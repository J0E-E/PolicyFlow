"""DB-backed proof of submit + the inline carrier decision (P2.3 Epic 7).

`POST /api/applications/{id}/submit` moves a Draft application to *Submitted*, then
runs the deterministic inline carrier decision: the contact's decrypted email with a
`deny` substring forces a decline, else an approve (the value is never returned). The
outcome couples to the opportunity — *Submitted* then *Approved* on approve, left at
*Submitted* on decline (the return + supersession are Epic 10) — and emits the
lifecycle events. Policy issuance is Epic 8.

Builds a submit-ready Draft application the honest way (convert → round-trip →
select → capture step), with a controllable applicant email so the decline path can
be exercised. Drives the real endpoints over the DB-backed client.

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no decorator.
"""

import uuid

from sqlalchemy import text

from app.events.catalog import EventType
from app.leads.state import LeadStatus
from app.tenancy.registry import SUNSHINE

from tests.test_endpoints_db import login_as, seeded  # noqa: F401
from tests.test_lead_convert import read_one
from tests.test_lead_intake import read_outbox_rows_for_entity
from tests.test_lead_reads import (
    insert_lead,
    login_agent_for_slug,
    tenant_id_for_slug,
    unique_contact,
    unique_marker,
)
from tests.test_opportunity_stage import set_stage
from tests.test_quote_round_trip import (
    container_quotes_session_factory,  # noqa: F401
    quote_requested_envelope,
)
from app.quotes import service as quotes_service_module

BENEFICIARY = {
    "full_name": "Jordan Rivera",
    "relationship": "spouse",
    "date_of_birth": "1970-01-01",
}


async def submit_ready_application(
    db_client, database_engine, *, email=None, capture_step=True, product_line="final_expense"
):
    """Build a submit-ready Draft Sunshine application; return `(application_id, opportunity_id)`.

    Converts a Qualified lead (with `email`, or a random one) on `product_line`, runs
    the quote round-trip, selects the first quote, and — unless `capture_step` is
    False — captures the beneficiary step. The `db_client` is left logged in as the
    owning agent.
    """
    login = await login_agent_for_slug(db_client, SUNSHINE.slug)
    agent_id = uuid.UUID(login.json()["user"]["id"])
    tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    default_email, phone = unique_contact()
    lead_id = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        tenant_id,
        first_name=unique_marker(),
        email=email or default_email,
        phone=phone,
        status=LeadStatus.QUALIFIED,
        owner_user_id=agent_id,
        owner_username=f"agent@{SUNSHINE.email_domain}",
    )
    convert = await db_client.post(
        f"/api/leads/{lead_id}/convert",
        json={"household": {"mode": "new"}, "product_lines": [product_line]},
    )
    contact_id = uuid.UUID(convert.json()["lead"]["converted_contact_id"])
    opportunity = await read_one(
        database_engine,
        f"SELECT id FROM {SUNSHINE.schema_name}.opportunities WHERE contact_id = :id",
        {"id": contact_id},
    )
    await set_stage(database_engine, SUNSHINE.schema_name, opportunity.id, "Qualified")

    request_response = await db_client.post(
        f"/api/opportunities/{opportunity.id}/quote-requests"
    )
    quote_request_id = uuid.UUID(request_response.json()["quote_request"]["id"])
    await quotes_service_module.complete_quote_request(
        quote_requested_envelope(tenant_id, quote_request_id, opportunity.id, product_line),
        SUNSHINE.schema_name,
    )
    poll = (
        await db_client.get(
            f"/api/opportunities/{opportunity.id}/quote-requests/{quote_request_id}"
        )
    ).json()
    selection = await db_client.post(
        f"/api/opportunities/{opportunity.id}/applications",
        json={"quote_id": poll["quotes"][0]["id"]},
    )
    application_id = selection.json()["application"]["id"]
    if capture_step:
        await db_client.patch(
            f"/api/applications/{application_id}", json={"beneficiary": BENEFICIARY}
        )
    return application_id, opportunity.id


async def read_application(database_engine, application_id):
    """Read an application's status / decision / decided_at via the superuser engine."""
    async with database_engine.connect() as connection:
        return (
            await connection.execute(
                text(
                    f"SELECT status, decision, decided_at "
                    f"FROM {SUNSHINE.schema_name}.applications WHERE id = :id"
                ),
                {"id": application_id},
            )
        ).one()


async def test_submit_approves_by_default_and_advances_the_opportunity(
    db_client, database_engine, seeded, container_quotes_session_factory
):
    """A normal applicant email approves: app → Approved, opportunity → Policy Active.

    Approval auto-issues the policy (Epic 8), so the opportunity reaches *Policy
    Active* and the submit response carries the issued policy.
    """
    application_id, opportunity_id = await submit_ready_application(db_client, database_engine)

    response = await db_client.post(f"/api/applications/{application_id}/submit")
    assert response.status_code == 200
    body = response.json()
    assert body["application"]["status"] == "Approved"
    assert body["application"]["decision"] == "approved"
    assert body["opportunity_stage"] == "Policy Active"
    assert body["policy"] is not None
    assert body["policy"]["status"] == "Active"

    stored = await read_application(database_engine, uuid.UUID(application_id))
    assert stored.status == "Approved"
    assert stored.decision == "approved"
    assert stored.decided_at is not None

    # The lifecycle events fired: submitted then approved.
    for event_type in (EventType.APPLICATION_SUBMITTED, EventType.APPLICATION_APPROVED):
        rows = await read_outbox_rows_for_entity(
            database_engine, SUNSHINE.schema_name, event_type, uuid.UUID(application_id)
        )
        assert len(rows) == 1, event_type


async def test_submit_declines_when_the_contact_email_contains_deny(
    db_client, database_engine, seeded, container_quotes_session_factory
):
    """A `deny` applicant email declines: app → Declined, opportunity stays Submitted."""
    deny_email = f"deny.{unique_marker()}@{SUNSHINE.email_domain}"
    application_id, opportunity_id = await submit_ready_application(
        db_client, database_engine, email=deny_email
    )

    response = await db_client.post(f"/api/applications/{application_id}/submit")
    assert response.status_code == 200
    body = response.json()
    assert body["application"]["status"] == "Declined"
    assert body["application"]["decision"] == "declined"
    # The decline does not advance the opportunity (Epic 10 returns it to Quoted).
    assert body["opportunity_stage"] == "Submitted"
    # No policy is issued on a decline.
    assert body["policy"] is None
    # The decrypted email is never echoed back in the response.
    assert "deny" not in response.text.lower()

    declined_rows = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.APPLICATION_DECLINED, uuid.UUID(application_id)
    )
    assert len(declined_rows) == 1


async def test_submit_requires_a_completed_step(
    db_client, database_engine, seeded, container_quotes_session_factory
):
    """A beneficiary line with no captured step cannot be submitted — a 409."""
    application_id, _ = await submit_ready_application(
        db_client, database_engine, capture_step=False
    )
    response = await db_client.post(f"/api/applications/{application_id}/submit")
    assert response.status_code == 409


async def test_a_decided_application_cannot_be_submitted_again(
    db_client, database_engine, seeded, container_quotes_session_factory
):
    """Submitting an already-decided application is a 409 (no longer Draft)."""
    application_id, _ = await submit_ready_application(db_client, database_engine)
    first = await db_client.post(f"/api/applications/{application_id}/submit")
    assert first.status_code == 200
    second = await db_client.post(f"/api/applications/{application_id}/submit")
    assert second.status_code == 409
