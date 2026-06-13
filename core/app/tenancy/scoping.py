"""The per-request tenant scoping seam: the `get_tenant_db` dependency.

Epics 1–4 built the substrate — a tenant registry, the schemas/roles/grants
migration, the seed that fills `platform.tenants.schema_name`/`db_role`, and a
real tenant-scoped table (`tenant_settings`). This module delivers the seam that
makes isolation *automatic*: a FastAPI dependency that, on every tenant-scoped
request, opens a transaction, looks up the caller's schema and DB role from their
session identity, and issues ``SET LOCAL ROLE`` + ``SET LOCAL search_path`` so
every query reads only that tenant's schema and resets at transaction end
(leak-proof by construction).

Epic 7 adds the Platform-Admin carve-out alongside it: `get_platform_db`, the
sanctioned cross-tenant read seam. It mirrors `get_tenant_db`'s lifecycle but
runs as the read-only `platform_reader` role instead of a per-tenant role, so a
Platform Admin can read every tenant's schema. It is gated by
`require_platform_admin`, and it `await`s a named, no-op audit seam
(`record_platform_read_for_audit`) so P1.4 can later log every cross-tenant read
by filling that one body — with zero call-site churn.

Settled decisions:
- A tenantless caller (a Platform Admin, whose `identity.tenant_id` is `None`)
  raises ``400 {"detail": "no tenant context"}`` — they must use the Epic-7 path.
- The schema/role pair is **re-read each request** from `platform.tenants` (one
  indexed primary-key read; no cache), per the TDD's decision.

Names are reused from their single source of truth — `Identity`,
`require_authenticated`, and `require_platform_admin` from `app.auth`, `get_db`
from `app.db`, the `Tenant` model from `app.models`, and the registry whitelist
(plus the `PLATFORM_ROLE` constant) from `app.tenancy.registry`. Nothing is
redeclared here.
"""

from typing import AsyncIterator

from fastapi import Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import require_authenticated, require_platform_admin
from ..auth.provider import Identity
from ..db import get_db
from ..models.tenant import Tenant
from .registry import PLATFORM_ROLE, TENANTS


def is_known_tenant_pair(schema_name: str, db_role: str) -> bool:
    """Return whether `(schema_name, db_role)` matches a registered tenant.

    The registry is the single source of truth for which schema and DB role
    serve each tenant. Confirming the looked-up pair against it before the pair
    is interpolated into a ``SET LOCAL`` statement is the whitelist guard that
    makes that interpolation safe — SQL identifiers cannot be passed as bound
    parameters, so an unrecognized pair must never reach the statement text.
    """
    return any(
        tenant.schema_name == schema_name and tenant.db_role == db_role
        for tenant in TENANTS
    )


