"""The named P2.3 acceptance suite — Quotes → Application → Policy, end to end.

Epics 1–13 built every piece of the money path: the event vocabulary + the
`carrier.quote` non-terminal stub, the registry catalog, the quote round-trip, the
pure application state machine, quote selection → Draft Application, the
product-specific step, submit + the inline carrier decision, policy issuance, the
opportunity-coupling lockdown, decline → supersession, the Tenant-1 Medicare ID, and
demo-session isolation. This file is the single named proof that the whole phase
contract holds end-to-end on the real Postgres + RabbitMQ substrate.

It adds **no production code.** It drives the already-assembled path through the real
HTTP endpoints over the DB-backed client, and invokes the `carrier.quote` consumer
effect directly (the relay/consumer lifespan does not run under `ASGITransport`,
exactly as the broker round-trip tests do). Five proofs:

1. **Happy path → issued Policy.** A Qualified opportunity requests quotes (round-trip
   to *Quoted*), selects one (→ Draft, *Application Started*), captures the beneficiary
   step + the Medicare ID, and submits — the inline decision approves, a Policy is
   issued with a deterministic number, the opportunity reaches *Policy Active*, and the
   Medicare ID is masked on the reads and revealed by the audited endpoint.
2. **Decline → supersession.** A `deny`-email applicant declines on submit; the
   opportunity returns to *Quoted*; re-selecting a different quote opens a fresh Draft
   and marks the prior declined application *Superseded*.
3. **Coupling lockdown.** The automation drives the opportunity's automation-owned
   stages; a manual `POST /stage` into one is rejected (422).
4. **Tenant isolation.** Tenant-2 (Florida) neither renders nor reveals a Medicare ID.
5. **Session isolation.** A foreign session cannot poll another session's quote request.

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no decorator.
"""

import uuid

from sqlalchemy import text

from app.tenancy.registry import FLORIDA, SUNSHINE

from tests.test_endpoints_db import seeded  # noqa: F401
from tests.test_lead_reads import tenant_id_for_slug, unique_marker
from tests.test_application_step import draft_application
from tests.test_application_submit import submit_ready_application
from tests.test_quote_round_trip import (
    container_quotes_session_factory,  # noqa: F401
    qualified_opportunity,
    quote_requested_envelope,
)
from app.quotes import service as quotes_service_module

BENEFICIARY = {"full_name": "Jordan Rivera", "relationship": "spouse", "date_of_birth": "1972-04-18"}
MEDICARE_ID = "1EG4TE5MK73"


async def run_round_trip(db_client, database_engine, opportunity_id, product_line):
    """Request quotes for a Qualified opportunity and run the stub to *Quoted*; return the quotes."""
    tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    request_response = await db_client.post(
        f"/api/opportunities/{opportunity_id}/quote-requests"
    )
    quote_request_id = uuid.UUID(request_response.json()["quote_request"]["id"])
    await quotes_service_module.complete_quote_request(
        quote_requested_envelope(tenant_id, quote_request_id, opportunity_id, product_line),
        SUNSHINE.schema_name,
    )
    poll = (
        await db_client.get(
            f"/api/opportunities/{opportunity_id}/quote-requests/{quote_request_id}"
        )
    ).json()
    assert poll["quote_request"]["status"] == "completed"
    assert poll["opportunity_stage"] == "Quoted"
    return poll["quotes"]


# --- Proof 1: the happy path to an issued policy -----------------------------


async def test_happy_path_quote_to_issued_policy(
    db_client, database_engine, seeded, container_quotes_session_factory
):
    """Quote → select → step + Medicare → submit → approve → issued Policy, end to end."""
    opportunity_id = await qualified_opportunity(db_client, database_engine, "final_expense")
    quotes = await run_round_trip(db_client, database_engine, opportunity_id, "final_expense")

    # Select a quote → Draft Application, opportunity → Application Started.
    selection = await db_client.post(
        f"/api/opportunities/{opportunity_id}/applications",
        json={"quote_id": quotes[0]["id"]},
    )
    assert selection.status_code == 200
    application = selection.json()["application"]
    assert application["status"] == "Draft"
    application_id = application["id"]

    # Capture the beneficiary step + the Tenant-1 Medicare ID.
    capture = await db_client.patch(
        f"/api/applications/{application_id}",
        json={"beneficiary": BENEFICIARY, "medicare_id": MEDICARE_ID},
    )
    assert capture.status_code == 200
    assert capture.json()["application"]["medicare_id_masked"] is not None

    # Submit → the carrier approves, a policy is issued, the opportunity reaches Policy Active.
    submit = await db_client.post(f"/api/applications/{application_id}/submit")
    body = submit.json()
    assert body["application"]["status"] == "Approved"
    assert body["opportunity_stage"] == "Policy Active"
    assert body["policy"] is not None
    assert body["policy"]["policy_number"].startswith("POL-SUN-")
    # The Medicare ID is masked on the policy read, never the plaintext.
    assert body["policy"]["medicare_id_masked"] is not None
    assert MEDICARE_ID not in submit.text

    # The audited reveal returns the plaintext.
    reveal = await db_client.post(f"/api/applications/{application_id}/reveal-medicare-id")
    assert reveal.json() == {"field": "medicare_id", "value": MEDICARE_ID}


