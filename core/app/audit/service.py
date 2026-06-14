"""The audit-emit service — the single place every audited action writes through.

The whole P1.4 phase records sensitive actions by calling **one** function,
`record_audit_event(...)`. This module is that function. It picks a store, opens
its **own** short-lived database session, becomes the `audit_writer` role, and
writes exactly one append-only row that stores field *names*, never their values.

**Store routing (one rule).** `tenant_id` present → that tenant's own
``audit_records`` table inside its schema; `tenant_id` absent (`None`) → the
shared ``platform.audit_records`` table. The platform branch needs no lookup
(the schema is the literal ``"platform"``); the tenant branch reads the tenant's
``schema_name`` from ``platform.tenants`` and whitelist-validates it via
`is_known_schema` before that name is interpolated into the ``INSERT`` text.

**Own-session, separate from any request.** Like `app.pii.keys`, the service
holds a module-global `session_factory` (the engine handed in by `app.db`,
monkeypatchable in tests) and opens its own session per call rather than reusing a
request's tenant-scoped session. That is what lets later epics fill the two
waiting no-op seams (`record_platform_read_for_audit`, `on_pii_revealed`) with
zero call-site changes: the audit write never depends on the caller's role,
schema, or transaction.

**Why a schema-qualified raw INSERT, not the ORM models.** A schema name cannot be
a bound SQL parameter, so it must be interpolated into the statement text — but
only the registry-validated name is, and every audited value (`tenant_id`,
`actor_user_id`, `field_names`, …) is bound as a parameter. The write is fully
schema-qualified (`INSERT INTO <schema>.audit_records ...`), so no ``search_path``
is needed. `occurred_at` is omitted so the column's ``now()`` server default sets
it; ordering (newest-first) is the reader's concern (Epic 10), not the service's.

**Tenant-isolation note (the project's cross-cutting axis).** The schema lookup
runs as the default login role, **before** any role switch, so it can read the
shared ``platform`` schema. The single write then becomes `audit_writer` — a role
that can only INSERT/SELECT on the audit stores (Epic 2's grants) — so a tenant's
audit row lands in that tenant's own schema and nowhere else. The schema whitelist
guard ensures an unrecognized schema name can never reach the statement text.

**Strict failure (TDD Decision 7).** The service swallows nothing. An unknown
tenant raises `UnknownAuditTenant`, and a failed write propagates, so a sensitive
operation can never silently proceed unaudited.

Precedents this mirrors: the own-session module-global in `app.pii.keys`, the
schema-resolve + whitelist + ``SET LOCAL ROLE`` interpolation idiom in
`app.tenancy.scoping.get_tenant_db`, and the loud-lookup exception
`TenantDataKeyNotFound`.
"""

import uuid
from typing import Optional

from sqlalchemy import text

from ..db import session_factory
from ..tenancy.registry import AUDIT_WRITER_ROLE, is_known_schema
from .records import EventType, Outcome

# The shared, tenantless store's schema. A literal — no lookup or whitelist check
# is needed because it is not derived from any caller-supplied value.
PLATFORM_SCHEMA = "platform"


class UnknownAuditTenant(LookupError):
    """Raised when an audit `tenant_id` cannot be routed to a known store.

    Fires when a `tenant_id` has **no row** in ``platform.tenants`` or its
    ``schema_name`` **fails `is_known_schema`** — the whitelist guard raises rather
    than interpolating an untrusted schema name into the ``INSERT``. Mirrors the
    loud-lookup `TenantDataKeyNotFound` precedent: a bad tenant is a
    misconfiguration, so the service fails loud and names the tenant id rather than
    writing nowhere silently. Being strict (TDD Decision 7) means a sensitive
    operation can never proceed unaudited.
    """

    def __init__(self, tenant_id: uuid.UUID) -> None:
        self.tenant_id = tenant_id
        super().__init__(
            f"cannot route an audit record for tenant {tenant_id}: no matching "
            "schema in platform.tenants / the registry whitelist"
        )


