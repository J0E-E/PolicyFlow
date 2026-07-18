"""Substrate proof for migration 0020 — renewal / cross-sell columns + index.

These assert the database state after `upgrade head` against the real Postgres
booted in Docker (the same `database_engine` substrate as
`test_lead_conversion_migration.py`). Every expected value is read from
`app.tenancy.registry`, so the assertions stay in lock-step with the single source
of truth:

- `opportunities` gained `source_policy_id` + `renewal_cycle` in **each** tenant
  schema, and `source_lead_id` is now nullable (`is_nullable = 'YES'`);
- the partial unique index enforces one renewal opportunity per
  `(source_policy_id, renewal_cycle, demo_session_id)` where `origin = 'renewal'`:
  a duplicate raises `IntegrityError`, a differing `renewal_cycle` inserts fine;
- the whole migration round-trips: `downgrade 0019` drops the two columns and the
  index from every schema, `upgrade head` restores them.
"""

import os
import uuid
from contextlib import contextmanager

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.tenancy.registry import TENANTS

from tests.conftest import ALEMBIC_CONFIG_PATH, CORE_ROOT, build_postgresql_url

# The revision just below 0020, used as the downgrade target for the round-trip.
ONE_BELOW_RENEWAL_SCHEMA = "0019_one_active_index"

# The two additive columns 0020 lands on opportunities, and the partial index name.
NEW_OPPORTUNITY_COLUMNS = {"source_policy_id", "renewal_cycle"}
RENEWAL_INDEX_NAME = "ux_opportunities_one_renewal_per_policy_cycle"


