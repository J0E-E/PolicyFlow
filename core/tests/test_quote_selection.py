"""DB-backed proof of quote selection → Draft Application (P2.3 Epic 5).

Selecting an attached quote (`POST /api/opportunities/{id}/applications`) creates a
`Draft` `Application` with the carrier / product / coverage / premium copied from the
quote, advances the opportunity to *Application Started* via the internal stage-setter
(bypassing the manual machine), sets `estimated_annual_premium`, and emits
`application.started`.

Builds on the round-trip seams from `test_quote_round_trip.py`: it runs a real
round-trip to a *Quoted* opportunity with attached quotes, then selects one. Drives
the real endpoints over the DB-backed client and reads the stored rows / outbox back
over the SELECT-capable superuser engine.

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no decorator.
"""

import uuid

from sqlalchemy import text

from app.events.catalog import EventType
from app.tenancy.registry import SUNSHINE

from tests.test_endpoints_db import login_as, seeded  # noqa: F401
from tests.test_lead_intake import read_outbox_rows_for_entity
from tests.test_lead_reads import tenant_id_for_slug
from tests.test_opportunity_stage import set_stage
from tests.test_quote_round_trip import (
    HAPPY_PATH_LINE,
    container_quotes_session_factory,  # noqa: F401
    qualified_opportunity,
    quote_requested_envelope,
)
from app.quotes import service as quotes_service_module


async def quoted_opportunity_with_quotes(db_client, database_engine):
    """Run a round-trip to a *Quoted* opportunity; return `(opportunity_id, quote_ids)`.

    Requests quotes on a Qualified Sunshine opportunity, drives the consumer effect
    to completion (which attaches the quotes and moves the opportunity to *Quoted*),
    then reads back the attached quote ids. The `db_client` is left logged in as the
    owning agent.
    """
    opportunity_id = await qualified_opportunity(db_client, database_engine, HAPPY_PATH_LINE)
    tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    request_response = await db_client.post(
        f"/api/opportunities/{opportunity_id}/quote-requests"
    )
    quote_request_id = uuid.UUID(request_response.json()["quote_request"]["id"])
    await quotes_service_module.complete_quote_request(
        quote_requested_envelope(tenant_id, quote_request_id, opportunity_id, HAPPY_PATH_LINE),
        SUNSHINE.schema_name,
    )
    poll = (
        await db_client.get(
            f"/api/opportunities/{opportunity_id}/quote-requests/{quote_request_id}"
        )
    ).json()
    return opportunity_id, poll["quotes"]


async def read_opportunity(database_engine, schema_name, opportunity_id):
    """Read one opportunity's stage + estimated premium via the superuser engine."""
    async with database_engine.connect() as connection:
        return (
            await connection.execute(
                text(
                    f"SELECT stage, estimated_annual_premium "
                    f"FROM {schema_name}.opportunities WHERE id = :id"
                ),
                {"id": opportunity_id},
            )
        ).one()


async def test_selecting_a_quote_creates_a_draft_application_and_advances_the_opportunity(
    db_client, database_engine, seeded, container_quotes_session_factory
):
    """Selecting a quote copies its terms onto a Draft Application and moves the opportunity."""
    opportunity_id, quotes = await quoted_opportunity_with_quotes(db_client, database_engine)
    chosen = quotes[0]

    response = await db_client.post(
        f"/api/opportunities/{opportunity_id}/applications",
        json={"quote_id": chosen["id"]},
    )
    assert response.status_code == 200
    application = response.json()["application"]
    assert application["status"] == "Draft"
    # The carrier / product / coverage / premium are copied from the chosen quote.
    assert application["carrier"] == chosen["carrier"]
    assert application["product_label"] == chosen["product_label"]
    assert application["coverage_amount"] == chosen["coverage_amount"]
    assert application["premium_annual"] == chosen["premium_annual"]

    # The opportunity advanced to Application Started and took the quote's annual premium.
    opportunity = await read_opportunity(database_engine, SUNSHINE.schema_name, opportunity_id)
    assert opportunity.stage == "Application Started"
    assert int(opportunity.estimated_annual_premium) == chosen["premium_annual"]

    # Both events fired: application.started and the opportunity stage change.
    started_rows = await read_outbox_rows_for_entity(
        database_engine,
        SUNSHINE.schema_name,
        EventType.APPLICATION_STARTED,
        uuid.UUID(application["id"]),
    )
    assert len(started_rows) == 1
    stage_rows = await read_outbox_rows_for_entity(
        database_engine,
        SUNSHINE.schema_name,
        EventType.OPPORTUNITY_STAGE_CHANGED,
        opportunity_id,
    )
    assert any(row.payload["to_stage"] == "Application Started" for row in stage_rows)


async def test_selecting_a_quote_requires_a_quoted_opportunity(
    db_client, database_engine, seeded, container_quotes_session_factory
):
    """Selecting against an opportunity that is not *Quoted* is a 409."""
    opportunity_id, quotes = await quoted_opportunity_with_quotes(db_client, database_engine)
    # Force the opportunity back to Qualified so it is no longer selectable.
    await set_stage(database_engine, SUNSHINE.schema_name, opportunity_id, "Qualified")

    response = await db_client.post(
        f"/api/opportunities/{opportunity_id}/applications",
        json={"quote_id": quotes[0]["id"]},
    )
    assert response.status_code == 409


async def test_selecting_a_quote_from_another_opportunity_is_not_found(
    db_client, database_engine, seeded, container_quotes_session_factory
):
    """A quote id that does not belong to the opportunity is a 404."""
    opportunity_id, _ = await quoted_opportunity_with_quotes(db_client, database_engine)
    response = await db_client.post(
        f"/api/opportunities/{opportunity_id}/applications",
        json={"quote_id": str(uuid.uuid4())},
    )
    assert response.status_code == 404
