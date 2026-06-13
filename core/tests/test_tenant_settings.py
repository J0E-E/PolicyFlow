"""Substrate proof for migration 0004 — tenant_settings table + grants (Epic 4).

These assert the database state after `upgrade head` against the real Postgres
booted in Docker (the same `database_engine` substrate as `test_tenant_schemas.py`).
Every expected value is read from `app.tenancy.registry`, so the assertions stay
in lock-step with the single source of truth:

- a `tenant_settings` table exists in **each** tenant schema, with the expected
  columns;
- each tenant role has full CRUD on its own schema's copy
  (`has_table_privilege`);
- `platform_reader` has SELECT on every tenant's copy.
"""

import pytest
from sqlalchemy import text

from app.tenancy.registry import PLATFORM_ROLE, TENANTS

EXPECTED_COLUMNS = {
    "tenant_id",
    "brand_primary_color",
    "brand_logo_url",
    "welcome_message",
    "created_at",
}


@pytest.mark.asyncio
async def test_tenant_settings_table_exists_in_each_schema(database_engine):
    """`upgrade head` created a tenant_settings table in every tenant schema."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            column_rows = await connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = :schema "
                    "AND table_name = 'tenant_settings'"
                ),
                {"schema": tenant.schema_name},
            )
            column_names = {row[0] for row in column_rows}
            assert EXPECTED_COLUMNS <= column_names


@pytest.mark.asyncio
async def test_each_tenant_role_has_crud_on_its_own_settings(database_engine):
    """A tenant role can SELECT/INSERT/UPDATE/DELETE its own settings table."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            qualified_table = f"{tenant.schema_name}.tenant_settings"
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
async def test_platform_reader_has_select_on_every_settings(database_engine):
    """The platform read-role has SELECT on every tenant's settings table."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            qualified_table = f"{tenant.schema_name}.tenant_settings"
            select_row = await connection.execute(
                text("SELECT has_table_privilege(:role, :table, 'SELECT')"),
                {"role": PLATFORM_ROLE, "table": qualified_table},
            )
            assert select_row.scalar_one() is True
