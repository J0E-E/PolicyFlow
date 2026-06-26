"""DB-backed proof of the decline → supersession thread (P2.3 Epic 10).

The second acceptance thread: a declined application is retained read-only and the
opportunity returns to *Quoted* (D11/C3); re-selecting a different attached quote
creates a fresh `Draft` and marks the prior declined application `Superseded`
(linking it), with exactly one active application per opportunity enforced (C5,
backstopped by the partial unique index of migration 0019).

Builds a deny-email Draft application (reusing `test_application_submit`'s seam),
declines it, then re-selects. Drives the real endpoints over the DB-backed client
and reads the stored rows back over the SELECT-capable superuser engine.

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no decorator.
"""

import uuid

from sqlalchemy import text

from app.tenancy.registry import SUNSHINE

from tests.test_endpoints_db import login_as, seeded  # noqa: F401
from tests.test_lead_reads import unique_marker
from tests.test_application_submit import submit_ready_application
from tests.test_quote_round_trip import container_quotes_session_factory  # noqa: F401


def deny_email():
    return f"deny.{unique_marker()}@{SUNSHINE.email_domain}"


async def read_application(database_engine, application_id):
    """Read an application's status + supersede link via the superuser engine."""
    async with database_engine.connect() as connection:
        return (
            await connection.execute(
                text(
                    "SELECT status, selected_quote_id, superseded_by_application_id "
                    f"FROM {SUNSHINE.schema_name}.applications WHERE id = :id"
                ),
                {"id": application_id},
            )
        ).one()


async def read_quote_ids(database_engine, opportunity_id):
    """Return the attached quote ids for an opportunity (superuser read)."""
    async with database_engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    f"SELECT id FROM {SUNSHINE.schema_name}.quotes "
                    "WHERE opportunity_id = :id ORDER BY id"
                ),
                {"id": opportunity_id},
            )
        ).all()
    return [row.id for row in rows]


async def read_opportunity_stage(database_engine, opportunity_id):
    async with database_engine.connect() as connection:
        return (
            await connection.execute(
                text(
                    f"SELECT stage FROM {SUNSHINE.schema_name}.opportunities WHERE id = :id"
                ),
                {"id": opportunity_id},
            )
        ).scalar_one()


async def test_decline_returns_the_opportunity_to_quoted(
    db_client, database_engine, seeded, container_quotes_session_factory
):
    """A decline returns the opportunity to *Quoted* (re-selectable), app left Declined."""
    application_id, opportunity_id = await submit_ready_application(
        db_client, database_engine, email=deny_email()
    )
    submit = await db_client.post(f"/api/applications/{application_id}/submit")
    assert submit.json()["application"]["status"] == "Declined"

    assert await read_opportunity_stage(database_engine, opportunity_id) == "Quoted"
    stored = await read_application(database_engine, uuid.UUID(application_id))
    assert stored.status == "Declined"


async def test_reselection_after_decline_supersedes_and_opens_a_fresh_draft(
    db_client, database_engine, seeded, container_quotes_session_factory
):
    """Re-selecting a different quote supersedes the declined app and opens a new Draft."""
    first_id, opportunity_id = await submit_ready_application(
        db_client, database_engine, email=deny_email()
    )
    await db_client.post(f"/api/applications/{first_id}/submit")  # declines

    # Re-select a different attached quote.
    first = await read_application(database_engine, uuid.UUID(first_id))
    quote_ids = await read_quote_ids(database_engine, opportunity_id)
    different_quote = next(qid for qid in quote_ids if qid != first.selected_quote_id)
    reselect = await db_client.post(
        f"/api/opportunities/{opportunity_id}/applications",
        json={"quote_id": str(different_quote)},
    )
    assert reselect.status_code == 200
    second_id = reselect.json()["application"]["id"]
    assert second_id != first_id
    assert reselect.json()["application"]["status"] == "Draft"

    # The prior declined application is now Superseded, linked to the new one.
    superseded = await read_application(database_engine, uuid.UUID(first_id))
    assert superseded.status == "Superseded"
    assert str(superseded.superseded_by_application_id) == second_id
    # The opportunity is back on the money path.
    assert (
        await read_opportunity_stage(database_engine, opportunity_id)
        == "Application Started"
    )


async def test_one_active_application_per_opportunity_is_enforced(
    db_client, database_engine, seeded, container_quotes_session_factory
):
    """While a Draft is active, selecting another quote is a 409 (one active, C5)."""
    application_id, opportunity_id = await submit_ready_application(
        db_client, database_engine, email=deny_email(), capture_step=False
    )
    # The first Draft is still active; force the opportunity back to Quoted (without a
    # decline) so the stage precondition passes and the one-active rule is what bites.
    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                f"UPDATE {SUNSHINE.schema_name}.opportunities SET stage = 'Quoted' "
                "WHERE id = :id"
            ),
            {"id": opportunity_id},
        )
    quote_ids = await read_quote_ids(database_engine, opportunity_id)
    second = await db_client.post(
        f"/api/opportunities/{opportunity_id}/applications",
        json={"quote_id": str(quote_ids[0])},
    )
    assert second.status_code == 409
