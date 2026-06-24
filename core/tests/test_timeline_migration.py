"""Substrate proof for migration 0014 — outbox SELECT grant + result_summary (P1.9 Epic 1).

These assert the database state after `upgrade head` against the real Postgres
booted in Docker (the same `database_engine` substrate as `test_event_bus_migration.py`
/ `test_demo_purge_migration.py`). Every expected value is read from
`app.tenancy.registry`, so the assertions stay in lock-step with the single source
of truth:

- each tenant's `processed_events` now carries the nullable `result_summary` column
  (`information_schema.columns`);
- each tenant role now holds `SELECT` on its own `outbox` (`0008` had revoked it),
  but still **lacks** `UPDATE`/`DELETE` — the timeline only reads (`has_table_privilege`);
- a `SET ROLE <tenant db_role>` session can actually `SELECT` from its own `outbox`
  end-to-end (the grant works at execution time, not just on paper).

Mirrors `test_demo_purge_migration.py`'s role-flip capability check: the on-paper
`has_table_privilege` assertions plus one live `SET ROLE` execution proving the
grant shape holds against real Postgres.
"""

import pytest
from sqlalchemy import text

from app.tenancy.registry import TENANTS


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
async def test_processed_events_has_result_summary_column(database_engine):
    """`upgrade head` added the nullable result_summary column in every schema."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            processed_events_columns = await get_column_names(
                connection, tenant.schema_name, "processed_events"
            )
            assert "result_summary" in processed_events_columns


@pytest.mark.asyncio
async def test_tenant_role_now_has_select_on_its_own_outbox(database_engine):
    """A tenant role can now SELECT its own outbox (0008 revoked, 0014 re-granted)."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            outbox_table = f"{tenant.schema_name}.outbox"

            assert (
                await has_privilege(
                    connection, tenant.db_role, outbox_table, "SELECT"
                )
                is True
            )


@pytest.mark.asyncio
async def test_tenant_role_still_cannot_write_its_own_outbox(database_engine):
    """The re-grant adds only SELECT — INSERT stays (the write), UPDATE/DELETE stay revoked."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            outbox_table = f"{tenant.schema_name}.outbox"

            # INSERT remains (the transactional write 0008 kept).
            assert (
                await has_privilege(
                    connection, tenant.db_role, outbox_table, "INSERT"
                )
                is True
            )
            # UPDATE/DELETE stay revoked — the timeline only reads, the relay owns
            # the publish stamp.
            for forbidden_privilege in ("UPDATE", "DELETE"):
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
async def test_tenant_role_can_select_outbox_under_set_role(database_engine):
    """Under `SET ROLE <tenant db_role>`, a SELECT on its own outbox succeeds.

    Proves the grant shape end-to-end against real Postgres: the role flip plus a
    live SELECT (the timeline endpoint's read) must not raise insufficient-privilege.
    """
    tenant = TENANTS[0]
    schema = tenant.schema_name

    async with database_engine.connect() as connection:
        await connection.execute(text(f"SET ROLE {tenant.db_role}"))
        await connection.execute(text(f"SET search_path TO {schema}"))

        # The timeline endpoint's read shape: SELECT from the role's own outbox.
        result = await connection.execute(
            text(f"SELECT count(*) FROM {schema}.outbox")
        )
        assert result.scalar_one() >= 0

        await connection.execute(text("RESET ROLE"))
        await connection.rollback()
