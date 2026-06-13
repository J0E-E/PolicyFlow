"""Substrate proof for migration 0005 — tenant_data_keys table + grants (Epic 3).

These assert the database state after `upgrade head` against the real Postgres
booted in Docker (the same `database_engine` substrate as `test_tenant_settings.py`).
The wrapped-key store lives in the shared `platform` schema and must be readable
**only** by the default login role, so:

- a `tenant_data_keys` table exists in the `platform` schema with the expected
  columns;
- the default login role (`current_user`) **can** SELECT;
- `platform_reader` (the `PLATFORM_ROLE` constant) **cannot** SELECT;
- **no** tenant role (`TENANTS`) can SELECT.

The negative grants are the security crux: even a fully tenant-scoped request can
never read key material, so the tenant-isolation story holds.
"""

import pytest
from sqlalchemy import text

from app.tenancy.registry import PLATFORM_ROLE, TENANTS

EXPECTED_COLUMNS = {
    "tenant_id",
    "wrapped_root_key",
    "created_at",
}


@pytest.mark.asyncio
async def test_tenant_data_keys_table_exists_in_platform_schema(database_engine):
    """`upgrade head` created a tenant_data_keys table in the platform schema."""
    async with database_engine.connect() as connection:
        column_rows = await connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'platform' "
                "AND table_name = 'tenant_data_keys'"
            )
        )
        column_names = {row[0] for row in column_rows}
        assert EXPECTED_COLUMNS <= column_names


@pytest.mark.asyncio
async def test_login_role_can_select_tenant_data_keys(database_engine):
    """The default login role (the table owner) can SELECT key material."""
    async with database_engine.connect() as connection:
        select_row = await connection.execute(
            text(
                "SELECT has_table_privilege("
                "current_user, 'platform.tenant_data_keys', 'SELECT')"
            )
        )
        assert select_row.scalar_one() is True


@pytest.mark.asyncio
async def test_platform_reader_cannot_select_tenant_data_keys(database_engine):
    """`platform_reader` must never see key material — no SELECT granted."""
    async with database_engine.connect() as connection:
        select_row = await connection.execute(
            text("SELECT has_table_privilege(:role, :table, 'SELECT')"),
            {"role": PLATFORM_ROLE, "table": "platform.tenant_data_keys"},
        )
        assert select_row.scalar_one() is False


@pytest.mark.asyncio
async def test_no_tenant_role_can_select_tenant_data_keys(database_engine):
    """No tenant role may read key material — no SELECT granted to any tenant."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            select_row = await connection.execute(
                text("SELECT has_table_privilege(:role, :table, 'SELECT')"),
                {
                    "role": tenant.db_role,
                    "table": "platform.tenant_data_keys",
                },
            )
            assert select_row.scalar_one() is False
