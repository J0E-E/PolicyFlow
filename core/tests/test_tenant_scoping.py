"""Substrate proof for Epic 5 — the `get_tenant_db` scoping dependency.

These exercise `app.tenancy.scoping.get_tenant_db` end-to-end against the real
Postgres booted in Docker (the same `database_engine` substrate as
`test_tenant_settings.py`), with the migrations applied and the demo data
seeded. Together they prove the seam does what the epic promises:

- **Happy path:** a scoped session reads **its own** tenant's `tenant_settings`
  row — proving ``SET LOCAL search_path`` resolves the schema-less
  `TenantSettings` model to the right schema (Phase 1).
- **Tenantless guard:** a Platform Admin (`tenant_id is None`) is rejected with
  ``400 {"detail": "no tenant context"}`` before any transaction opens
  (Phase 2).
- **Reset after request (no leak):** once the `get_tenant_db` transaction
  commits, a follow-up query on the same connection shows `search_path` and
  `current_user` back to their defaults — the ``SET LOCAL``s discarded at commit,
  so nothing leaks onto a reused pooled connection (Phase 2).
"""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth.provider import Identity
from app.models.user import Role
from app.seed import seed
from app.tenancy.registry import TENANTS
from app.tenancy.scoping import get_tenant_db


async def _seed_and_get_tenant_id(session_factory, slug: str) -> uuid.UUID:
    """Seed the demo data, then return the `platform.tenants` id for `slug`."""
    async with session_factory() as session:
        await seed(session)
    async with session_factory() as session:
        tenant_id_row = await session.execute(
            text("SELECT id FROM platform.tenants WHERE slug = :slug"),
            {"slug": slug},
        )
        return tenant_id_row.scalar_one()


def _identity_for_tenant(tenant_id: uuid.UUID) -> Identity:
    """Build a real `Identity` for a tenant Agent pointing at `tenant_id`."""
    return Identity(
        user_id=uuid.uuid4(),
        tenant_id=tenant_id,
        role=Role.AGENT,
        username="agent.one@example",
    )


async def _drive_to_first_yield(generator):
    """Advance an async-generator dependency to its single yielded value."""
    return await generator.__anext__()


async def _exhaust(generator) -> None:
    """Run an async-generator dependency past its yield so its block exits.

    `get_tenant_db` yields once inside ``async with db.begin()``; advancing it a
    second time raises `StopAsyncIteration` as the generator returns, which also
    commits that transaction (discarding the ``SET LOCAL``s).
    """
    try:
        await generator.__anext__()
    except StopAsyncIteration:
        pass


# --- Phase 1: happy path -----------------------------------------------------


@pytest.mark.asyncio
async def test_scoped_session_reads_only_its_own_tenant_settings(database_engine):
    """A `get_tenant_db` session reads its own tenant's settings row.

    Drives the dependency for each tenant in turn and asserts the row it sees
    through the yielded session is keyed to *that* tenant's id — proving
    ``SET LOCAL search_path`` resolves the schema-less `TenantSettings` to the
    caller's own schema, not another tenant's.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)

    for tenant in TENANTS:
        tenant_id = await _seed_and_get_tenant_id(session_factory, tenant.slug)
        identity = _identity_for_tenant(tenant_id)

        async with session_factory() as session:
            generator = get_tenant_db(identity=identity, db=session)
            scoped_session = await _drive_to_first_yield(generator)

            settings_row = (
                await scoped_session.execute(
                    text(
                        "SELECT tenant_id, welcome_message, brand_primary_color "
                        "FROM tenant_settings"
                    )
                )
            ).one()

            assert settings_row.tenant_id == tenant_id
            assert settings_row.welcome_message
            assert settings_row.brand_primary_color

            await _exhaust(generator)


# --- Phase 2: guard + reset proofs -------------------------------------------


@pytest.mark.asyncio
async def test_tenantless_caller_is_rejected_with_400(database_engine):
    """A tenantless caller (Platform Admin) raises 400 'no tenant context'.

    The guard fires before any transaction opens, so a Platform Admin
    (`tenant_id is None`) is steered to the Epic-7 platform path instead.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    platform_admin_identity = Identity(
        user_id=uuid.uuid4(),
        tenant_id=None,
        role=Role.PLATFORM_ADMIN,
        username="platform.admin@policyflow.example",
    )

    async with session_factory() as session:
        generator = get_tenant_db(
            identity=platform_admin_identity, db=session
        )
        with pytest.raises(HTTPException) as rejection:
            await _drive_to_first_yield(generator)

    assert rejection.value.status_code == 400
    assert rejection.value.detail == "no tenant context"


@pytest.mark.asyncio
async def test_role_and_search_path_reset_after_request(database_engine):
    """After the scoped transaction commits, role and search_path are default.

    Proves the ``SET LOCAL``s are discarded at commit: a follow-up query on the
    same session shows `current_user` and `search_path` back to their defaults —
    the no-leak guarantee across reused pooled connections.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    tenant = TENANTS[0]
    tenant_id = await _seed_and_get_tenant_id(session_factory, tenant.slug)
    identity = _identity_for_tenant(tenant_id)

    # Read the connection's defaults from a separate session, so the target
    # session below stays untouched until `get_tenant_db` opens its own
    # transaction (matching how `get_db` hands the dependency a fresh session).
    async with session_factory() as defaults_session:
        default_user = (
            await defaults_session.execute(text("SELECT current_user"))
        ).scalar_one()
        default_search_path = (
            await defaults_session.execute(text("SHOW search_path"))
        ).scalar_one()

    async with session_factory() as session:
        # Inside the scoped transaction, role and search_path are the tenant's.
        generator = get_tenant_db(identity=identity, db=session)
        scoped_session = await _drive_to_first_yield(generator)
        scoped_user = (
            await scoped_session.execute(text("SELECT current_user"))
        ).scalar_one()
        scoped_search_path = (
            await scoped_session.execute(text("SHOW search_path"))
        ).scalar_one()
        assert scoped_user == tenant.db_role
        assert scoped_search_path == tenant.schema_name

        # Past the yield the transaction commits, discarding the SET LOCALs.
        await _exhaust(generator)

        user_after_request = (
            await session.execute(text("SELECT current_user"))
        ).scalar_one()
        search_path_after_request = (
            await session.execute(text("SHOW search_path"))
        ).scalar_one()

    assert user_after_request == default_user
    assert search_path_after_request == default_search_path
