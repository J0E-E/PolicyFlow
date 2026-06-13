"""Substrate proof for migration 0003 — tenant schemas, roles, and grants (Epic 2).

These assert the database backbone after `upgrade head` against the real Postgres
booted in Docker (the same `database_engine` substrate as `test_substrate.py`).
Every expected value is read from `app.tenancy.registry`, so the assertions stay
in lock-step with the single source of truth:

- both tenant schemas exist (`pg_namespace`);
- all three roles exist (`pg_roles`), and each tenant role reaches USAGE on its
  own schema but not the other tenant's (`has_schema_privilege`);
- `platform.tenants` now has the nullable `schema_name` / `db_role` columns;
- the connected login role is `NOINHERIT` and a member of every tenant role plus
  the platform read-role (`pg_roles.rolinherit`, `pg_auth_members`).
"""

import pytest
from sqlalchemy import text

from app.tenancy.registry import PLATFORM_ROLE, TENANTS


@pytest.mark.asyncio
async def test_tenant_schemas_exist(database_engine):
    """`upgrade head` created a schema for every tenant in the registry."""
    expected_schemas = {tenant.schema_name for tenant in TENANTS}

    async with database_engine.connect() as connection:
        schema_rows = await connection.execute(
            text("SELECT nspname FROM pg_namespace")
        )
        schema_names = {row[0] for row in schema_rows}

    assert expected_schemas <= schema_names


@pytest.mark.asyncio
async def test_tenant_and_platform_roles_exist(database_engine):
    """Every tenant role and the platform read-role exist as cluster roles."""
    expected_roles = {tenant.db_role for tenant in TENANTS} | {PLATFORM_ROLE}

    async with database_engine.connect() as connection:
        role_rows = await connection.execute(
            text("SELECT rolname FROM pg_roles")
        )
        role_names = {row[0] for row in role_rows}

    assert expected_roles <= role_names


@pytest.mark.asyncio
async def test_each_tenant_role_reaches_only_its_own_schema(database_engine):
    """A tenant role has USAGE on its own schema and not on the other tenant's."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            other_tenants = [other for other in TENANTS if other is not tenant]

            own_usage_row = await connection.execute(
                text(
                    "SELECT has_schema_privilege(:role, :schema, 'USAGE')"
                ),
                {"role": tenant.db_role, "schema": tenant.schema_name},
            )
            assert own_usage_row.scalar_one() is True

            for other in other_tenants:
                other_usage_row = await connection.execute(
                    text(
                        "SELECT has_schema_privilege(:role, :schema, 'USAGE')"
                    ),
                    {"role": tenant.db_role, "schema": other.schema_name},
                )
                assert other_usage_row.scalar_one() is False


@pytest.mark.asyncio
async def test_platform_tenants_has_nullable_schema_and_role_columns(database_engine):
    """`platform.tenants` gained the nullable `schema_name` / `db_role` columns."""
    async with database_engine.connect() as connection:
        column_rows = await connection.execute(
            text(
                "SELECT column_name, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_schema = 'platform' AND table_name = 'tenants'"
            )
        )
        nullable_by_column = {row[0]: row[1] for row in column_rows}

    assert nullable_by_column.get("schema_name") == "YES"
    assert nullable_by_column.get("db_role") == "YES"


@pytest.mark.asyncio
async def test_login_role_is_noinherit_member_of_every_role(database_engine):
    """The connected login role is NOINHERIT and a member of all tenant roles."""
    expected_member_roles = {tenant.db_role for tenant in TENANTS} | {
        PLATFORM_ROLE
    }

    async with database_engine.connect() as connection:
        inherit_row = await connection.execute(
            text("SELECT rolinherit FROM pg_roles WHERE rolname = CURRENT_USER")
        )
        assert inherit_row.scalar_one() is False

        membership_rows = await connection.execute(
            text(
                "SELECT parent.rolname "
                "FROM pg_auth_members member "
                "JOIN pg_roles parent ON parent.oid = member.roleid "
                "JOIN pg_roles child ON child.oid = member.member "
                "WHERE child.rolname = CURRENT_USER"
            )
        )
        member_of_roles = {row[0] for row in membership_rows}

    assert expected_member_roles <= member_of_roles
