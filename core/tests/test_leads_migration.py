"""Substrate proof for migration 0009 — leads table + grants + indexes (Epic 3).

These assert the database state after `upgrade head` against the real Postgres
booted in Docker (the same `database_engine` substrate as `test_pii_demo.py`).
Every expected value is read from `app.tenancy.registry`, so the assertions stay
in lock-step with the single source of truth:

- a `leads` table exists in **each** tenant schema, with the full column set;
- each tenant role has full CRUD on its own schema's copy
  (`has_table_privilege`);
- `platform_reader` has SELECT on every tenant's copy;
- each blind-index index (`ix_leads_email_blind_index` /
  `ix_leads_phone_blind_index`) exists in every tenant schema (`pg_indexes`).
"""

import os
from contextlib import contextmanager

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.tenancy.registry import PLATFORM_ROLE, TENANTS

from tests.conftest import ALEMBIC_CONFIG_PATH, CORE_ROOT, build_postgresql_url

EXPECTED_COLUMNS = {
    "id",
    "first_name",
    "last_name",
    "email_encrypted",
    "email_blind_index",
    "phone_encrypted",
    "phone_blind_index",
    "date_of_birth_encrypted",
    "age_band",
    "zip_code",
    "street_address_encrypted",
    "product_lines_of_interest",
    "preferred_contact_method",
    "notes",
    "rejection_reason",
    "lead_source",
    "status",
    "owner_user_id",
    "owner_username",
    "duplicate_of_lead_id",
    "duplicate_resolution",
    "correlation_id",
    "demo_session_id",
    "created_at",
    "updated_at",
}

EXPECTED_INDEX_NAMES = {
    "ix_leads_email_blind_index",
    "ix_leads_phone_blind_index",
}


@pytest.mark.asyncio
async def test_leads_table_exists_in_each_schema(database_engine):
    """`upgrade head` created a leads table in every tenant schema."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            column_rows = await connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = :schema "
                    "AND table_name = 'leads'"
                ),
                {"schema": tenant.schema_name},
            )
            column_names = {row[0] for row in column_rows}
            assert EXPECTED_COLUMNS <= column_names


@pytest.mark.asyncio
async def test_each_tenant_role_has_crud_on_its_own_leads(database_engine):
    """A tenant role can SELECT/INSERT/UPDATE/DELETE its own leads table."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            qualified_table = f"{tenant.schema_name}.leads"
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
async def test_platform_reader_has_select_on_every_leads(database_engine):
    """The platform read-role has SELECT on every tenant's leads table."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            qualified_table = f"{tenant.schema_name}.leads"
            select_row = await connection.execute(
                text("SELECT has_table_privilege(:role, :table, 'SELECT')"),
                {"role": PLATFORM_ROLE, "table": qualified_table},
            )
            assert select_row.scalar_one() is True


@pytest.mark.asyncio
async def test_blind_index_indexes_exist_in_each_schema(database_engine):
    """Both blind-index indexes exist on the leads table in every schema."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            index_rows = await connection.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname = :schema "
                    "AND tablename = 'leads'"
                ),
                {"schema": tenant.schema_name},
            )
            index_names = {row[0] for row in index_rows}
            assert EXPECTED_INDEX_NAMES <= index_names


# --- Migration 0010 round-trip — rejection_reason column (Epic 13) ------------

# The revision just below 0010, used as the downgrade target for the round-trip.
ONE_BELOW_REJECTION_REASON = "0009_leads"


def build_alembic_config() -> Config:
    """Build an Alembic `Config` pointed at the core package's migration scripts.

    Mirrors the `database_engine` fixture in `conftest.py` (and the same helper in
    `test_migration_hygiene.py`): the same `alembic.ini` and `alembic/` script
    location, so the commands run exactly as production does.
    """
    alembic_config = Config(str(ALEMBIC_CONFIG_PATH))
    alembic_config.set_main_option("script_location", str(CORE_ROOT / "alembic"))
    return alembic_config


@contextmanager
def database_url_pointed_at(container):
    """Set `DATABASE_URL` to the container while Alembic runs, then restore it.

    `alembic/env.py` reads `DATABASE_URL`, so each command needs it pointed at the
    test container. The previous value is restored in a `finally` — the same no-leak
    pattern `test_migration_hygiene.py` uses.
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


async def rejection_reason_exists_in_every_schema(database_engine) -> bool:
    """True only when `leads.rejection_reason` exists in every tenant schema."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            column_row = await connection.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = :schema "
                    "AND table_name = 'leads' "
                    "AND column_name = 'rejection_reason'"
                ),
                {"schema": tenant.schema_name},
            )
            if column_row.scalar_one_or_none() is None:
                return False
    return True


@pytest.mark.asyncio
async def test_0010_rejection_reason_round_trips(database_engine, postgres_container):
    """`downgrade 0009` drops `rejection_reason`; `upgrade head` restores it.

    Proves migration 0010 reverses and replays cleanly. The `database_engine` fixture
    has migrated the container to head, so the column starts present. Downgrading one
    revision (to `0009`) drops it from every tenant schema; upgrading back to head
    re-adds it. Head is restored in a `finally` so the shared session-scoped container
    is left exactly as the rest of the suite expects (pytest runs serially, so the
    transient downgrade is never observed by another test).
    """
    alembic_config = build_alembic_config()

    with database_url_pointed_at(postgres_container):
        assert await rejection_reason_exists_in_every_schema(database_engine) is True

        try:
            command.downgrade(alembic_config, ONE_BELOW_REJECTION_REASON)
            assert (
                await rejection_reason_exists_in_every_schema(database_engine) is False
            )

            command.upgrade(alembic_config, "head")
            assert (
                await rejection_reason_exists_in_every_schema(database_engine) is True
            )
        finally:
            # Restore head no matter what so other tests see a migrated container.
            command.upgrade(alembic_config, "head")