async def record_audit_event(
    *,
    tenant_id: Optional[uuid.UUID],
    actor_user_id: Optional[uuid.UUID],
    actor_role: Optional[str],
    event_type: EventType,
    outcome: Outcome,
    entity_type: Optional[str] = None,
    entity_id: Optional[uuid.UUID] = None,
    field_names: Optional[list[str]] = None,
) -> None:
    """Write one append-only audit record to the store the `tenant_id` selects.

    The single function every audited action calls. In order:

    1. **Route the store.** `tenant_id is None` → the shared ``platform`` schema
       (a literal, no lookup). Otherwise open the own session and read the tenant's
       ``schema_name`` from ``platform.tenants`` as the login role (before any role
       switch), then whitelist-validate it with `is_known_schema`. A missing row or
       an unrecognized schema raises `UnknownAuditTenant` (strict — no swallowing).
    2. **Write the row.** In one transaction on the own session, ``SET LOCAL ROLE
       audit_writer`` (the name from `AUDIT_WRITER_ROLE`), then a schema-qualified
       ``INSERT INTO <schema>.audit_records (...)`` with a fresh ``uuid.uuid4()``
       id, ``occurred_at`` omitted (the column's ``now()`` default), and every
       other value bound as a parameter. Only the registry-validated schema name is
       interpolated. Commit.

    Stores field *names* only (`field_names`), never their values. Returns `None`
    on success; raises on any failure so a sensitive op never proceeds unaudited.
    """
    schema_name = await _get_audit_schema(tenant_id)
    await _write_audit_row(
        schema_name=schema_name,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        event_type=event_type,
        outcome=outcome,
        entity_type=entity_type,
        entity_id=entity_id,
        field_names=field_names,
    )


async def _get_audit_schema(tenant_id: Optional[uuid.UUID]) -> str:
    """Return the schema name of the store this `tenant_id` routes to.

    `tenant_id is None` → the literal ``platform`` schema. Otherwise opens the
    module-global `session_factory`'s own session as the default login role (no
    role switch), reads the tenant's ``schema_name`` from ``platform.tenants``, and
    whitelist-validates it. Raises `UnknownAuditTenant` when no row exists or the
    schema fails `is_known_schema` — the guard that makes the later interpolation
    safe. Reading as the login role (before any ``SET LOCAL ROLE``) is what lets
    this see the shared ``platform`` schema, mirroring `get_tenant_db`'s pre-switch
    read.
    """
    if tenant_id is None:
        return PLATFORM_SCHEMA

    async with session_factory() as session:
        schema_name = (
            await session.execute(
                text(
                    "SELECT schema_name FROM platform.tenants "
                    "WHERE id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            )
        ).scalar_one_or_none()

    if schema_name is None or not is_known_schema(schema_name):
        raise UnknownAuditTenant(tenant_id)
    return schema_name


async def _write_audit_row(
    *,
    schema_name: str,
    tenant_id: Optional[uuid.UUID],
    actor_user_id: Optional[uuid.UUID],
    actor_role: Optional[str],
    event_type: EventType,
    outcome: Outcome,
    entity_type: Optional[str],
    entity_id: Optional[uuid.UUID],
    field_names: Optional[list[str]],
) -> None:
    """Insert one row into ``<schema_name>.audit_records`` as the writer role.

    Opens its own session, then in one transaction issues ``SET LOCAL ROLE
    audit_writer`` and a schema-qualified ``INSERT``. `schema_name` is interpolated
    into the statement text because a schema name cannot be a bound parameter — but
    it is only ever a registry-validated name from `_get_audit_schema` (or the
    `platform` literal), never a caller-supplied value, so the interpolation is
    safe (the `get_tenant_db` whitelist-then-interpolate idiom). The `id` is a fresh
    ``uuid.uuid4()``, ``occurred_at`` is omitted so the column's ``now()`` server
    default sets it, and every other value is bound as a parameter. Commits.
    """
    async with session_factory() as session:
        # `AUDIT_WRITER_ROLE` is a fixed registry constant, not user input, so this
        # identifier interpolation is safe.
        await session.execute(text(f"SET LOCAL ROLE {AUDIT_WRITER_ROLE}"))
        await session.execute(
            text(
                f"INSERT INTO {schema_name}.audit_records "
                "(id, tenant_id, actor_user_id, actor_role, event_type, "
                "entity_type, entity_id, field_names, outcome) "
                "VALUES (:id, :tenant_id, :actor_user_id, :actor_role, "
                ":event_type, :entity_type, :entity_id, :field_names, :outcome)"
            ),
            {
                "id": uuid.uuid4(),
                "tenant_id": tenant_id,
                "actor_user_id": actor_user_id,
                "actor_role": actor_role,
                "event_type": str(event_type),
                "entity_type": entity_type,
                "entity_id": entity_id,
                "field_names": field_names,
                "outcome": str(outcome),
            },
        )
        await session.commit()
