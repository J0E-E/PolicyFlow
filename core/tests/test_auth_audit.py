"""DB-backed proof of the auth-event audit wiring (Epic 8, P1.4).

Drives the three auth paths over the real DB-backed client (the same `seeded` +
`db_client` substrate the other endpoint tests use), logging in as the actual
seeded personas, and reads the audit stores back directly to prove each path
leaves the right trail in the right store:

- **Login success routing:** a Tenant Admin login writes exactly one
  `auth.login` / `success` row to **that tenant's** store and **none** to the
  platform store; a Platform Admin login (tenantless) writes one to the
  **platform** store.
- **Login failure is PII-free:** a wrong-password login writes one
  `auth.login` / `failure` row to the **platform** store with `actor_user_id`
  NULL and the attempted username present in **no** field of the row.
- **Logout is attributed:** a login then logout writes exactly one
  `auth.logout` / `success` row attributed to that actor; a logout with no
  session cookie writes **no** audit row.

This mirrors `test_reveal_seam.py` / `test_platform_settings_endpoint.py`'s
`test_platform_read_is_audited`: a per-actor read-back with a before/after delta
rather than a global `== 1` count, because the session-scoped container DB is
never reset between tests, so rows accumulate. `pytest.ini` sets
`asyncio_mode = auto`, so these async tests carry no `@pytest.mark.asyncio`
decorator. The `seeded` / `db_client` fixtures and the `login_as` helper are
reused by name from `test_endpoints_db.py`, the Epic 6 precedent.
"""

import uuid

from sqlalchemy import text

from app.audit.records import EventType, Outcome
from app.models.user import Role
from app.tenancy.registry import SUNSHINE

from .test_endpoints_db import (  # noqa: F401 — `seeded` fixture is used by name
    email_for_role,
    login_as,
    seeded,
)


async def _read_audit_rows_for_actor(session_factory, qualified_table, actor_user_id):
    """Return one audit table's rows written by a single actor, newest-first.

    Mirrors `test_reveal_seam.py::_read_rows_for_actor`: a plain
    ``SELECT … WHERE actor_user_id = :id ORDER BY occurred_at DESC`` against a
    schema-qualified audit table. Filtering by a per-test `actor_user_id` (rather
    than counting the whole table) keeps each assertion attributable, because the
    session-scoped container DB is never reset between tests.
    """
    async with session_factory() as session:
        rows = await session.execute(
            text(
                "SELECT tenant_id, actor_user_id, actor_role, event_type, "
                "entity_type, entity_id, field_names, outcome "
                f"FROM {qualified_table} WHERE actor_user_id = :actor_user_id "
                "ORDER BY occurred_at DESC"
            ),
            {"actor_user_id": actor_user_id},
        )
        return rows.all()


async def _read_all_platform_failure_rows(session_factory):
    """Return every `auth.login` / `failure` row in the platform store as raw dicts.

    Used by the PII-free proof: failures carry no `actor_user_id`, so they cannot
    be filtered per-actor. The whole row is read as a mapping so the test can scan
    **every** column's value for the attempted username — the assertion is that it
    appears nowhere. A freshly-generated, never-seeded username keeps this
    unambiguous against the accumulating container DB.
    """
    async with session_factory() as session:
        rows = await session.execute(
            text(
                "SELECT * FROM platform.audit_records "
                "WHERE event_type = :event_type AND outcome = :outcome"
            ),
            {
                "event_type": str(EventType.AUTH_LOGIN),
                "outcome": str(Outcome.FAILURE),
            },
        )
        return [dict(row) for row in rows.mappings().all()]


async def _count_login_success_rows(session_factory, qualified_table):
    """Count `auth.login`/`success` rows in one audit store (for before/after deltas).

    The shared seeded personas log in across many tests against the session-scoped
    container DB, which is never reset, so a global `== 1` count of a persona's rows
    is order-dependent. A login-success delta on the store proves *this* login wrote
    exactly one row — the same before/after-delta idiom
    `test_wrong_password_login_audits_pii_free_to_platform` uses for the failure
    store. Counting under serial test execution is exact: only this test's login can
    add an `auth.login`/`success` row between the two snapshots.
    """
    async with session_factory() as session:
        total = await session.execute(
            text(
                f"SELECT count(*) FROM {qualified_table} "
                "WHERE event_type = :event_type AND outcome = :outcome"
            ),
            {
                "event_type": str(EventType.AUTH_LOGIN),
                "outcome": str(Outcome.SUCCESS),
            },
        )
        return total.scalar_one()