@pytest.mark.asyncio
async def test_opportunities_gained_renewal_columns_and_nullable_source_lead(
    database_engine,
):
    """Per tenant: the two renewal columns exist and source_lead_id is nullable."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            column_rows = await connection.execute(
                text(
                    "SELECT column_name, is_nullable FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = 'opportunities'"
                ),
                {"schema": tenant.schema_name},
            )
            nullability_by_column = {row[0]: row[1] for row in column_rows}
            column_names = set(nullability_by_column)

            assert NEW_OPPORTUNITY_COLUMNS <= column_names, (
                f"{tenant.schema_name}.opportunities missing columns: "
                f"{NEW_OPPORTUNITY_COLUMNS - column_names}"
            )
            assert nullability_by_column.get("source_lead_id") == "YES", (
                f"{tenant.schema_name}.opportunities.source_lead_id is not nullable"
            )


def build_insert_opportunity_sql(schema: str) -> str:
    """A minimal INSERT for one tenant's opportunities row (all NOT NULL columns).

    `source_lead_id` is omitted on purpose — 0020 relaxed it to nullable, so a
    renewal opportunity is created without a lead. `stage` is omitted too (it has a
    server default). Fully schema-qualified so no search_path is needed.
    """
    return (
        f"INSERT INTO {schema}.opportunities "
        "(id, contact_id, household_id, product_line, origin, "
        "source_policy_id, renewal_cycle, demo_session_id, correlation_id) "
        "VALUES (:id, :contact_id, :household_id, :product_line, :origin, "
        ":source_policy_id, :renewal_cycle, :demo_session_id, :correlation_id)"
    )


def build_renewal_row(source_policy_id, renewal_cycle, demo_session_id) -> dict:
    """A fresh origin='renewal' opportunity row for the given idempotency key."""
    return {
        "id": uuid.uuid4(),
        "contact_id": uuid.uuid4(),
        "household_id": uuid.uuid4(),
        "product_line": "medicare_advantage",
        "origin": "renewal",
        "source_policy_id": source_policy_id,
        "renewal_cycle": renewal_cycle,
        "demo_session_id": demo_session_id,
        "correlation_id": uuid.uuid4(),
    }


@pytest.mark.asyncio
async def test_one_renewal_per_policy_cycle_index_enforces_uniqueness(database_engine):
    """The partial unique index blocks a duplicate renewal for the same key.

    Inserts one origin='renewal' row, then a second with the SAME
    (source_policy_id, renewal_cycle, demo_session_id) — which must raise
    IntegrityError — and a third with a DIFFERING renewal_cycle, which inserts fine.
    Everything runs inside a transaction that is rolled back in `finally`, so the
    shared session-scoped container is left pristine (the duplicate insert is
    isolated in a SAVEPOINT so the outer transaction survives its abort).
    """
    schema = TENANTS[0].schema_name
    insert_sql = text(build_insert_opportunity_sql(schema))

    source_policy_id = uuid.uuid4()
    demo_session_id = uuid.uuid4()

    async with database_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            # First renewal for (policy, '2026', session) — inserts cleanly.
            await connection.execute(
                insert_sql,
                build_renewal_row(source_policy_id, "2026", demo_session_id),
            )

            # Same key again → the partial unique index rejects it. Isolate the
            # failing statement in a SAVEPOINT so the outer transaction survives.
            savepoint = await connection.begin_nested()
            with pytest.raises(IntegrityError):
                await connection.execute(
                    insert_sql,
                    build_renewal_row(source_policy_id, "2026", demo_session_id),
                )
            await savepoint.rollback()

            # Differing renewal_cycle → a distinct key, inserts fine.
            await connection.execute(
                insert_sql,
                build_renewal_row(source_policy_id, "2027", demo_session_id),
            )
        finally:
            # Never commit — leave the shared container exactly as we found it.
            await transaction.rollback()


# --- Migration 0020 round-trip ------------------------------------------------


def build_alembic_config() -> Config:
    """Build an Alembic `Config` pointed at the core package's migration scripts.

    Mirrors the `database_engine` fixture in `conftest.py` (and the same helper in
    `test_lead_conversion_migration.py`): the same `alembic.ini` and `alembic/`
    script location, so the commands run exactly as production does.
    """
    alembic_config = Config(str(ALEMBIC_CONFIG_PATH))
    alembic_config.set_main_option("script_location", str(CORE_ROOT / "alembic"))
    return alembic_config


@contextmanager
def database_url_pointed_at(container):
    """Set `DATABASE_URL` to the container while Alembic runs, then restore it.

    `alembic/env.py` reads `DATABASE_URL`, so each command needs it pointed at the
    test container. The previous value is restored in a `finally` — the same no-leak
    pattern `test_lead_conversion_migration.py` uses.
    """
    database_url = build_postgresql_url(container)
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        yield database_url
    finally:
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url


async def renewal_schema_present_in_every_schema(database_engine) -> bool:
    """True only when both columns and the partial index exist in every schema."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            column_rows = await connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = 'opportunities' "
                    "AND column_name = ANY(:columns)"
                ),
                {
                    "schema": tenant.schema_name,
                    "columns": list(NEW_OPPORTUNITY_COLUMNS),
                },
            )
            present_columns = {row[0] for row in column_rows}
            if NEW_OPPORTUNITY_COLUMNS != present_columns:
                return False

            index_rows = await connection.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname = :schema AND tablename = 'opportunities' "
                    "AND indexname = :index"
                ),
                {"schema": tenant.schema_name, "index": RENEWAL_INDEX_NAME},
            )
            if index_rows.first() is None:
                return False
    return True


@pytest.mark.asyncio
async def test_0020_round_trips(database_engine, postgres_container):
    """`downgrade 0019` drops the renewal schema; `upgrade head` restores it.

    Proves migration 0020 reverses and replays cleanly. The `database_engine`
    fixture has migrated the container to head, so the columns/index start present.
    Downgrading one revision (to `0019`) drops both columns and the partial index
    from every tenant schema; upgrading back to head re-adds them. Head is restored
    in a `finally` so the shared session-scoped container is left exactly as the
    rest of the suite expects (pytest runs serially, so the transient downgrade is
    never observed by another test).
    """
    alembic_config = build_alembic_config()

    with database_url_pointed_at(postgres_container):
        assert await renewal_schema_present_in_every_schema(database_engine) is True

        try:
            command.downgrade(alembic_config, ONE_BELOW_RENEWAL_SCHEMA)
            assert (
                await renewal_schema_present_in_every_schema(database_engine) is False
            )

            command.upgrade(alembic_config, "head")
            assert (
                await renewal_schema_present_in_every_schema(database_engine) is True
            )
        finally:
            # Restore head no matter what so other tests see a migrated container.
            command.upgrade(alembic_config, "head")