async def get_tenant_db(
    identity: Identity = Depends(require_authenticated),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[AsyncSession]:
    """Yield a database session scoped to the caller's own tenant schema.

    The per-request isolation seam every tenant-scoped route leans on. In order:

    1. Inherit the 401 path via `require_authenticated`, giving the caller's
       `Identity`, and reuse the request `AsyncSession` from `get_db`.
    2. A tenantless caller (a Platform Admin, `identity.tenant_id is None`) is
       rejected with ``400 {"detail": "no tenant context"}`` **before** any
       transaction opens — they must use the Epic-7 platform path.
    3. Open one request transaction with ``async with db.begin()`` and, inside it:
       - Read this tenant's `schema_name`/`db_role` from `platform.tenants` by
         `tenant_id`. This read runs as the default login role, *before*
         ``SET LOCAL ROLE``, so it can still see the `platform` schema.
       - Whitelist-validate the looked-up pair against the registry. A missing
         row or an unrecognized pair is a server invariant violation, raised as
         ``500 {"detail": "tenant scoping misconfigured"}`` — and it guards the
         identifier interpolation on the next step.
       - Issue ``SET LOCAL ROLE <db_role>`` then
         ``SET LOCAL search_path TO <schema_name>`` with the validated
         identifiers, then yield the now-scoped session.

    The ``async with db.begin()`` block commits on normal exit (which discards
    both ``SET LOCAL``s, resetting the connection) and rolls back on any
    exception — so nothing leaks onto a reused pooled connection.
    """
    if identity.tenant_id is None:
        raise HTTPException(status_code=400, detail="no tenant context")

    # `require_authenticated` resolves the caller by reading the session table on
    # this same session, which auto-begins a read transaction. Close it out first
    # so the scoped transaction below starts clean — `db.begin()` would otherwise
    # raise "a transaction is already begun". The identity is already materialized,
    # so discarding that read transaction loses nothing.
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        tenant_row = (
            await db.execute(
                select(Tenant.schema_name, Tenant.db_role).where(
                    Tenant.id == identity.tenant_id
                )
            )
        ).one_or_none()

        if tenant_row is None or not is_known_tenant_pair(
            tenant_row.schema_name, tenant_row.db_role
        ):
            raise HTTPException(
                status_code=500, detail="tenant scoping misconfigured"
            )

        schema_name = tenant_row.schema_name
        db_role = tenant_row.db_role

        # Identifiers cannot be bound as parameters, so they are interpolated —
        # but only after `is_known_tenant_pair` confirmed both come verbatim from
        # the registry whitelist, never from user input.
        await db.execute(text(f"SET LOCAL ROLE {db_role}"))
        await db.execute(text(f"SET LOCAL search_path TO {schema_name}"))

        yield db


async def record_platform_read_for_audit(identity: Identity) -> None:
    """The **P1.4 audit seam** for cross-tenant platform reads — a no-op today.

    Every cross-tenant read through `get_platform_db` is a privileged action that
    P1.4 will audit-log. This function is the single, named place that log will be
    written: `get_platform_db` already `await`s it on the privileged path, so P1.4
    only fills this body — no call site changes. It deliberately does nothing yet
    (emits no audit record), so the carve-out works today without an audit store.
    """
    return None


async def get_platform_db(
    identity: Identity = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[AsyncSession]:
    """Yield a database session that can read across every tenant's schema.

    The sanctioned cross-tenant read seam — the controlled exception to tenant
    isolation. It mirrors `get_tenant_db`'s lifecycle, but is gated by
    `require_platform_admin` (only the Platform Admin reaches here) and runs as the
    read-only `platform_reader` role rather than a per-tenant role. In order:

    1. Inherit the 401/403 path via `require_platform_admin`, giving the Platform
       Admin's `Identity`, and reuse the request `AsyncSession` from `get_db`.
    2. Close out any read transaction `require_platform_admin` left open (it reads
       the session table first), the same reason `get_tenant_db` does — `db.begin()`
       would otherwise raise "a transaction is already begun".
    3. Open one request transaction with `async with db.begin()` and, inside it:
       - Issue `SET LOCAL ROLE platform_reader` (the role name comes from the
         `PLATFORM_ROLE` constant in the registry — a fixed string, never user
         input), granting the cross-tenant `SELECT` Epic 2's migration set up.
       - `await` the named audit seam `record_platform_read_for_audit` (a no-op
         today; the place P1.4 logs the read).
       - Yield the now-platform-scoped session.

    The `async with db.begin()` block commits on normal exit, which discards the
    `SET LOCAL ROLE` and resets the connection, and rolls back on any exception —
    so the elevated role never leaks onto a reused pooled connection.
    """
    # `require_platform_admin` resolves the caller by reading the session table on
    # this same session, which auto-begins a read transaction. Close it out first
    # so the scoped transaction below starts clean.
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        # `PLATFORM_ROLE` is a fixed registry constant, not user input, so this
        # identifier interpolation is safe.
        await db.execute(text(f"SET LOCAL ROLE {PLATFORM_ROLE}"))
        await record_platform_read_for_audit(identity)
        yield db
