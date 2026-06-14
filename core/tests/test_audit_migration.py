"""Substrate proof for migration 0007 — audit stores + audit_writer + grants (Epic 2).

These assert the database state after `upgrade head` against the real Postgres
booted in Docker (the same `database_engine` substrate as `test_pii_demo.py`).
Every expected value is read from `app.tenancy.registry`, so the assertions stay
in lock-step with the single source of truth:

- an `audit_records` table exists in **each** tenant schema and
  `platform.audit_records` exists, each with the expected columns;
- `audit_writer` exists (`pg_roles`) and has INSERT + SELECT but **lacks**
  UPDATE/DELETE on both stores (`has_table_privilege`);
- each tenant role has SELECT only on its own `audit_records` (has SELECT; lacks
  INSERT/UPDATE/DELETE), and `platform_reader` **lacks** SELECT on any tenant
  `audit_records`;
- `ix_audit_records_occurred_at` exists in every tenant schema **and** in
  `platform` (`pg_indexes`).

Live permission-*denied* execution (running a forbidden UPDATE and catching the
error) is Epic 5's job; Epic 2 proves the grant *shape* via `has_table_privilege`,
exactly as `test_pii_demo.py` does.
"""

import pytest
from sqlalchemy import text

from app.tenancy.registry import AUDIT_WRITER_ROLE, PLATFORM_ROLE, TENANTS

EXPECTED_COLUMNS = {
    "id",
    "occurred_at",
    "tenant_id",
    "actor_user_id",
    "actor_role",
    "event_type",
    "entity_type",
    "entity_id",
    "field_names",
    "outcome",
}

OCCURRED_AT_INDEX_NAME = "ix_audit_records_occurred_at"


@pytest.mark.asyncio
async def test_audit_records_table_exists_in_each_schema(database_engine):
    """`upgrade head` created an audit_records table in every tenant schema and platform."""
    expected_schemas = [tenant.schema_name for tenant in TENANTS] + ["platform"]

    async with database_engine.connect() as connection:
        for schema_name in expected_schemas:
            column_rows = await connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = :schema "
                    "AND table_name = 'audit_records'"
                ),
                {"schema": schema_name},
            )
            column_names = {row[0] for row in column_rows}
            assert EXPECTED_COLUMNS <= column_names


@pytest.mark.asyncio
async def test_audit_writer_role_exists(database_engine):
    """The dedicated audit_writer role exists as a cluster role."""
    async with database_engine.connect() as connection:
        role_rows = await connection.execute(
            text("SELECT rolname FROM pg_roles")
        )
        role_names = {row[0] for row in role_rows}

    assert AUDIT_WRITER_ROLE in role_names


@pytest.mark.asyncio
async def test_audit_writer_can_insert_and_select_but_not_modify(database_engine):
    """audit_writer has INSERT + SELECT but lacks UPDATE/DELETE on both stores."""
    qualified_tables = [
        f"{tenant.schema_name}.audit_records" for tenant in TENANTS
    ] + ["platform.audit_records"]

    async with database_engine.connect() as connection:
        for qualified_table in qualified_tables:
            for granted_privilege in ("INSERT", "SELECT"):
                granted_row = await connection.execute(
                    text(
                        "SELECT has_table_privilege(:role, :table, :privilege)"
                    ),
                    {
                        "role": AUDIT_WRITER_ROLE,
                        "table": qualified_table,
                        "privilege": granted_privilege,
                    },
                )
                assert granted_row.scalar_one() is True

            for forbidden_privilege in ("UPDATE", "DELETE"):
                forbidden_row = await connection.execute(
                    text(
                        "SELECT has_table_privilege(:role, :table, :privilege)"
                    ),
                    {
                        "role": AUDIT_WRITER_ROLE,
                        "table": qualified_table,
                        "privilege": forbidden_privilege,
                    },
                )
                assert forbidden_row.scalar_one() is False


@pytest.mark.asyncio
async def test_tenant_role_has_select_only_on_its_own_audit(database_engine):
    """A tenant role can SELECT its own audit_records but cannot INSERT/UPDATE/DELETE."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            qualified_table = f"{tenant.schema_name}.audit_records"

            select_row = await connection.execute(
                text("SELECT has_table_privilege(:role, :table, 'SELECT')"),
                {"role": tenant.db_role, "table": qualified_table},
            )
            assert select_row.scalar_one() is True

            for forbidden_privilege in ("INSERT", "UPDATE", "DELETE"):
                forbidden_row = await connection.execute(
                    text(
                        "SELECT has_table_privilege(:role, :table, :privilege)"
                    ),
                    {
                        "role": tenant.db_role,
                        "table": qualified_table,
                        "privilege": forbidden_privilege,
                    },
                )
                assert forbidden_row.scalar_one() is False


@pytest.mark.asyncio
async def test_platform_reader_cannot_read_any_tenant_audit(database_engine):
    """platform_reader lacks SELECT on every tenant's audit_records."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            qualified_table = f"{tenant.schema_name}.audit_records"
            select_row = await connection.execute(
                text("SELECT has_table_privilege(:role, :table, 'SELECT')"),
                {"role": PLATFORM_ROLE, "table": qualified_table},
            )
            assert select_row.scalar_one() is False


@pytest.mark.asyncio
async def test_occurred_at_index_exists_in_every_schema_and_platform(database_engine):
    """ix_audit_records_occurred_at exists on audit_records in every tenant schema and platform."""
    expected_schemas = [tenant.schema_name for tenant in TENANTS] + ["platform"]

    async with database_engine.connect() as connection:
        for schema_name in expected_schemas:
            index_rows = await connection.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname = :schema "
                    "AND tablename = 'audit_records'"
                ),
                {"schema": schema_name},
            )
            index_names = {row[0] for row in index_rows}
            assert OCCURRED_AT_INDEX_NAME in index_names