# --- Login success: store routing -------------------------------------------


async def test_tenant_admin_login_audits_to_their_tenant_store(
    seeded, db_client, container_audit_session_factory
):
    """A Tenant Admin login writes one `auth.login`/`success` to their tenant store.

    The row lands in the Sunshine tenant's own schema attributed to that actor, and
    nothing for that actor reaches the platform store — a tenant login is
    tenant-scoped (the project's cross-cutting axis). A before/after delta proves
    *this* login wrote exactly one row: the shared seeded Tenant Admin persona logs
    in across many tests against the never-reset container DB, so a global `== 1`
    count of the actor's rows would be order-dependent.
    """
    tenant_table = f"{SUNSHINE.schema_name}.audit_records"
    logins_before = await _count_login_success_rows(
        container_audit_session_factory, tenant_table
    )

    login_response = await login_as(db_client, Role.TENANT_ADMIN)
    assert login_response.status_code == 200
    actor_user_id = uuid.UUID(login_response.json()["user"]["id"])

    logins_after = await _count_login_success_rows(
        container_audit_session_factory, tenant_table
    )
    assert logins_after == logins_before + 1

    # The just-written login is attributed to this actor. Every `auth.login` row
    # this persona writes is identical in the asserted fields, so inspecting the
    # newest of the actor's login rows is order-independent.
    tenant_rows = await _read_audit_rows_for_actor(
        container_audit_session_factory, tenant_table, actor_user_id
    )
    login_rows = [
        row for row in tenant_rows if row.event_type == EventType.AUTH_LOGIN
    ]
    assert login_rows
    written = login_rows[0]
    assert written.actor_user_id == actor_user_id
    assert written.actor_role == Role.TENANT_ADMIN
    assert written.event_type == EventType.AUTH_LOGIN
    assert written.outcome == Outcome.SUCCESS
    assert written.tenant_id is not None

    # That same actor wrote nothing to the platform store — a tenant login routes
    # only to the tenant's own schema (tenant isolation).
    platform_rows = await _read_audit_rows_for_actor(
        container_audit_session_factory, "platform.audit_records", actor_user_id
    )
    assert platform_rows == []


async def test_platform_admin_login_audits_to_the_platform_store(
    seeded, db_client, container_audit_session_factory
):
    """A Platform Admin login writes one `auth.login`/`success` to the platform store.

    The seeded Platform Admin is tenantless (`tenant_id=None`), so the service's one
    routing rule lands its login record in the shared platform store with a NULL
    `tenant_id`. A before/after delta proves *this* login wrote exactly one row: the
    shared persona logs in across many tests against the never-reset container DB, so
    a global `== 1` count of the actor's rows would be order-dependent.
    """
    logins_before = await _count_login_success_rows(
        container_audit_session_factory, "platform.audit_records"
    )

    login_response = await login_as(db_client, Role.PLATFORM_ADMIN)
    assert login_response.status_code == 200
    actor_user_id = uuid.UUID(login_response.json()["user"]["id"])

    logins_after = await _count_login_success_rows(
        container_audit_session_factory, "platform.audit_records"
    )
    assert logins_after == logins_before + 1

    platform_rows = await _read_audit_rows_for_actor(
        container_audit_session_factory, "platform.audit_records", actor_user_id
    )
    login_rows = [
        row for row in platform_rows if row.event_type == EventType.AUTH_LOGIN
    ]
    assert login_rows
    written = login_rows[0]
    assert written.tenant_id is None
    assert written.actor_user_id == actor_user_id
    assert written.actor_role == Role.PLATFORM_ADMIN
    assert written.event_type == EventType.AUTH_LOGIN
    assert written.outcome == Outcome.SUCCESS


# --- Login failure: PII-free in the platform store --------------------------


