"""Live append-only + isolation acceptance for the audit stores (Epic 5).

This is the **live-execution** counterpart to Epic 2's `test_audit_migration.py`.
That file proved the *grant shape* by reading Postgres' privilege catalog
(`has_table_privilege` booleans). A catalog boolean can be bypassed by a
superuser; a **raised `permission denied` error cannot**. So here every forbidden
statement is actually run under the real role and Postgres is asserted to refuse
it — closing the superuser-bypass concern (TDD §7) and standing as the phase's
physical append-only + isolation proof.

No production code: rows are written directly as `audit_writer` (a plain
`INSERT`), not through the Epic 4 service — the proof stays at the pure physical
layer (no `seed()`, no keys fixture, no `record_audit_event` import). That
successful INSERT is itself the positive control that `audit_writer` can append.

- **Phase 1 — append-only is physical (immutability):** for every store, the
  successful `audit_writer` INSERT contrasts with an `UPDATE` and a `DELETE` that
  Postgres denies under the same role; and a tenant role is denied INSERT /
  UPDATE / DELETE on even its own audit (it is SELECT-only).
- **Phase 2 — read isolation (confidentiality + SELECT-only):** a tenant role
  reads its own audit back (positive control, so denials elsewhere prove
  isolation, not a broken role), is denied another tenant's audit, and
  `platform_reader` is denied every tenant's audit.

Mirrors the Phase-1 substrate half of `test_isolation_acceptance.py`: the
session-scoped `database_engine` fixture, one `async with database_engine.begin()`
block per forbidden attempt (the denial aborts that transaction, and
`SET LOCAL ROLE` resets on the rollback — exactly the production `SET LOCAL`
pattern), identifiers taken only from `app.tenancy.registry` and interpolated
verbatim (never request input), and the `ProgrammingError` / "permission denied"
assertion. `pytest.ini` is `asyncio_mode = auto`, but the substrate tests still
carry `@pytest.mark.asyncio`, matching the mirror.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.tenancy.registry import AUDIT_WRITER_ROLE, PLATFORM_ROLE, TENANTS


def _all_audit_tables() -> list[str]:
    """Return every audit store's schema-qualified table name.

    Each tenant's `<schema>.audit_records` plus the tenantless
    `platform.audit_records`, read only from the registry so the list stays in
    lock-step with the migration's single source of truth.
    """
    return [f"{tenant.schema_name}.audit_records" for tenant in TENANTS] + [
        "platform.audit_records"
    ]


def _tenant_pairs():
    """Yield every ordered (acting, other) tenant pair from the registry.

    The acting tenant's role is switched on; the other tenant's audit store is the
    one that must be physically out of reach. (Code body verbatim from
    `test_isolation_acceptance.py`.)
    """
    for acting in TENANTS:
        for other in TENANTS:
            if other is not acting:
                yield acting, other


async def _insert_audit_row_as_writer(database_engine, qualified_table, marker):
    """Append one marked audit row to `qualified_table` as `audit_writer`.

    Opens its own transaction, `SET LOCAL ROLE audit_writer`, and runs a minimal
    `INSERT` of only the three NOT-NULL columns (`id`, `event_type`, `outcome`) —
    `occurred_at` falls back to its `now()` default and every other column is
    nullable. `entity_id` carries the per-test `marker` uuid so a later `SELECT`
    stays attributable across the session-scoped (never-reset) database. The
    statement succeeding **is** the audit_writer-can-INSERT positive control.
    """
    async with database_engine.begin() as connection:
        await connection.execute(text(f"SET LOCAL ROLE {AUDIT_WRITER_ROLE}"))
        await connection.execute(
            text(
                f"INSERT INTO {qualified_table} "
                "(id, event_type, outcome, entity_id) "
                "VALUES (gen_random_uuid(), 'record.created', 'success', :marker)"
            ),
            {"marker": marker},
        )


async def _denied(database_engine, role, statement):
    """Assert `statement` raises a "permission denied" error under `role`.

    Runs the attempt in its own transaction: the denial aborts it, and the
    `SET LOCAL ROLE` resets when the block rolls back on the raised error (the
    production `SET LOCAL` pattern). Postgres surfaces an insufficient-privilege
    error as a SQLAlchemy `ProgrammingError` wrapping asyncpg's
    `InsufficientPrivilegeError`, reading "permission denied".
    """
    with pytest.raises(ProgrammingError) as denial:
        async with database_engine.begin() as connection:
            await connection.execute(text(f"SET LOCAL ROLE {role}"))
            await connection.execute(text(statement))

    message = str(denial.value).lower()
    assert "permission denied" in message, (
        f"expected {role} to be denied `{statement}`, got: {message}"
    )


# --- Phase 1: append-only is physical (immutability) -------------------------


@pytest.mark.asyncio
async def test_audit_writer_can_insert_but_cannot_update_or_delete(database_engine):
    """audit_writer may append but is physically denied UPDATE and DELETE.

    For every store (each tenant's `audit_records` plus `platform.audit_records`):
    insert a marked row as `audit_writer` (this succeeding is the positive control
    that the role can append), then attempt an `UPDATE ... SET outcome='tampered'`
    and a `DELETE FROM ...` under `SET LOCAL ROLE audit_writer`. Each must raise
    "permission denied" — the live proof that no role the app writes audit as can
    ever change or remove a record (append-only is enforced beneath the app, not
    merely a privilege-catalog boolean).
    """
    for qualified_table in _all_audit_tables():
        marker = uuid.uuid4()
        await _insert_audit_row_as_writer(database_engine, qualified_table, marker)

        await _denied(
            database_engine,
            AUDIT_WRITER_ROLE,
            f"UPDATE {qualified_table} SET outcome = 'tampered'",
        )
        await _denied(
            database_engine,
            AUDIT_WRITER_ROLE,
            f"DELETE FROM {qualified_table}",
        )


@pytest.mark.asyncio
async def test_tenant_role_cannot_write_its_own_audit(database_engine):
    """A tenant role is SELECT-only: every write to its own audit is denied.

    For each tenant, under `SET LOCAL ROLE <tenant.db_role>`, an `INSERT` /
    `UPDATE` / `DELETE` on its **own** `audit_records` must each raise "permission
    denied". This is the live proof that the audit-write capability is reserved to
    `audit_writer` alone — a tenant role can read its history but can never forge,
    alter, or erase a record in it.
    """
    for tenant in TENANTS:
        qualified_table = f"{tenant.schema_name}.audit_records"
        forbidden_statements = [
            (
                f"INSERT INTO {qualified_table} (id, event_type, outcome) "
                "VALUES (gen_random_uuid(), 'record.created', 'success')"
            ),
            f"UPDATE {qualified_table} SET outcome = 'tampered'",
            f"DELETE FROM {qualified_table}",
        ]
        for statement in forbidden_statements:
            await _denied(database_engine, tenant.db_role, statement)


# --- Phase 2: read isolation (confidentiality + SELECT-only) -----------------


@pytest.mark.asyncio
async def test_tenant_role_can_read_its_own_audit(database_engine):
    """A tenant role reads its own audit back — denial elsewhere is isolation.

    Insert a marked row as `audit_writer`, then under
    `SET LOCAL ROLE <tenant.db_role>` `SELECT ... WHERE entity_id = :marker` and
    confirm exactly that row returns. This is the positive control that the read
    denials in the other Phase-2 tests prove *isolation*, not a broken role
    (mirrors `test_switched_tenant_role_still_reads_own_schema`).
    """
    for tenant in TENANTS:
        qualified_table = f"{tenant.schema_name}.audit_records"
        marker = uuid.uuid4()
        await _insert_audit_row_as_writer(database_engine, qualified_table, marker)

        async with database_engine.begin() as connection:
            await connection.execute(text(f"SET LOCAL ROLE {tenant.db_role}"))
            own_row = (
                await connection.execute(
                    text(
                        f"SELECT entity_id FROM {qualified_table} "
                        "WHERE entity_id = :marker"
                    ),
                    {"marker": marker},
                )
            ).one()
            assert own_row.entity_id == marker


@pytest.mark.asyncio
async def test_tenant_role_is_denied_other_tenant_audit(database_engine):
    """Under `SET LOCAL ROLE tenant_<A>`, reading <B>'s audit is denied.

    For every ordered `(acting, other)` tenant pair, a
    `SELECT * FROM <other>.audit_records` under `SET LOCAL ROLE <acting.db_role>`
    must raise "permission denied" — the live proof that one tenant's audit
    history is physically out of reach of any other tenant's role.
    """
    for acting, other in _tenant_pairs():
        await _denied(
            database_engine,
            acting.db_role,
            f"SELECT * FROM {other.schema_name}.audit_records",
        )


@pytest.mark.asyncio
async def test_platform_reader_cannot_read_any_tenant_audit(database_engine):
    """platform_reader is denied SELECT on every tenant's audit.

    Under `SET LOCAL ROLE platform_reader`, a `SELECT` on each tenant's
    `audit_records` must raise "permission denied" — the live proof that the
    cross-tenant platform read role still cannot reach any tenant's audit history
    (tenant audit is readable only inside its own tenant).
    """
    for tenant in TENANTS:
        await _denied(
            database_engine,
            PLATFORM_ROLE,
            f"SELECT * FROM {tenant.schema_name}.audit_records",
        )
