"""DB-backed proof that the purge sweeps the P2.1 conversion entities (Epic 10).

Migration 0015's four conversion tables (`households` / `contacts` / `opportunities`
/ `tasks`) carry `demo_session_id`, so a session reset must remove a session's
conversion overlay alongside its leads. These convert a real lead **inside a demo
session** (so the created entities are session-tagged) and then run the purge engine,
asserting the session's conversion rows are gone — and that an *unrelated* session's
purge leaves them untouched (the isolation invariant).

The purge engine opens its own session as the `demo_purge` role through the
module-global `app.demo.purge.session_factory`; this file points that global at the
container database with the same per-file monkeypatch fixture the other purge tests
use. Seams reused from the convert test.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.demo import purge as purge_module
from app.demo.purge import Session, purge_sessions
from app.demo.session import DEMO_SESSION_COOKIE_NAME
from app.tenancy.registry import SUNSHINE

from tests.test_endpoints_db import login_as, seeded  # noqa: F401
from tests.test_lead_convert import convert_body, login_agent_and_insert_qualified_lead
from tests.test_lead_reads import mint_live_demo_session

CONVERSION_TABLES = ("households", "contacts", "opportunities", "tasks")


@pytest.fixture
def container_purge_session_factory(database_engine, monkeypatch):
    """Point `app.demo.purge.session_factory` at the migrated container database."""
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    monkeypatch.setattr(purge_module, "session_factory", session_factory)
    return session_factory


async def count_for_session(database_engine, table_name, demo_session_id):
    """Count `<sunshine>.<table>` rows tagged with `demo_session_id`."""
    async with database_engine.connect() as connection:
        return (
            await connection.execute(
                text(
                    f"SELECT COUNT(*) FROM {SUNSHINE.schema_name}.{table_name} "
                    "WHERE demo_session_id = :demo_session_id"
                ),
                {"demo_session_id": demo_session_id},
            )
        ).scalar_one()


async def convert_in_session(db_client, database_engine, session_id):
    """Convert a fresh lead while carrying `session_id`, so its entities are tagged."""
    # The helper logs the agent in and inserts a Qualified lead tagged with this
    # session; carry the demo-session cookie so the convert (and the entities it
    # creates) resolve to the same session.
    _, lead_id, _ = await login_agent_and_insert_qualified_lead(
        db_client,
        database_engine,
        notes="Call in the morning.",
        demo_session_id=session_id,
    )
    db_client.cookies.set(DEMO_SESSION_COOKIE_NAME, str(session_id))
    response = await db_client.post(
        f"/api/leads/{lead_id}/convert", json=convert_body()
    )
    assert response.status_code == 200
    return lead_id


async def test_purge_removes_a_sessions_conversion_entities(
    seeded, db_client, database_engine, container_purge_session_factory
):
    """A session reset removes that session's household/contact/opportunity/task rows."""
    session_id = await mint_live_demo_session(database_engine)
    await convert_in_session(db_client, database_engine, session_id)

    # The conversion wrote session-tagged rows in every conversion table (notes → task).
    for table_name in CONVERSION_TABLES:
        assert await count_for_session(database_engine, table_name, session_id) >= 1

    counts = await purge_sessions(Session(session_id), delete_session_row=False)

    # Every conversion table for this session is now empty, and the purge counted them.
    for table_name in CONVERSION_TABLES:
        assert await count_for_session(database_engine, table_name, session_id) == 0
    assert counts.households_deleted[SUNSHINE.schema_name] >= 1
    assert counts.contacts_deleted[SUNSHINE.schema_name] >= 1
    assert counts.opportunities_deleted[SUNSHINE.schema_name] >= 1
    assert counts.tasks_deleted[SUNSHINE.schema_name] >= 1


async def test_purge_of_another_session_leaves_these_entities(
    seeded, db_client, database_engine, container_purge_session_factory
):
    """Purging an unrelated session removes none of this session's conversion entities."""
    session_id = await mint_live_demo_session(database_engine)
    await convert_in_session(db_client, database_engine, session_id)

    # Purge a different, unrelated session id.
    await purge_sessions(Session(uuid.uuid4()), delete_session_row=False)

    # This session's conversion entities all survive — the purge is session-scoped.
    for table_name in CONVERSION_TABLES:
        assert await count_for_session(database_engine, table_name, session_id) >= 1
