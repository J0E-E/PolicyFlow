"""Substrate proof for migration 0006 — pii_demo table + grants + indexes (Epic 8).

These assert the database state after `upgrade head` against the real Postgres
booted in Docker (the same `database_engine` substrate as `test_tenant_settings.py`).
Every expected value is read from `app.tenancy.registry`, so the assertions stay
in lock-step with the single source of truth:

- a `pii_demo` table exists in **each** tenant schema, with the expected columns;
- each tenant role has full CRUD on its own schema's copy
  (`has_table_privilege`);
- `platform_reader` has SELECT on every tenant's copy;
- each blind-index index (`ix_pii_demo_email_blind_index` /
  `ix_pii_demo_phone_blind_index`) exists in every tenant schema (`pg_indexes`).
"""

import pytest
from sqlalchemy import text

from app.tenancy.registry import PLATFORM_ROLE, TENANTS

EXPECTED_COLUMNS = {
    "id",
    "display_name",
    "email_encrypted",
    "email_blind_index",
    "phone_encrypted",
    "phone_blind_index",
    "date_of_birth_encrypted",
    "age_band",
    "mock_medicare_id_encrypted",
    "created_at",
}

EXPECTED_INDEX_NAMES = {
    "ix_pii_demo_email_blind_index",
    "ix_pii_demo_phone_blind_index",
}


@pytest.mark.asyncio
async def test_pii_demo_table_exists_in_each_schema(database_engine):
    """`upgrade head` created a pii_demo table in every tenant schema."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            column_rows = await connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = :schema "
                    "AND table_name = 'pii_demo'"
                ),
                {"schema": tenant.schema_name},
            )
            column_names = {row[0] for row in column_rows}
            assert EXPECTED_COLUMNS <= column_names


@pytest.mark.asyncio
async def test_each_tenant_role_has_crud_on_its_own_pii_demo(database_engine):
    """A tenant role can SELECT/INSERT/UPDATE/DELETE its own pii_demo table."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            qualified_table = f"{tenant.schema_name}.pii_demo"
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                privilege_row = await connection.execute(
                    text(
                        "SELECT has_table_privilege(:role, :table, :privilege)"
                    ),
                    {
                        "role": tenant.db_role,
                        "table": qualified_table,
                        "privilege": privilege,
                    },
                )
                assert privilege_row.scalar_one() is True


@pytest.mark.asyncio
async def test_platform_reader_has_select_on_every_pii_demo(database_engine):
    """The platform read-role has SELECT on every tenant's pii_demo table."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            qualified_table = f"{tenant.schema_name}.pii_demo"
            select_row = await connection.execute(
                text("SELECT has_table_privilege(:role, :table, 'SELECT')"),
                {"role": PLATFORM_ROLE, "table": qualified_table},
            )
            assert select_row.scalar_one() is True


@pytest.mark.asyncio
async def test_blind_index_indexes_exist_in_each_schema(database_engine):
    """Both blind-index indexes exist on the pii_demo table in every schema."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            index_rows = await connection.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname = :schema "
                    "AND tablename = 'pii_demo'"
                ),
                {"schema": tenant.schema_name},
            )
            index_names = {row[0] for row in index_rows}
            assert EXPECTED_INDEX_NAMES <= index_names
