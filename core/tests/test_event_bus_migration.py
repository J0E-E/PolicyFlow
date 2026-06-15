"""Substrate proof for migration 0008 — event-bus stores + roles + grants (Epic 2).

These assert the database state after `upgrade head` against the real Postgres
booted in Docker (the same `database_engine` substrate as `test_audit_migration.py`).
Every expected value is read from `app.tenancy.registry`, so the assertions stay
in lock-step with the single source of truth:

- an `outbox` table and a `processed_events` table exist in **each** tenant schema
  (per-tenant only — there is **no** `platform` twin, unlike audit), each with the
  expected columns;
- `outbox_relay` and `event_consumer` exist (`pg_roles`);
- `outbox_relay` has SELECT + UPDATE but **lacks** INSERT/DELETE on each `outbox`;
  `event_consumer` has INSERT + SELECT but **lacks** UPDATE/DELETE on each
  `processed_events` (`has_table_privilege`);
- each tenant role has INSERT only on its own `outbox` (lacks SELECT/UPDATE/DELETE)
  and SELECT only on its own `processed_events` (lacks INSERT/UPDATE/DELETE);
- `platform_reader` **lacks** SELECT on both new tables in every tenant schema;
- the partial scan index `ix_outbox_unpublished` exists on each `outbox`
  (`pg_indexes`), and the dedup unique `uq_processed_events_consumer_name_event_id`
  and the defensive `uq_outbox_event_id` exist (`pg_constraint`).

Live permission-*denied* execution (running a forbidden statement and catching the
error) is a later epic's job; Epic 2 proves the grant *shape* via
`has_table_privilege`, exactly as `test_audit_migration.py` does.
"""

import pytest
from sqlalchemy import text

from app.tenancy.registry import (
    EVENT_CONSUMER_ROLE,
    OUTBOX_RELAY_ROLE,
    PLATFORM_ROLE,
    TENANTS,
)

EXPECTED_OUTBOX_COLUMNS = {
    "id",
    "event_id",
    "event_type",
    "schema_version",
    "tenant_id",
    "correlation_id",
    "causation_id",
    "actor_user_id",
    "actor_role",
    "demo_session_id",
    "payload",
    "occurred_at",
    "published_at",
}

EXPECTED_PROCESSED_EVENTS_COLUMNS = {
    "id",
    "consumer_name",
    "event_id",
    "tenant_id",
    "event_type",
    "correlation_id",
    "processed_at",
}

OUTBOX_UNPUBLISHED_INDEX_NAME = "ix_outbox_unpublished"
OUTBOX_EVENT_ID_UNIQUE_NAME = "uq_outbox_event_id"
PROCESSED_EVENTS_DEDUP_UNIQUE_NAME = "uq_processed_events_consumer_name_event_id"


async def get_column_names(connection, schema_name, table_name):
    """Return the set of column names for one schema-qualified table."""
    column_rows = await connection.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :table"
        ),
        {"schema": schema_name, "table": table_name},
    )
    return {row[0] for row in column_rows}


async def has_privilege(connection, role, qualified_table, privilege):
    """Return whether `role` holds `privilege` on `qualified_table`."""
    privilege_row = await connection.execute(
        text("SELECT has_table_privilege(:role, :table, :privilege)"),
        {"role": role, "table": qualified_table, "privilege": privilege},
    )
    return privilege_row.scalar_one()


@pytest.mark.asyncio
async def test_event_bus_tables_exist_in_each_tenant_schema(database_engine):
    """`upgrade head` created outbox + processed_events in every tenant schema."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            outbox_columns = await get_column_names(
                connection, tenant.schema_name, "outbox"
            )
            assert EXPECTED_OUTBOX_COLUMNS <= outbox_columns

            processed_events_columns = await get_column_names(
                connection, tenant.schema_name, "processed_events"
            )
            assert EXPECTED_PROCESSED_EVENTS_COLUMNS <= processed_events_columns


@pytest.mark.asyncio
async def test_event_bus_tables_have_no_platform_twin(database_engine):
    """outbox / processed_events are per-tenant only — neither exists in platform."""
    async with database_engine.connect() as connection:
        for table_name in ("outbox", "processed_events"):
            platform_columns = await get_column_names(
                connection, "platform", table_name
            )
            assert platform_columns == set()


@pytest.mark.asyncio
async def test_event_bus_roles_exist(database_engine):
    """The dedicated outbox_relay and event_consumer roles exist as cluster roles."""
    async with database_engine.connect() as connection:
        role_rows = await connection.execute(text("SELECT rolname FROM pg_roles"))
        role_names = {row[0] for row in role_rows}

    assert OUTBOX_RELAY_ROLE in role_names
    assert EVENT_CONSUMER_ROLE in role_names


@pytest.mark.asyncio
async def test_outbox_relay_can_select_and_update_but_not_insert_or_delete(
    database_engine,
):
    """outbox_relay has SELECT + UPDATE but lacks INSERT/DELETE on each outbox."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            outbox_table = f"{tenant.schema_name}.outbox"

            for granted_privilege in ("SELECT", "UPDATE"):
                assert (
                    await has_privilege(
                        connection,
                        OUTBOX_RELAY_ROLE,
                        outbox_table,
                        granted_privilege,
                    )
                    is True
                )

            for forbidden_privilege in ("INSERT", "DELETE"):
                assert (
                    await has_privilege(
                        connection,
                        OUTBOX_RELAY_ROLE,
                        outbox_table,
                        forbidden_privilege,
                    )
                    is False
                )


