"""Smoke tests for the real-database test substrate (Epic 11).

These prove the substrate fixtures in `conftest.py` actually work against a real
Postgres booted in Docker:

- the migrations applied (the `platform` tables and the `user_role` enum exist);
- a real write/read round-trip survives through `db_session`;
- the DB-backed `db_client` reaches the app on a DB-touching path.

Epics 12 and 13 build their real-database tests on the same fixtures.
"""

import uuid

import pytest
from sqlalchemy import select, text

from app.models.tenant import Tenant


@pytest.mark.asyncio
async def test_migrations_created_platform_tables(database_engine):
    """`upgrade head` created the three `platform` tables and the role enum."""
    async with database_engine.connect() as connection:
        table_rows = await connection.execute(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'platform'"
            )
        )
        table_names = {row[0] for row in table_rows}

        enum_rows = await connection.execute(
            text(
                "SELECT t.typname FROM pg_type t "
                "JOIN pg_namespace n ON n.oid = t.typnamespace "
                "WHERE n.nspname = 'platform' AND t.typname = 'user_role'"
            )
        )
        enum_names = {row[0] for row in enum_rows}

    assert {"tenants", "users", "auth_sessions"} <= table_names
    assert "user_role" in enum_names


@pytest.mark.asyncio
async def test_tenant_round_trip_through_db_session(db_session):
    """A tenant inserted via `db_session` reads back from the real database."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Round Trip Insurance",
        slug=f"round-trip-{uuid.uuid4().hex}",
    )
    db_session.add(tenant)
    await db_session.commit()

    found = await db_session.execute(
        select(Tenant).where(Tenant.id == tenant.id)
    )
    read_back = found.scalar_one()

    assert read_back.name == "Round Trip Insurance"
    assert read_back.slug == tenant.slug


@pytest.mark.asyncio
async def test_db_client_reaches_app_on_db_touching_path(db_client):
    """The DB-backed client reaches the app: no cookie → 401 on a guarded path."""
    response = await db_client.get("/api/tenant/config")

    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}
