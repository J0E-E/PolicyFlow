"""Substrate proof for Epic 8 — the `get_public_tenant_db` public scoping seam.

These exercise `app.tenancy.scoping.get_public_tenant_db` end-to-end against the
real Postgres booted in Docker (the same `database_engine` substrate as
`test_tenant_scoping.py`), with the migrations applied and the demo data seeded.
Together they prove the public seam does what Epic 8 promises:

- **Whitelist guard:** an unknown slug — one that maps to no registered tenant —
  raises ``404`` (a stranger guessing a slug is a *client* error), and the
  registry lookup is itself the whitelist (no `platform.tenants` read).
- **Role/schema set:** for each tenant, entering the seam yields a session whose
  `current_user` is that tenant's `db_role` and whose `search_path` is its
  `schema_name` — proving the ``SET LOCAL``s resolve to the slug's own schema.
- **Reset after request (no leak, parity):** once the seam's ``async with`` exits,
  `current_user` and `search_path` on the same session are back to their defaults
  — the ``SET LOCAL``s discarded at commit, so nothing leaks onto a reused pooled
  connection. The exact no-leak parity `test_tenant_scoping.py` proves for the
  session-scoped seam.

The seam is an ``@asynccontextmanager``, so these drive it with ``async with``,
not the ``__anext__`` / ``_exhaust`` generator helpers `test_tenant_scoping.py`
uses for the raw ``Depends`` generator.
"""

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.seed import seed
from app.tenancy.registry import TENANTS
from app.tenancy.scoping import get_public_tenant_db


async def _seed(session_factory) -> None:
    """Seed the demo data so the tenant schemas and rows exist."""
    async with session_factory() as session:
        await seed(session)


# --- Whitelist guard ---------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_slug_is_rejected_with_404(container_keys_session_factory):
    """An unknown slug raises 404 — the registry lookup is the whitelist guard.

    A slug that maps to no registered tenant never reaches a ``SET LOCAL``: the
    `tenant_by_slug` `KeyError` is caught and re-raised as ``404``, because a
    stranger guessing a slug is a client error (contrast the session seam's 500
    for a misconfigured, authenticated tenant).
    """
    session_factory = container_keys_session_factory

    async with session_factory() as session:
        with pytest.raises(HTTPException) as rejection:
            async with get_public_tenant_db("no-such-tenant", session):
                pass

    assert rejection.value.status_code == 404


# --- Role/schema set ---------------------------------------------------------


@pytest.mark.asyncio
async def test_seam_sets_role_and_search_path_for_each_tenant(
    container_keys_session_factory,
):
    """Entering the seam scopes the session to the slug's own role and schema.

    For each tenant in turn, opens the seam on its slug and asserts the yielded
    session's `current_user` is that tenant's `db_role` and its `search_path` is
    its `schema_name` — proving the ``SET LOCAL``s resolve to the right schema,
    keyed only by the slug.
    """
    session_factory = container_keys_session_factory
    await _seed(session_factory)

    for tenant in TENANTS:
        async with session_factory() as session:
            async with get_public_tenant_db(tenant.slug, session) as scoped_session:
                scoped_user = (
                    await scoped_session.execute(text("SELECT current_user"))
                ).scalar_one()
                scoped_search_path = (
                    await scoped_session.execute(text("SHOW search_path"))
                ).scalar_one()

                assert scoped_user == tenant.db_role
                assert scoped_search_path == tenant.schema_name


# --- No leak (parity) --------------------------------------------------------


@pytest.mark.asyncio
async def test_role_and_search_path_reset_after_request(
    container_keys_session_factory,
):
    """After the seam's `async with` exits, role and search_path are default.

    Proves the ``SET LOCAL``s are discarded at commit: once the seam exits, a
    follow-up query on the same session shows `current_user` and `search_path`
    back to their defaults — the no-leak guarantee across reused pooled
    connections, in parity with `test_tenant_scoping.py`.
    """
    session_factory = container_keys_session_factory
    await _seed(session_factory)
    tenant = TENANTS[0]

    # Read the connection's defaults from a separate session, so the target
    # session below stays untouched until the seam opens its own transaction.
    async with session_factory() as defaults_session:
        default_user = (
            await defaults_session.execute(text("SELECT current_user"))
        ).scalar_one()
        default_search_path = (
            await defaults_session.execute(text("SHOW search_path"))
        ).scalar_one()

    async with session_factory() as session:
        async with get_public_tenant_db(tenant.slug, session) as scoped_session:
            scoped_user = (
                await scoped_session.execute(text("SELECT current_user"))
            ).scalar_one()
            assert scoped_user == tenant.db_role

        # Past the `async with` the transaction has committed, discarding the
        # SET LOCALs — the same session is back to the connection defaults.
        user_after_request = (
            await session.execute(text("SELECT current_user"))
        ).scalar_one()
        search_path_after_request = (
            await session.execute(text("SHOW search_path"))
        ).scalar_one()

    assert user_after_request == default_user
    assert search_path_after_request == default_search_path
