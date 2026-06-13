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


async def _read_settings_rows(connection, schema_name: str):
    """Return every tenant_settings row in this tenant's schema."""
    settings_rows = await connection.execute(
        text(
            f"SELECT tenant_id, brand_primary_color, brand_logo_url, "
            f"welcome_message FROM {schema_name}.tenant_settings"
        )
    )
    return settings_rows.all()


@pytest.mark.asyncio
async def test_seed_writes_one_distinct_settings_row_per_tenant(database_engine):
    """After seeding, each tenant schema holds exactly one settings row.

    Each row carries that tenant's distinct brand colour, logo URL, and welcome
    message, keyed to its `platform.tenants` id.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    async with session_factory() as session:
        await seed(session)

    seen_welcome_messages = set()
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            tenant_id_row = await connection.execute(
                text("SELECT id FROM platform.tenants WHERE slug = :slug"),
                {"slug": tenant.slug},
            )
            expected_tenant_id = tenant_id_row.scalar_one()

            settings_rows = await _read_settings_rows(
                connection, tenant.schema_name
            )
            assert len(settings_rows) == 1
            (
                tenant_id,
                brand_primary_color,
                brand_logo_url,
                welcome_message,
            ) = settings_rows[0]

            assert tenant_id == expected_tenant_id
            assert brand_primary_color
            assert brand_logo_url == (
                f"https://assets.policyflow.example/"
                f"{tenant.schema_name}/logo.svg"
            )
            assert welcome_message
            seen_welcome_messages.add(welcome_message)

    # The welcome messages are distinct per tenant.
    assert len(seen_welcome_messages) == len(TENANTS)


@pytest.mark.asyncio
async def test_second_seed_run_leaves_settings_rows_unchanged(database_engine):
    """A second seed run is idempotent: no duplicate or changed settings rows."""
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    async with session_factory() as session:
        await seed(session)
    async with database_engine.connect() as connection:
        rows_after_first_seed = {
            tenant.slug: await _read_settings_rows(connection, tenant.schema_name)
            for tenant in TENANTS
        }

    async with session_factory() as session:
        await seed(session)
    async with database_engine.connect() as connection:
        rows_after_second_seed = {
            tenant.slug: await _read_settings_rows(connection, tenant.schema_name)
            for tenant in TENANTS
        }

    for tenant in TENANTS:
        assert len(rows_after_second_seed[tenant.slug]) == 1
        assert rows_after_second_seed[tenant.slug] == rows_after_first_seed[
            tenant.slug
        ]
