"""Substrate proof for migration 0015 — lead-conversion tables + grants + leads ALTER.

These assert the database state after `upgrade head` against the real Postgres
booted in Docker (the same `database_engine` substrate as
`test_leads_migration.py` / `test_demo_purge_migration.py`). Every expected value
is read from `app.tenancy.registry`, so the assertions stay in lock-step with the
single source of truth:

- the four conversion tables (`households`, `contacts`, `opportunities`, `tasks`)
  exist in **each** tenant schema, each with its full column set;
- each tenant role has full CRUD on its own copy (`has_table_privilege`);
- `platform_reader` has SELECT on every copy;
- `demo_purge` has SELECT + DELETE on every copy and is **denied** INSERT/UPDATE
  (the purge sweeps, never writes — the 0013 grant shape);
- `leads` carries the two converted-ref columns (`converted_contact_id`,
  `converted_opportunity_ids`);
- the whole migration round-trips: `downgrade 0014` drops the four tables and the
  two leads columns from every schema, `upgrade head` restores them.
"""

import os
from contextlib import contextmanager

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.tenancy.registry import DEMO_PURGE_ROLE, PLATFORM_ROLE, TENANTS

from tests.conftest import ALEMBIC_CONFIG_PATH, CORE_ROOT, build_postgresql_url

# The revision just below 0015, used as the downgrade target for the round-trip.
ONE_BELOW_LEAD_CONVERSION = "0014_timeline_outbox_grant"

# Expected (subset) columns per new table — kept in lock-step with 0015's DDL and
# the TDD §5.2 shape. Subset (`<=`) checks tolerate future additive columns.
EXPECTED_COLUMNS: dict[str, set[str]] = {
    "households": {
        "id",
        "name",
        "correlation_id",
        "demo_session_id",
        "created_at",
        "updated_at",
    },
    "contacts": {
        "id",
        "household_id",
        "first_name",
        "last_name",
        "zip_code",
        "age_band",
        "email_encrypted",
        "phone_encrypted",
        "date_of_birth_encrypted",
        "street_address_encrypted",
        "lead_source",
        "owner_user_id",
        "owner_username",
        "source_lead_id",
        "correlation_id",
        "demo_session_id",
        "created_at",
        "updated_at",
    },
    "opportunities": {
        "id",
        "contact_id",
        "household_id",
        "product_line",
        "stage",
        "owner_user_id",
        "owner_username",
        "estimated_annual_premium",
        "target_close_date",
        "origin",
        "source_lead_id",
        "correlation_id",
        "demo_session_id",
        "created_at",
        "updated_at",
    },
    "tasks": {
        "id",
        "related_entity_type",
        "related_entity_id",
        "task_type",
        "body",
        "assignee_user_id",
        "assignee_username",
        "due_date",
        "status",
        "correlation_id",
        "demo_session_id",
        "created_at",
        "updated_at",
    },
}

CONVERSION_TABLES: tuple[str, ...] = tuple(EXPECTED_COLUMNS)

NEW_LEAD_COLUMNS = {"converted_contact_id", "converted_opportunity_ids"}