# --- Proof 2: decline → supersession -----------------------------------------


async def test_decline_returns_to_quoted_then_reselection_supersedes(
    db_client, database_engine, seeded, container_quotes_session_factory
):
    """A deny applicant declines; the opportunity returns to Quoted; re-selection supersedes."""
    deny_email = f"deny.{unique_marker()}@{SUNSHINE.email_domain}"
    first_application_id, opportunity_id = await submit_ready_application(
        db_client, database_engine, email=deny_email
    )

    declined = await db_client.post(f"/api/applications/{first_application_id}/submit")
    assert declined.json()["application"]["status"] == "Declined"
    assert declined.json()["opportunity_stage"] == "Quoted"

    # Re-select a different attached quote → a fresh Draft; the prior is Superseded.
    async with database_engine.connect() as connection:
        quote_ids = (
            await connection.execute(
                text(
                    f"SELECT id FROM {SUNSHINE.schema_name}.quotes "
                    "WHERE opportunity_id = :id ORDER BY id"
                ),
                {"id": opportunity_id},
            )
        ).scalars().all()
    reselect = await db_client.post(
        f"/api/opportunities/{opportunity_id}/applications",
        json={"quote_id": str(quote_ids[-1])},
    )
    assert reselect.status_code == 200
    assert reselect.json()["application"]["status"] == "Draft"

    async with database_engine.connect() as connection:
        prior_status = (
            await connection.execute(
                text(
                    f"SELECT status FROM {SUNSHINE.schema_name}.applications WHERE id = :id"
                ),
                {"id": uuid.UUID(first_application_id)},
            )
        ).scalar_one()
    assert prior_status == "Superseded"


# --- Proof 3: the coupling lockdown ------------------------------------------


async def test_manual_reach_into_an_automation_owned_stage_is_rejected(
    db_client, database_engine, seeded, container_quotes_session_factory
):
    """The automation owns *Application Started*+; a manual advance into it is a 422."""
    opportunity_id = await qualified_opportunity(db_client, database_engine, "final_expense")
    await run_round_trip(db_client, database_engine, opportunity_id, "final_expense")

    # The opportunity is Quoted; a manual advance to the automation-owned next stage 422s.
    blocked = await db_client.post(
        f"/api/opportunities/{opportunity_id}/stage",
        json={"target_stage": "Application Started"},
    )
    assert blocked.status_code == 422


# --- Proof 4: tenant isolation -----------------------------------------------


async def test_tenant_2_has_no_medicare_id_field(
    db_client, database_engine, seeded, container_quotes_session_factory
):
    """Florida neither renders nor reveals a Medicare ID (gated by the registry flag)."""
    application = await draft_application(db_client, database_engine, FLORIDA, "term_life")
    assert application["collects_medicare_id"] is False
    assert application["medicare_id_masked"] is None

    capture = await db_client.patch(
        f"/api/applications/{application['id']}", json={"medicare_id": MEDICARE_ID}
    )
    assert capture.status_code == 422
    reveal = await db_client.post(
        f"/api/applications/{application['id']}/reveal-medicare-id"
    )
    assert reveal.status_code == 422


# --- Proof 5: session isolation ----------------------------------------------


async def test_a_foreign_session_cannot_poll_a_quote_request(
    db_client, database_engine, seeded, container_quotes_session_factory
):
    """A session-less caller cannot poll another session's quote request (404)."""
    opportunity_id = await qualified_opportunity(db_client, database_engine, "final_expense")
    request_response = await db_client.post(
        f"/api/opportunities/{opportunity_id}/quote-requests"
    )
    quote_request_id = request_response.json()["quote_request"]["id"]

    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                f"UPDATE {SUNSHINE.schema_name}.quote_requests "
                "SET demo_session_id = :sid WHERE id = :id"
            ),
            {"sid": uuid.uuid4(), "id": uuid.UUID(quote_request_id)},
        )

    poll = await db_client.get(
        f"/api/opportunities/{opportunity_id}/quote-requests/{quote_request_id}"
    )
    assert poll.status_code == 404
