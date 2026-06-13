"""Substrate proof for Epic 3 — the seed populates tenant schema/role columns.

These assert that, after `upgrade head` against the real Postgres booted in
Docker (the same `database_engine` substrate as `test_tenant_schemas.py`),
running `seed()` fills each registry tenant's `platform.tenants` row with the
registry value for that row's slug, and that a second `seed()` run leaves those
columns unchanged (idempotency on the real database).

The assertions are keyed on the registry's slugs (the single source of truth),
so they ignore any orphan tenant rows other tests insert into the shared
session-scoped container — matching Epic 3's decision to leave non-registry rows
untouched.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.seed import seed
from app.tenancy.registry import TENANTS


async def _read_columns_for_slug(connection, slug: str) -> tuple[str, str]:
    """Return the (schema_name, db_role) for the one tenant row with this slug."""
    column_row = await connection.execute(
        text(
            "SELECT schema_name, db_role FROM platform.tenants WHERE slug = :slug"
        ),
        {"slug": slug},
    )
    return column_row.one()


@pytest.mark.asyncio
async def test_seed_fills_tenant_columns_from_registry(database_engine):
    """After seeding, each registry tenant's row carries its schema_name / db_role."""
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    async with session_factory() as session:
        await seed(session)

    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            schema_name, db_role = await _read_columns_for_slug(
                connection, tenant.slug
            )
            assert schema_name == tenant.schema_name
            assert db_role == tenant.db_role


@pytest.mark.asyncio
async def test_second_seed_run_leaves_tenant_columns_unchanged(database_engine):
    """A second seed run is idempotent: the columns keep their registry values."""
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    async with session_factory() as session:
        await seed(session)
    async with database_engine.connect() as connection:
        columns_after_first_seed = {
            tenant.slug: await _read_columns_for_slug(connection, tenant.slug)
            for tenant in TENANTS
        }

    async with session_factory() as session:
        await seed(session)
    async with database_engine.connect() as connection:
        columns_after_second_seed = {
            tenant.slug: await _read_columns_for_slug(connection, tenant.slug)
            for tenant in TENANTS
        }

    assert columns_after_second_seed == columns_after_first_seed
    for tenant in TENANTS:
        assert columns_after_second_seed[tenant.slug] == (
            tenant.schema_name,
            tenant.db_role,
        )
