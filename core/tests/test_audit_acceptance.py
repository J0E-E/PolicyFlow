"""Audit acceptance suite for P1.4 (Epic 11).

This is the phase's named acceptance proof: that a sensitive op of every wired
kind produces a names-not-values audit record, that append-only holds physically,
that one tenant's audit is tenant-only (and the platform store is invisible to
tenants), and that viewing the audit log is itself an audited operation.

It is packaged **add-only** — it asserts only the genuinely-missing end-to-end
narrative that ties the spine together, and deliberately does **not** move,
re-run, or duplicate the focused per-epic matrices, nor re-implement migration
health. Specifically, what stays owned elsewhere:

- **Migration health** stays entirely in `test_migration_hygiene.py`: it asserts
  `alembic check` no-drift (with `platform.audit_records` reflected and the
  schema-less per-tenant `audit_records` excluded by the `alembic/env.py` filter)
  and the `downgrade base -> upgrade head` round-trip — which replays the whole
  chain, `0007` included. This module adds **no new migration-health code**; the
  phase's "confirm `0007` health" is satisfied by running that file green in the
  gate.
- **The full case matrices** stay in the per-epic tests: the live append-only /
  isolation matrix in `test_audit_append_only_acceptance.py`, the auth-path matrix
  in `test_auth_audit.py`, the record-change matrix in `test_record_change_audit.py`,
  and the read-endpoint RBAC / isolation / no-PII matrix in `test_audit_endpoint.py`
  (plus the reveal / cross-read seam tests). The narrative below is a concise
  summary that exercises each wired kind once, not a re-run of those matrices.

The four tests (simplest-first, each independently reviewable) cover the four
Epic-11 goal bullets, and across them every one of the five wired event kinds
appears (`auth.login`, `record.created`, `pii.revealed`, `audit.viewed`,
`platform.cross_tenant_read`):

- **Test 1 — every wired kind is audited, names-not-values (tenant HTTP narrative):**
  as the Agent, create one record with sentinel PII (`record.created`) and reveal
  its `email` (`pii.revealed`); the Agent's login already wrote `auth.login`. Then
  as the Tenant Admin, `GET /api/audit` returns rows of all three kinds, the
  reveal / create rows carry field *names* (e.g. `"email"`), and the sentinel
  plaintext appears **nowhere** in the serialized body.
- **Test 2 — viewing audit is itself audited (`audit.viewed`):** two successive
  `GET /api/audit` as a Tenant Admin; the second response contains an
  `audit.viewed` row attributed to the caller that the first did not.
- **Test 3 — tenant audit is tenant-only (`platform.cross_tenant_read` lands in
  the platform store):** a Platform Admin's `GET /api/platform/tenant-settings`
  writes one `platform.cross_tenant_read` row to the **platform** store (read back
  directly via `database_engine`), and that row is invisible to a Sunshine Tenant
  Admin's `GET /api/audit`; a Florida admin's view shows none of the Sunshine
  actor's rows.
- **Test 4 — append-only holds (physical, DB-layer):** for both stores, an
  `UPDATE` and a `DELETE` raise `permission denied` under the tenant role and
  under `audit_writer` — a thin restatement of the Epic 5 physical proof.

`pytest.ini` sets `asyncio_mode = auto`, so the HTTP tests (1-3) carry no
`@pytest.mark.asyncio` decorator; the Test 4 substrate test that drives the
`database_engine` directly keeps it, matching `test_audit_append_only_acceptance.py`
and the other `database_engine` substrate modules. The `seeded` / `db_client`
fixtures and the `login_as` helper are reused by name from `test_endpoints_db.py`,
and `container_audit_session_factory` is requested explicitly on the HTTP tests
that trigger audit writes (the Epic 6/8/9/10 precedent).
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.audit.records import EventType
from app.config import settings
from app.models.user import Role
from app.tenancy.registry import AUDIT_WRITER_ROLE, TENANTS

from .test_endpoints_db import (  # noqa: F401 — `seeded` fixture is used by name
    login_as,
    seeded,
)

# The seeded Florida Tenant Admin, addressed by email directly: the `login_as`
# helper returns the *first* persona for a role, which is Sunshine (first in
# registry order), so Tests 1-3's tenant-vs-tenant face addresses Florida by name.
FLORIDA_ADMIN_USERNAME = "admin@florida.example"

# The sentinel record Test 1 creates and tracks through the HTTP surface. Its
# plaintext values are deliberately unique (a fresh uuid in the email) so any
# unmasked leak into the audit body would be unmistakable.
SENTINEL_EMAIL = f"audit-sentinel-{uuid.uuid4()}@example.com"
SENTINEL_RECORD_BODY = {
    "display_name": "Audit Sentinel",
    "email": SENTINEL_EMAIL,
    "date_of_birth": "1950-06-14",
    "phone": "+1 (305) 555-7777",
    "mock_medicare_id": "999-88-7777",
}

# The sentinel plaintext values that must never appear in the audit body — only
# the field *names* (`email`, `phone`, …) may.
SENTINEL_PLAINTEXT_VALUES = (
    SENTINEL_RECORD_BODY["email"],
    SENTINEL_RECORD_BODY["phone"],
    SENTINEL_RECORD_BODY["date_of_birth"],
    SENTINEL_RECORD_BODY["mock_medicare_id"],
)


async def _login_as_florida_admin(db_client):
    """Log in as the seeded Florida Tenant Admin; return the login response.

    `login_as(db_client, Role.TENANT_ADMIN)` resolves to Sunshine (the first
    persona in registry order), so the Florida admin is addressed by email
    directly — the same approach `test_audit_endpoint.py` uses for its
    tenant-vs-tenant isolation case.
    """
    return await db_client.post(
        "/api/auth/login",
        json={
            "username": FLORIDA_ADMIN_USERNAME,
            "password": settings.seed_user_password,
        },
    )


async def _read_platform_rows_for_actor(session_factory, actor_user_id):
    """Return `platform.audit_records` rows written by one actor, newest-first.

    Mirrors `test_platform_settings_endpoint.py::_read_platform_audit_rows_for_actor`:
    a plain ``SELECT … WHERE actor_user_id = :id ORDER BY occurred_at DESC``.
    Filtering by a per-test `actor_user_id` keeps each assertion attributable,
    because the session-scoped container DB is never reset between tests.
    """
    async with session_factory() as session:
        rows = await session.execute(
            text(
                "SELECT tenant_id, actor_user_id, actor_role, event_type, "
                "entity_type, entity_id, field_names, outcome "
                "FROM platform.audit_records WHERE actor_user_id = :actor_user_id "
                "ORDER BY occurred_at DESC"
            ),
            {"actor_user_id": actor_user_id},
        )
        return rows.all()


async def _denied(database_engine, role, statement):
    """Assert `statement` raises a "permission denied" error under `role`.

    Runs the attempt in its own transaction: the denial aborts it, and the
    `SET LOCAL ROLE` resets when the block rolls back on the raised error (the
    production `SET LOCAL` pattern). A thin restatement of
    `test_audit_append_only_acceptance.py::_denied`.
    """
    with pytest.raises(ProgrammingError) as denial:
        async with database_engine.begin() as connection:
            await connection.execute(text(f"SET LOCAL ROLE {role}"))
            await connection.execute(text(statement))

    message = str(denial.value).lower()
    assert "permission denied" in message, (
        f"expected {role} to be denied `{statement}`, got: {message}"
    )


# --- Test 1: every wired kind is audited, names-not-values -------------------


async def test_every_wired_kind_is_audited_names_not_values(
    seeded, db_client, container_audit_session_factory
):
    """ACCEPTANCE: each wired kind is recorded by name only, never by value.

    As the Agent (whose login already wrote `auth.login`), create one record with
    sentinel PII (writing `record.created`) and reveal its `email` (writing
    `pii.revealed` with `field_names=["email"]`). Then as the Tenant Admin,
    `GET /api/audit` returns rows of all three kinds; the `record.created` and
    `pii.revealed` rows carry the field *name* `"email"`; and none of the sentinel
    plaintext (email / phone / date of birth / Medicare id) appears anywhere in the
    serialized body — the whole-body scan idiom. This is the headline
    names-not-values proof, covering three of the five wired kinds end-to-end.
    """
    agent_login = await login_as(db_client, Role.AGENT)
    assert agent_login.status_code == 200

    create_response = await db_client.post(
        "/api/pii-demo/", json=SENTINEL_RECORD_BODY
    )
    assert create_response.status_code == 201
    created_id = create_response.json()["record"]["id"]

    reveal_response = await db_client.post(
        f"/api/pii-demo/{created_id}/reveal", json={"field": "email"}
    )
    assert reveal_response.status_code == 200
    assert reveal_response.json()["value"] == SENTINEL_EMAIL

    # The Tenant Admin reads the same tenant's audit log on the shared client.
    admin_login = await login_as(db_client, Role.TENANT_ADMIN)
    assert admin_login.status_code == 200

    response = await db_client.get("/api/audit")
    assert response.status_code == 200
    records = response.json()["records"]

    # All three wired kinds the Agent produced are present in this tenant's log.
    present_event_types = {record["event_type"] for record in records}
    assert EventType.AUTH_LOGIN in present_event_types
    assert EventType.RECORD_CREATED in present_event_types
    assert EventType.PII_REVEALED in present_event_types

    # The `record.created` row for the sentinel names the created fields.
    created_rows = [
        record
        for record in records
        if record["event_type"] == EventType.RECORD_CREATED
        and record["entity_id"] == created_id
    ]
    assert len(created_rows) == 1
    assert "email" in created_rows[0]["field_names"]

    # The `pii.revealed` row for the sentinel names the revealed field.
    revealed_rows = [
        record
        for record in records
        if record["event_type"] == EventType.PII_REVEALED
        and record["entity_id"] == created_id
    ]
    assert len(revealed_rows) == 1
    assert "email" in revealed_rows[0]["field_names"]

    # No sentinel plaintext value appears anywhere in the serialized body — only
    # the field *names* were recorded, never the values.
    for plaintext_value in SENTINEL_PLAINTEXT_VALUES:
        assert plaintext_value not in response.text


# --- Test 2: viewing audit is itself audited (`audit.viewed`) ----------------


async def test_viewing_audit_is_itself_audited(
    seeded, db_client, container_audit_session_factory
):
    """ACCEPTANCE: a second `GET /api/audit` sees the `audit.viewed` the first wrote.

    The first view reads the existing rows and then writes its own `audit.viewed`
    record before returning, so that record is **not** in the first response. The
    second view, reading after the first's self-audit committed, **does** see an
    `audit.viewed` record attributed to the caller — proving viewing the audit log
    is itself an audited operation (the fourth tenant-store wired kind). A thin
    restatement of `test_audit_endpoint.py::test_viewing_audit_is_itself_audited`.
    """
    login_response = await login_as(db_client, Role.TENANT_ADMIN)
    assert login_response.status_code == 200
    actor_user_id = login_response.json()["user"]["id"]

    first_response = await db_client.get("/api/audit")
    assert first_response.status_code == 200
    first_viewed_rows = [
        record
        for record in first_response.json()["records"]
        if record["event_type"] == EventType.AUDIT_VIEWED
        and record["actor_user_id"] == actor_user_id
    ]

    second_response = await db_client.get("/api/audit")
    assert second_response.status_code == 200
    second_viewed_rows = [
        record
        for record in second_response.json()["records"]
        if record["event_type"] == EventType.AUDIT_VIEWED
        and record["actor_user_id"] == actor_user_id
    ]

    # The second view sees at least one more of the caller's own `audit.viewed`
    # rows than the first — the first view's self-audit is now readable.
    assert len(second_viewed_rows) > len(first_viewed_rows)


# --- Test 3: tenant audit is tenant-only (platform store stays separate) ------


async def test_tenant_audit_is_tenant_only(
    seeded, db_client, database_engine, container_audit_session_factory
):
    """ACCEPTANCE: a tenant's audit log is tenant-only; the platform store is separate.

    A Platform Admin's `GET /api/platform/tenant-settings` writes one
    `platform.cross_tenant_read` row to the **platform** store (the fifth wired
    kind) — read back directly via `database_engine` (the Epic 6 idiom). That
    platform row is **invisible** to a Sunshine Tenant Admin's `GET /api/audit`
    (a tenant view never reaches the platform store), and a Florida admin's
    `GET /api/audit` shows **none** of the Sunshine actor's rows (tenant-vs-tenant
    isolation, the project's cross-cutting axis).
    """
    # The Platform Admin's cross-tenant read writes one `platform.cross_tenant_read`
    # row to the platform store.
    platform_login = await login_as(db_client, Role.PLATFORM_ADMIN)
    assert platform_login.status_code == 200
    platform_actor_user_id = uuid.UUID(platform_login.json()["user"]["id"])

    platform_read = await db_client.get("/api/platform/tenant-settings")
    assert platform_read.status_code == 200

    # That row is present in the platform store, attributed to the Platform Admin.
    platform_rows = await _read_platform_rows_for_actor(
        container_audit_session_factory, platform_actor_user_id
    )
    cross_read_rows = [
        row
        for row in platform_rows
        if row.event_type == EventType.PLATFORM_CROSS_TENANT_READ
    ]
    assert len(cross_read_rows) >= 1

    # A Sunshine Tenant Admin logs in (leaving its own rows in the Sunshine store)
    # and reads its tenant audit log — the platform `cross_tenant_read` row is
    # invisible here, and so is the Platform Admin actor.
    sunshine_login = await login_as(db_client, Role.TENANT_ADMIN)
    assert sunshine_login.status_code == 200
    sunshine_actor_user_id = sunshine_login.json()["user"]["id"]

    sunshine_view = await db_client.get("/api/audit")
    assert sunshine_view.status_code == 200
    sunshine_records = sunshine_view.json()["records"]

    # The platform cross-tenant-read kind never appears in a tenant view, and the
    # Platform Admin actor is attributed to none of the tenant rows.
    assert all(
        record["event_type"] != EventType.PLATFORM_CROSS_TENANT_READ
        for record in sunshine_records
    )
    assert all(
        record["actor_user_id"] != str(platform_actor_user_id)
        for record in sunshine_records
    )

    # Tenant-vs-tenant: a Florida admin's view shows none of the Sunshine actor's
    # rows — Sunshine's audit is physically out of reach of Florida's schema.
    florida_login = await _login_as_florida_admin(db_client)
    assert florida_login.status_code == 200
    florida_actor_user_id = florida_login.json()["user"]["id"]
    assert florida_actor_user_id != sunshine_actor_user_id

    florida_view = await db_client.get("/api/audit")
    assert florida_view.status_code == 200
    florida_records = florida_view.json()["records"]
    sunshine_attributed = [
        record
        for record in florida_records
        if record["actor_user_id"] == sunshine_actor_user_id
    ]
    assert sunshine_attributed == []


# --- Test 4: append-only holds (physical, DB-layer) --------------------------


@pytest.mark.asyncio
async def test_append_only_holds_for_every_store(database_engine):
    """ACCEPTANCE: every audit store is physically append-only — no UPDATE, no DELETE.

    For both stores (each tenant's `audit_records` plus `platform.audit_records`),
    an `UPDATE` and a `DELETE` raise "permission denied" under the tenant role and
    under `audit_writer` — the live proof that no role the app writes audit as can
    change or remove a record. A thin restatement of the Epic 5 physical proof in
    `test_audit_append_only_acceptance.py`, using identifiers from the registry
    only and the `database_engine.begin()`-per-attempt idiom.
    """
    audit_tables = [
        f"{tenant.schema_name}.audit_records" for tenant in TENANTS
    ] + ["platform.audit_records"]

    # `audit_writer` may append (Epic 5 proves the positive control) but never
    # mutate: every UPDATE / DELETE under it is denied, on every store.
    for qualified_table in audit_tables:
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

    # A tenant role is SELECT-only on its own audit: UPDATE / DELETE are denied.
    for tenant in TENANTS:
        qualified_table = f"{tenant.schema_name}.audit_records"
        await _denied(
            database_engine,
            tenant.db_role,
            f"UPDATE {qualified_table} SET outcome = 'tampered'",
        )
        await _denied(
            database_engine,
            tenant.db_role,
            f"DELETE FROM {qualified_table}",
        )
