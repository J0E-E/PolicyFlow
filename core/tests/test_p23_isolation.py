"""DB-backed proof of demo-session isolation for the P2.3 records (Epic 12).

Every new record type — quote requests, quotes, applications, policies — and the
carrier-quote stub respect demo-session isolation (D13): a visitor never sees or
mutates another session's records, the stub propagates the session through the
round-trip, and a session reset purges all four record types.

Builds the money-path records (reusing the submit seam), re-tags them to a live demo
session, and exercises the isolation guards + the purge sweep. Reads over the
SELECT-capable superuser engine.

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no decorator.
"""

import uuid

from sqlalchemy import text

from app.demo.purge import Session, purge_sessions
from app.tenancy.registry import SUNSHINE

from tests.test_endpoints_db import login_as, seeded  # noqa: F401
from tests.test_lead_reads import mint_live_demo_session, tenant_id_for_slug
from tests.test_application_submit import submit_ready_application
from tests.test_conversion_purge import container_purge_session_factory  # noqa: F401
from tests.test_quote_round_trip import (
    HAPPY_PATH_LINE,
    container_quotes_session_factory,  # noqa: F401
    qualified_opportunity,
    quote_requested_envelope,
)
from app.quotes import service as quotes_service_module

P23_TABLES = ("quote_requests", "quotes", "applications", "policies")


async def retag_records_to_session(database_engine, opportunity_id, session_id):
    """Tag every P2.3 record for an opportunity with `session_id` (superuser write)."""
    async with database_engine.begin() as connection:
        for table_name in P23_TABLES:
            await connection.execute(
                text(
                    f"UPDATE {SUNSHINE.schema_name}.{table_name} "
                    "SET demo_session_id = :sid WHERE opportunity_id = :oid"
                ),
                {"sid": session_id, "oid": opportunity_id},
            )


async def count_for_session(database_engine, table_name, session_id):
    async with database_engine.connect() as connection:
        return (
            await connection.execute(
                text(
                    f"SELECT COUNT(*) FROM {SUNSHINE.schema_name}.{table_name} "
                    "WHERE demo_session_id = :sid"
                ),
                {"sid": session_id},
            )
        ).scalar_one()


async def test_a_reset_purges_all_four_p23_record_types(
    db_client,
    database_engine,
    seeded,
    container_quotes_session_factory,
    container_purge_session_factory,
):
    """A session reset removes the session's quote requests, quotes, applications, policies."""
    application_id, opportunity_id = await submit_ready_application(db_client, database_engine)
    # Approve → a policy is issued, so all four record types now exist.
    await db_client.post(f"/api/applications/{application_id}/submit")

    session_id = await mint_live_demo_session(database_engine)
    await retag_records_to_session(database_engine, opportunity_id, session_id)
    for table_name in P23_TABLES:
        assert await count_for_session(database_engine, table_name, session_id) >= 1

    counts = await purge_sessions(Session(session_id), delete_session_row=False)

    # Every P2.3 table for this session is now empty, and the purge counted each.
    for table_name in P23_TABLES:
        assert await count_for_session(database_engine, table_name, session_id) == 0
    assert counts.quote_requests_deleted[SUNSHINE.schema_name] >= 1
    assert counts.quotes_deleted[SUNSHINE.schema_name] >= 1
    assert counts.applications_deleted[SUNSHINE.schema_name] >= 1
    assert counts.policies_deleted[SUNSHINE.schema_name] >= 1


async def test_a_foreign_sessions_quote_request_is_a_404(
    db_client, database_engine, seeded, container_quotes_session_factory
):
    """A session-less caller cannot poll another session's quote request (404)."""
    opportunity_id = await qualified_opportunity(db_client, database_engine, HAPPY_PATH_LINE)
    request_response = await db_client.post(
        f"/api/opportunities/{opportunity_id}/quote-requests"
    )
    quote_request_id = request_response.json()["quote_request"]["id"]

    # Tag the quote request to a foreign session; the session-less caller now sees a 404.
    foreign_session = await mint_live_demo_session(database_engine)
    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                f"UPDATE {SUNSHINE.schema_name}.quote_requests "
                "SET demo_session_id = :sid WHERE id = :id"
            ),
            {"sid": foreign_session, "id": uuid.UUID(quote_request_id)},
        )

    poll = await db_client.get(
        f"/api/opportunities/{opportunity_id}/quote-requests/{quote_request_id}"
    )
    assert poll.status_code == 404


async def test_the_stub_propagates_the_session_through_the_round_trip(
    db_client, database_engine, seeded, container_quotes_session_factory
):
    """The carrier-quote stub stamps the request's demo_session_id onto its quotes."""
    opportunity_id = await qualified_opportunity(db_client, database_engine, HAPPY_PATH_LINE)
    tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    request_response = await db_client.post(
        f"/api/opportunities/{opportunity_id}/quote-requests"
    )
    quote_request_id = uuid.UUID(request_response.json()["quote_request"]["id"])

    # Tag the pending request to a session before the stub runs.
    session_id = await mint_live_demo_session(database_engine)
    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                f"UPDATE {SUNSHINE.schema_name}.quote_requests "
                "SET demo_session_id = :sid WHERE id = :id"
            ),
            {"sid": session_id, "id": quote_request_id},
        )

    await quotes_service_module.complete_quote_request(
        quote_requested_envelope(tenant_id, quote_request_id, opportunity_id, HAPPY_PATH_LINE),
        SUNSHINE.schema_name,
    )

    # The generated quotes carry the request's session id — the stub propagated it.
    async with database_engine.connect() as connection:
        session_ids = (
            await connection.execute(
                text(
                    f"SELECT DISTINCT demo_session_id FROM {SUNSHINE.schema_name}.quotes "
                    "WHERE quote_request_id = :id"
                ),
                {"id": quote_request_id},
            )
        ).scalars().all()
    assert session_ids == [session_id]