async def test_wrong_password_login_audits_pii_free_to_platform(
    seeded, db_client, container_audit_session_factory
):
    """A wrong-password login writes a PII-free `auth.login`/`failure` to platform.

    Snapshots the platform failure rows before and after, asserts the count rose by
    exactly one (a before/after delta, not a global count — the container DB is
    never reset between tests), and that the new row carries no identifying PII: the
    attempted username appears in no column, and `actor_user_id` is NULL.
    """
    # A freshly-generated username that was never seeded, so finding it in any
    # column would unambiguously mean the failure path leaked it.
    attempted_username = f"never-seeded-{uuid.uuid4()}@policyflow.example"

    rows_before = await _read_all_platform_failure_rows(
        container_audit_session_factory
    )

    response = await db_client.post(
        "/api/auth/login",
        json={"username": attempted_username, "password": "the wrong password"},
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid credentials"}

    rows_after = await _read_all_platform_failure_rows(
        container_audit_session_factory
    )

    # Exactly one new platform failure row was written by this attempt.
    assert len(rows_after) == len(rows_before) + 1

    # The attempted username appears in no column of any failure row — the failure
    # path deliberately carries no PII (no username, user id, or role).
    for row in rows_after:
        for value in row.values():
            assert attempted_username not in str(value)
        assert row["actor_user_id"] is None
        assert row["actor_role"] is None
        assert row["tenant_id"] is None


# --- Logout: attributed; no-session logout is silent ------------------------


async def test_logout_audits_attributed_to_the_actor(
    seeded, db_client, container_audit_session_factory
):
    """A login then logout writes one `auth.logout`/`success` attributed to the actor.

    The Tenant Admin's logout record lands in their tenant store, resolved from the
    session before the token was revoked, attributed to that same actor. A
    before/after delta on the actor's logout rows proves *this* logout wrote exactly
    one row: the shared seeded Tenant Admin persona is logged out across many tests
    (`test_endpoints_db`, the assume-persona role switch) against the never-reset
    session-scoped container DB, so a global `== 1` count of the actor's logout rows
    would be order-dependent. Counting under serial test execution is exact — only
    this test's logout can add an `auth.logout` row between the two snapshots. This
    mirrors the before/after-delta idiom the login-success cases above already use.
    """
    tenant_table = f"{SUNSHINE.schema_name}.audit_records"

    login_response = await login_as(db_client, Role.TENANT_ADMIN)
    assert login_response.status_code == 200
    actor_user_id = uuid.UUID(login_response.json()["user"]["id"])

    rows_before = await _read_audit_rows_for_actor(
        container_audit_session_factory, tenant_table, actor_user_id
    )
    logouts_before = [
        row for row in rows_before if row.event_type == EventType.AUTH_LOGOUT
    ]

    logout_response = await db_client.post("/api/auth/logout")
    assert logout_response.status_code == 200

    rows_after = await _read_audit_rows_for_actor(
        container_audit_session_factory, tenant_table, actor_user_id
    )
    logout_rows = [
        row for row in rows_after if row.event_type == EventType.AUTH_LOGOUT
    ]

    # Exactly one new logout row was written by this logout (a before/after delta,
    # not a global `== 1` count — the container DB is never reset between tests).
    assert len(logout_rows) == len(logouts_before) + 1

    # `_read_audit_rows_for_actor` returns rows newest-first, so the actor's most
    # recent logout row is the one this test just wrote; every logout row this
    # persona writes is identical in the asserted fields, so inspecting the newest
    # is order-independent.
    written = logout_rows[0]
    assert written.actor_user_id == actor_user_id
    assert written.actor_role == Role.TENANT_ADMIN
    assert written.outcome == Outcome.SUCCESS
    assert written.tenant_id is not None


async def test_no_session_logout_writes_no_audit_row(
    seeded, db_client, container_audit_session_factory
):
    """A logout with no session cookie writes no audit row anywhere.

    A fresh client never logs in, so there is no session to resolve; the logout
    returns 200 but emits nothing — a no-session logout is not an audit event.
    Proven by snapshotting both stores' total logout rows before and after and
    asserting no change (no actor id exists to filter on).
    """

    async def count_logout_rows(qualified_table):
        async with container_audit_session_factory() as session:
            total = await session.execute(
                text(
                    f"SELECT count(*) FROM {qualified_table} "
                    "WHERE event_type = :event_type"
                ),
                {"event_type": str(EventType.AUTH_LOGOUT)},
            )
            return total.scalar_one()

    platform_before = await count_logout_rows("platform.audit_records")
    tenant_before = await count_logout_rows(f"{SUNSHINE.schema_name}.audit_records")

    response = await db_client.post("/api/auth/logout")
    assert response.status_code == 200
    assert response.json() == {"detail": "logged out"}

    platform_after = await count_logout_rows("platform.audit_records")
    tenant_after = await count_logout_rows(f"{SUNSHINE.schema_name}.audit_records")

    assert platform_after == platform_before
    assert tenant_after == tenant_before