@pytest.mark.asyncio
async def test_conversion_tables_exist_in_each_schema(database_engine):
    """`upgrade head` created the four tables, with their columns, per tenant."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            for table, expected_columns in EXPECTED_COLUMNS.items():
                column_rows = await connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = :schema AND table_name = :table"
                    ),
                    {"schema": tenant.schema_name, "table": table},
                )
                column_names = {row[0] for row in column_rows}
                assert expected_columns <= column_names, (
                    f"{tenant.schema_name}.{table} missing columns: "
                    f"{expected_columns - column_names}"
                )


@pytest.mark.asyncio
async def test_each_tenant_role_has_crud_on_its_own_conversion_tables(database_engine):
    """A tenant role can SELECT/INSERT/UPDATE/DELETE each of its own new tables."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            for table in CONVERSION_TABLES:
                qualified_table = f"{tenant.schema_name}.{table}"
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
async def test_platform_reader_has_select_on_every_conversion_table(database_engine):
    """The platform read-role has SELECT on every tenant's new tables."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            for table in CONVERSION_TABLES:
                qualified_table = f"{tenant.schema_name}.{table}"
                select_row = await connection.execute(
                    text("SELECT has_table_privilege(:role, :table, 'SELECT')"),
                    {"role": PLATFORM_ROLE, "table": qualified_table},
                )
                assert select_row.scalar_one() is True


@pytest.mark.asyncio
async def test_demo_purge_has_select_delete_but_not_write_on_conversion_tables(
    database_engine,
):
    """`demo_purge` has SELECT+DELETE on every new table, and never INSERT/UPDATE."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            for table in CONVERSION_TABLES:
                qualified_table = f"{tenant.schema_name}.{table}"
                for privilege in ("SELECT", "DELETE"):
                    granted_row = await connection.execute(
                        text(
                            "SELECT has_table_privilege(:role, :table, :privilege)"
                        ),
                        {
                            "role": DEMO_PURGE_ROLE,
                            "table": qualified_table,
                            "privilege": privilege,
                        },
                    )
                    assert granted_row.scalar_one() is True
                for privilege in ("INSERT", "UPDATE"):
                    denied_row = await connection.execute(
                        text(
                            "SELECT has_table_privilege(:role, :table, :privilege)"
                        ),
                        {
                            "role": DEMO_PURGE_ROLE,
                            "table": qualified_table,
                            "privilege": privilege,
                        },
                    )
                    assert denied_row.scalar_one() is False


@pytest.mark.asyncio
async def test_leads_has_converted_ref_columns_in_each_schema(database_engine):
    """`leads` gained `converted_contact_id` + `converted_opportunity_ids` per tenant."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            column_rows = await connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = 'leads'"
                ),
                {"schema": tenant.schema_name},
            )
            column_names = {row[0] for row in column_rows}
            assert NEW_LEAD_COLUMNS <= column_names


# --- Migration 0015 round-trip ------------------------------------------------


def build_alembic_config() -> Config:
    """Build an Alembic `Config` pointed at the core package's migration scripts.

    Mirrors the `database_engine` fixture in `conftest.py` (and the same helper in
    `test_leads_migration.py` / `test_migration_hygiene.py`): the same `alembic.ini`
    and `alembic/` script location, so the commands run exactly as production does.
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


async def conversion_schema_present_in_every_schema(database_engine) -> bool:
    """True only when all four tables and both leads columns exist in every schema."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            table_rows = await connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = :schema AND table_name = ANY(:tables)"
                ),
                {"schema": tenant.schema_name, "tables": list(CONVERSION_TABLES)},
            )
            present_tables = {row[0] for row in table_rows}
            if set(CONVERSION_TABLES) != present_tables:
                return False

            column_rows = await connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = 'leads' "
                    "AND column_name = ANY(:columns)"
                ),
                {"schema": tenant.schema_name, "columns": list(NEW_LEAD_COLUMNS)},
            )
            present_columns = {row[0] for row in column_rows}
            if NEW_LEAD_COLUMNS != present_columns:
                return False
    return True


@pytest.mark.asyncio
async def test_0015_round_trips(database_engine, postgres_container):
    """`downgrade 0014` drops the conversion schema; `upgrade head` restores it.

    Proves migration 0015 reverses and replays cleanly. The `database_engine`
    fixture has migrated the container to head, so the tables/columns start present.
    Downgrading one revision (to `0014`) drops the four tables and both leads columns
    from every tenant schema; upgrading back to head re-adds them. Head is restored
    in a `finally` so the shared session-scoped container is left exactly as the rest
    of the suite expects (pytest runs serially, so the transient downgrade is never
    observed by another test).
    """
    alembic_config = build_alembic_config()

    with database_url_pointed_at(postgres_container):
        assert await conversion_schema_present_in_every_schema(database_engine) is True

        try:
            command.downgrade(alembic_config, ONE_BELOW_LEAD_CONVERSION)
            assert (
                await conversion_schema_present_in_every_schema(database_engine)
                is False
            )

            command.upgrade(alembic_config, "head")
            assert (
                await conversion_schema_present_in_every_schema(database_engine)
                is True
            )
        finally:
            # Restore head no matter what so other tests see a migrated container.
            command.upgrade(alembic_config, "head")
