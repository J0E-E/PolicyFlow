"""DB tests for the batch overlay helper (`app.renewals.overlay`, P2.4 Epic 13).

`renewal_due_policy_ids` is the shared set/batch form of the derive-at-read *Renewal
Due* predicate (ADR 0005), lifted out of `get_opportunity_policy`'s inline check so
the household policy list resolves every policy in one query (no N+1). Given a set of
policy ids and the caller's demo session, it returns which of those policies read
*Renewal Due* — i.e. the session holds an `origin='renewal'` opportunity pointing at
them. These pin the two load-bearing qualifiers: the `origin='renewal'` filter (a
`cross_sell` opportunity also sets `source_policy_id`) and the session scoping.

Everything runs inside one **uncommitted** scoped session (mirrors
`test_renewal_generation`): flushed rows are visible to reads in the same transaction
and roll back on exit, so nothing leaks into the shared container.

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no decorator.
"""

import uuid
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.opportunity import Opportunity
from app.renewals.overlay import renewal_due_policy_ids
from app.tenancy.registry import SUNSHINE


@asynccontextmanager
async def _scoped_session(database_engine, schema_name):
    """Yield a `search_path`-scoped session, rolled back on exit (no commit, no leak)."""
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    async with session_factory() as session:
        await session.execute(text(f"SET search_path TO {schema_name}"))
        try:
            yield session
        finally:
            await session.rollback()


def _opportunity(*, origin, source_policy_id, demo_session_id, renewal_cycle=None):
    """A minimal opportunity carrying only the fields the helper's predicate reads."""
    return Opportunity(
        contact_id=uuid.uuid4(),
        household_id=uuid.uuid4(),
        product_line="medicare_advantage",
        stage="New",
        origin=origin,
        owner_user_id=uuid.uuid4(),
        owner_username="agent.one",
        source_lead_id=None,
        source_policy_id=source_policy_id,
        renewal_cycle=renewal_cycle,
        correlation_id=uuid.uuid4(),
        demo_session_id=demo_session_id,
    )


async def test_returns_only_renewal_backed_ids_in_the_session(database_engine):
    """Of the passed ids, only those with a session renewal opportunity come back."""
    session_id = uuid.uuid4()
    renewed_policy_id = uuid.uuid4()
    bare_policy_id = uuid.uuid4()
    async with _scoped_session(database_engine, SUNSHINE.schema_name) as db:
        db.add(
            _opportunity(
                origin="renewal",
                source_policy_id=renewed_policy_id,
                demo_session_id=session_id,
                renewal_cycle="aep-2026",
            )
        )
        await db.flush()

        result = await renewal_due_policy_ids(
            db, {renewed_policy_id, bare_policy_id}, session_id
        )

    assert result == {renewed_policy_id}


async def test_ignores_cross_sell_origin(database_engine):
    """A `cross_sell` opportunity sets `source_policy_id` but never lifts the overlay."""
    session_id = uuid.uuid4()
    policy_id = uuid.uuid4()
    async with _scoped_session(database_engine, SUNSHINE.schema_name) as db:
        db.add(
            _opportunity(
                origin="cross_sell",
                source_policy_id=policy_id,
                demo_session_id=session_id,
            )
        )
        await db.flush()

        result = await renewal_due_policy_ids(db, {policy_id}, session_id)

    assert result == set()


async def test_ignores_renewals_from_another_session(database_engine):
    """A renewal in a different session does not lift the caller's policy."""
    caller_session_id = uuid.uuid4()
    other_session_id = uuid.uuid4()
    policy_id = uuid.uuid4()
    async with _scoped_session(database_engine, SUNSHINE.schema_name) as db:
        db.add(
            _opportunity(
                origin="renewal",
                source_policy_id=policy_id,
                demo_session_id=other_session_id,
                renewal_cycle="aep-2026",
            )
        )
        await db.flush()

        result = await renewal_due_policy_ids(db, {policy_id}, caller_session_id)

    assert result == set()


async def test_no_session_or_no_ids_returns_empty(database_engine):
    """A session-less caller or an empty id set short-circuits to the empty set."""
    policy_id = uuid.uuid4()
    async with _scoped_session(database_engine, SUNSHINE.schema_name) as db:
        assert await renewal_due_policy_ids(db, {policy_id}, None) == set()
        assert await renewal_due_policy_ids(db, set(), uuid.uuid4()) == set()
