"""DB-backed proof of the product-specific application step (P2.3 Epic 6).

`PATCH /api/applications/{id}` captures the step a Draft application's product line
requires — the beneficiary details (life lines) or the five health answers (health
lines), chosen by `ProductLine.application_step` (D10). A line with no step
(Medicare / dental) rejects the call; a non-Draft application is frozen.

Builds a Draft application the honest way (round-trip → select) for the line under
test, then PATCHes it. Drives the real endpoints over the DB-backed client and reads
the stored row back over the SELECT-capable superuser engine.

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no decorator.
"""

import uuid

from sqlalchemy import text

from app.tenancy.registry import FLORIDA, SUNSHINE

from tests.test_endpoints_db import login_as, seeded  # noqa: F401
from tests.test_lead_reads import tenant_id_for_slug
from tests.test_opportunity_stage import convert_opportunity_for_slug, set_stage
from tests.test_quote_round_trip import (
    container_quotes_session_factory,  # noqa: F401
    quote_requested_envelope,
)
from app.quotes import service as quotes_service_module

VALID_BENEFICIARY = {
    "full_name": "Jordan Rivera",
    "relationship": "spouse",
    "date_of_birth": "1972-04-18",
}
VALID_HEALTH = {
    "tobacco_use": False,
    "hospitalized_recently": False,
    "chronic_condition": True,
    "prescription_medications": True,
    "family_history": False,
}


async def draft_application(db_client, database_engine, tenant, product_line):
    """Build a Draft application for `(tenant, product_line)` the honest way; return it.

    Converts an opportunity on the line, forces it to *Qualified*, runs the quote
    round-trip to completion, then selects the first attached quote. Returns the
    select response's application dict. The `db_client` is left logged in as the
    owning agent.
    """
    opportunity_id = await convert_opportunity_for_slug(
        db_client, database_engine, tenant, product_line
    )
    await set_stage(database_engine, tenant.schema_name, opportunity_id, "Qualified")
    tenant_id = await tenant_id_for_slug(database_engine, tenant.slug)
    request_response = await db_client.post(
        f"/api/opportunities/{opportunity_id}/quote-requests"
    )
    quote_request_id = uuid.UUID(request_response.json()["quote_request"]["id"])
    await quotes_service_module.complete_quote_request(
        quote_requested_envelope(tenant_id, quote_request_id, opportunity_id, product_line),
        tenant.schema_name,
    )
    poll = (
        await db_client.get(
            f"/api/opportunities/{opportunity_id}/quote-requests/{quote_request_id}"
        )
    ).json()
    selection = await db_client.post(
        f"/api/opportunities/{opportunity_id}/applications",
        json={"quote_id": poll["quotes"][0]["id"]},
    )
    return selection.json()["application"]


async def read_application_jsonb(database_engine, schema_name, application_id, column):
    """Read one jsonb column off an application via the SELECT-capable superuser engine."""
    async with database_engine.connect() as connection:
        return (
            await connection.execute(
                text(
                    f"SELECT {column} FROM {schema_name}.applications WHERE id = :id"
                ),
                {"id": application_id},
            )
        ).scalar_one()


async def test_beneficiary_step_is_captured_on_a_life_line(
    db_client, database_engine, seeded, container_quotes_session_factory
):
    """A `final_expense` (beneficiary) application captures its beneficiary details."""
    application = await draft_application(db_client, database_engine, SUNSHINE, "final_expense")
    assert application["application_step"] == "beneficiary"

    response = await db_client.patch(
        f"/api/applications/{application['id']}", json={"beneficiary": VALID_BENEFICIARY}
    )
    assert response.status_code == 200
    assert response.json()["application"]["beneficiary"] == VALID_BENEFICIARY

    stored = await read_application_jsonb(
        database_engine, SUNSHINE.schema_name, uuid.UUID(application["id"]), "beneficiary"
    )
    assert stored == VALID_BENEFICIARY


async def test_beneficiary_step_rejects_a_missing_field(
    db_client, database_engine, seeded, container_quotes_session_factory
):
    """A beneficiary payload missing a required field is a 422."""
    application = await draft_application(db_client, database_engine, SUNSHINE, "final_expense")
    response = await db_client.patch(
        f"/api/applications/{application['id']}",
        json={"beneficiary": {"full_name": "Jordan Rivera", "relationship": "spouse"}},
    )
    assert response.status_code == 422


async def test_health_step_is_captured_on_a_health_line(
    db_client, database_engine, seeded, container_quotes_session_factory
):
    """A Florida `health` application captures its five health answers."""
    application = await draft_application(db_client, database_engine, FLORIDA, "health")
    assert application["application_step"] == "health"

    response = await db_client.patch(
        f"/api/applications/{application['id']}", json={"health_answers": VALID_HEALTH}
    )
    assert response.status_code == 200
    assert response.json()["application"]["health_answers"] == VALID_HEALTH


async def test_wrong_payload_for_the_step_is_rejected(
    db_client, database_engine, seeded, container_quotes_session_factory
):
    """Sending health answers for a beneficiary line is a 422 (wrong step payload)."""
    application = await draft_application(db_client, database_engine, SUNSHINE, "final_expense")
    response = await db_client.patch(
        f"/api/applications/{application['id']}", json={"health_answers": VALID_HEALTH}
    )
    assert response.status_code == 422


async def test_a_line_with_no_step_rejects_capture(
    db_client, database_engine, seeded, container_quotes_session_factory
):
    """A `dental_vision_hearing` line has no step, so any capture is a 422."""
    application = await draft_application(
        db_client, database_engine, SUNSHINE, "dental_vision_hearing"
    )
    assert application["application_step"] is None
    response = await db_client.patch(
        f"/api/applications/{application['id']}", json={"beneficiary": VALID_BENEFICIARY}
    )
    assert response.status_code == 422


async def test_a_non_draft_application_cannot_capture_its_step(
    db_client, database_engine, seeded, container_quotes_session_factory
):
    """Once an application is no longer Draft its step is frozen — a 409."""
    application = await draft_application(db_client, database_engine, SUNSHINE, "final_expense")
    # Force the application past Draft (submit is Epic 7) to prove the Draft-only guard.
    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                f"UPDATE {SUNSHINE.schema_name}.applications SET status = 'Submitted' "
                "WHERE id = :id"
            ),
            {"id": uuid.UUID(application["id"])},
        )
    response = await db_client.patch(
        f"/api/applications/{application['id']}", json={"beneficiary": VALID_BENEFICIARY}
    )
    assert response.status_code == 409