@pytest.mark.asyncio
async def test_event_consumer_can_insert_and_select_but_not_update_or_delete(
    database_engine,
):
    """event_consumer has INSERT + SELECT but lacks UPDATE/DELETE on processed_events."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            processed_events_table = f"{tenant.schema_name}.processed_events"

            for granted_privilege in ("INSERT", "SELECT"):
                assert (
                    await has_privilege(
                        connection,
                        EVENT_CONSUMER_ROLE,
                        processed_events_table,
                        granted_privilege,
                    )
                    is True
                )

            for forbidden_privilege in ("UPDATE", "DELETE"):
                assert (
                    await has_privilege(
                        connection,
                        EVENT_CONSUMER_ROLE,
                        processed_events_table,
                        forbidden_privilege,
                    )
                    is False
                )


@pytest.mark.asyncio
async def test_tenant_role_has_insert_only_on_its_own_outbox(database_engine):
    """A tenant role can INSERT its own outbox but cannot SELECT/UPDATE/DELETE it."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            outbox_table = f"{tenant.schema_name}.outbox"

            assert (
                await has_privilege(
                    connection, tenant.db_role, outbox_table, "INSERT"
                )
                is True
            )

            for forbidden_privilege in ("SELECT", "UPDATE", "DELETE"):
                assert (
                    await has_privilege(
                        connection,
                        tenant.db_role,
                        outbox_table,
                        forbidden_privilege,
                    )
                    is False
                )


@pytest.mark.asyncio
async def test_tenant_role_has_select_only_on_its_own_processed_events(
    database_engine,
):
    """A tenant role can SELECT its own processed_events but cannot write it."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            processed_events_table = f"{tenant.schema_name}.processed_events"

            assert (
                await has_privilege(
                    connection, tenant.db_role, processed_events_table, "SELECT"
                )
                is True
            )

            for forbidden_privilege in ("INSERT", "UPDATE", "DELETE"):
                assert (
                    await has_privilege(
                        connection,
                        tenant.db_role,
                        processed_events_table,
                        forbidden_privilege,
                    )
                    is False
                )


@pytest.mark.asyncio
async def test_platform_reader_cannot_read_event_bus_tables(database_engine):
    """platform_reader lacks SELECT on every tenant's outbox and processed_events."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            for table_name in ("outbox", "processed_events"):
                qualified_table = f"{tenant.schema_name}.{table_name}"
                assert (
                    await has_privilege(
                        connection, PLATFORM_ROLE, qualified_table, "SELECT"
                    )
                    is False
                )


@pytest.mark.asyncio
async def test_outbox_unpublished_index_exists_in_every_schema(database_engine):
    """The partial relay-scan index ix_outbox_unpublished exists on each outbox."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            index_rows = await connection.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname = :schema AND tablename = 'outbox'"
                ),
                {"schema": tenant.schema_name},
            )
            index_names = {row[0] for row in index_rows}
            assert OUTBOX_UNPUBLISHED_INDEX_NAME in index_names


@pytest.mark.asyncio
async def test_unique_constraints_exist_in_every_schema(database_engine):
    """The defensive outbox unique and the processed_events dedup unique exist."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            constraint_rows = await connection.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE connamespace = (:schema)::regnamespace "
                    "AND contype = 'u'"
                ),
                {"schema": tenant.schema_name},
            )
            constraint_names = {row[0] for row in constraint_rows}
            assert OUTBOX_EVENT_ID_UNIQUE_NAME in constraint_names
            assert PROCESSED_EVENTS_DEDUP_UNIQUE_NAME in constraint_names
