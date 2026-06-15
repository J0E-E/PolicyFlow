"""Endpoint tests for the guarded, self-auditing audit-read route (Epic 10, P1.4).

Drives `GET /api/audit` over the real DB-backed client (the same `seeded` +
`db_client` substrate the other endpoint tests use), logging in as the actual
seeded personas, and proves the read side of the audit spine:

- **Happy path:** a Tenant Admin (whose login already wrote an `auth.login` row)
  `GET /api/audit` → 200, the `records` list contains that login row, every record
  carries the expected names/metadata keys, and no record exposes an encrypted or
  value-bearing key.
- **RBAC matrix:** Read-Only → 200; Agent → 403; anonymous → 401; Platform Admin →
  403 (lacks `VIEW_AUDIT_LOGS`, so the capability gate fires before
  `get_tenant_db`'s tenantless 400 — proving the capability-first ordering).
- **Tenant A-vs-B isolation:** a Sunshine login leaves a row, but a Florida admin's
  `GET /api/audit` returns Florida's rows only — the Sunshine actor appears in no
  Florida record (the endpoint inherits the Epic 5 physical isolation).
- **No unmasked PII:** an Agent reveals a field (writing a `pii.revealed` row with
  `field_names=["email"]`); a Tenant Admin's `GET /api/audit` shows that record's
  field *names* but the revealed plaintext appears nowhere in the serialized body.
- **Viewing is itself audited:** two successive views; the second response contains
  an `audit.viewed` record attributed to the caller that the first did not — the
  self-audit is written before the response and is itself readable.

This mirrors `test_auth_audit.py` / `test_record_change_audit.py`: per-actor or
per-content reads against the never-reset container DB rather than global counts.
`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no
`@pytest.mark.asyncio` decorator. The `seeded` / `db_client` fixtures and the
`login_as` helper are reused by name from `test_endpoints_db.py`, the Epic 6/8/9
precedent; `container_audit_session_factory` is requested explicitly (the self-audit
write needs the container-pointed global) as the sibling audit tests do.
"""

import uuid

from app.config import settings
from app.models.user import Role

from .test_endpoints_db import (  # noqa: F401 — `seeded` fixture is used by name
    login_as,
    seeded,
)

# The keys/names a well-formed audit record carries — the read shape the response
# builder defines. Asserted as an exact set so a record can neither drop a key nor
# grow a new one without this test noticing.
EXPECTED_RECORD_KEYS = {
    "id",
    "occurred_at",
    "tenant_id",
    "actor_user_id",
    "actor_role",
    "event_type",
    "entity_type",
    "entity_id",
    "field_names",
    "outcome",
}


def _record_exposes_no_value_key(record: dict) -> bool:
    """Return whether a record carries no encrypted/value-bearing key.

    The audit response is names-and-metadata only by construction. This guards the
    contract directly: no key may contain `encrypted` or be the bare `value`, the
    two shapes a leaked plaintext column would take.
    """
    return all(
        "encrypted" not in key and key != "value" for key in record
    )


# --- Phase 1: the happy path -------------------------------------------------


async def test_tenant_admin_can_read_audit_records(
    seeded, db_client, container_audit_session_factory
):
    """A Tenant Admin reads their tenant audit log → 200 with their own login row.

    Logging in itself writes an `auth.login` row to the Tenant Admin's tenant store,
    so the very first `GET /api/audit` already has at least that row to return. Every
    returned record carries exactly the expected names/metadata keys and exposes no
    encrypted or value-bearing key — names only, by construction.
    """
    login_response = await login_as(db_client, Role.TENANT_ADMIN)
    assert login_response.status_code == 200
    actor_user_id = login_response.json()["user"]["id"]

    response = await db_client.get("/api/audit")
    assert response.status_code == 200

    records = response.json()["records"]
    assert isinstance(records, list)

    # Every record has exactly the read-shape keys and leaks no value column.
    for record in records:
        assert set(record) == EXPECTED_RECORD_KEYS
        assert _record_exposes_no_value_key(record)

    # The caller's own `auth.login` row (written by the login above) is present.
    login_rows = [
        record
        for record in records
        if record["event_type"] == "auth.login"
        and record["actor_user_id"] == actor_user_id
    ]
    assert len(login_rows) >= 1
    assert login_rows[0]["outcome"] == "success"


# --- Phase 2: the RBAC matrix ------------------------------------------------


async def test_read_only_can_read_audit_records(
    seeded, db_client, container_audit_session_factory
):
    """A Read-Only user holds `VIEW_AUDIT_LOGS` → 200 with a records list."""
    assert (await login_as(db_client, Role.READ_ONLY)).status_code == 200

    response = await db_client.get("/api/audit")

    assert response.status_code == 200
    assert isinstance(response.json()["records"], list)


async def test_agent_cannot_read_audit_records(
    seeded, db_client, container_audit_session_factory
):
    """An Agent lacks `VIEW_AUDIT_LOGS` → 403."""
    assert (await login_as(db_client, Role.AGENT)).status_code == 200

    response = await db_client.get("/api/audit")

    assert response.status_code == 403
    assert response.json() == {"detail": "insufficient permissions"}


async def test_unauthenticated_cannot_read_audit_records(seeded, db_client):
    """A fresh client with no session cookie → 401."""
    response = await db_client.get("/api/audit")

    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}


async def test_platform_admin_cannot_read_audit_records(
    seeded, db_client, container_audit_session_factory
):
    """A Platform Admin lacks `VIEW_AUDIT_LOGS` → 403, not the tenantless 400.

    The tenantless Platform Admin would hit `get_tenant_db`'s 400 if the tenant
    session were resolved first. Because the capability gate runs **before**
    `get_tenant_db`, the missing `VIEW_AUDIT_LOGS` capability is caught first and
    the caller gets a 403 — the load-bearing dependency ordering. A regression to
    400 here would mean the ordering was reversed.
    """
    assert (await login_as(db_client, Role.PLATFORM_ADMIN)).status_code == 200

    response = await db_client.get("/api/audit")

    assert response.status_code == 403
    assert response.json() == {"detail": "insufficient permissions"}


# --- Phase 2: tenant A-vs-B isolation ----------------------------------------


async def test_audit_read_is_tenant_isolated(
    seeded, db_client, container_audit_session_factory
):
    """A Florida admin's audit read returns Florida's rows only, never Sunshine's.

    A Sunshine admin logs in (leaving an identifiable `auth.login` row attributed to
    the Sunshine actor in the Sunshine store), then a Florida admin logs in on a
    fresh client and reads `GET /api/audit`. The Sunshine actor's id appears in no
    Florida record — the endpoint inherits the Epic 5 physical cross-tenant denial
    via `get_tenant_db`'s `search_path` scoping (the project's cross-cutting axis).
    """
    sunshine_login = await login_as(db_client, Role.TENANT_ADMIN)
    assert sunshine_login.status_code == 200
    sunshine_actor_user_id = sunshine_login.json()["user"]["id"]

    # A fresh client for the Florida admin so no Sunshine session cookie carries
    # over. The seeded Tenant Admin persona is Sunshine (the first per the registry
    # order), so the Florida admin is addressed by email directly.
    florida_login = await db_client.post(
        "/api/auth/login",
        json={
            "username": "admin@florida.example",
            "password": settings.seed_user_password,
        },
    )
    assert florida_login.status_code == 200
    florida_actor_user_id = florida_login.json()["user"]["id"]
    assert florida_actor_user_id != sunshine_actor_user_id

    response = await db_client.get("/api/audit")
    assert response.status_code == 200
    records = response.json()["records"]

    # No record in the Florida admin's view is attributed to the Sunshine actor —
    # Sunshine's rows are physically out of reach of Florida's schema.
    sunshine_attributed = [
        record
        for record in records
        if record["actor_user_id"] == sunshine_actor_user_id
    ]
    assert sunshine_attributed == []

    # The Florida admin's own login row is present, confirming the view is the
    # Florida store, not an empty result.
    florida_login_rows = [
        record
        for record in records
        if record["event_type"] == "auth.login"
        and record["actor_user_id"] == florida_actor_user_id
    ]
    assert len(florida_login_rows) >= 1


# --- Phase 2: no unmasked PII in the response --------------------------------


async def test_audit_read_exposes_no_unmasked_pii(
    seeded, db_client, container_audit_session_factory
):
    """A revealed field shows its name in the audit log, never its value.

    An Agent creates a record with a unique email and reveals that `email` field —
    writing a `pii.revealed` row carrying `field_names=["email"]` (the field name,
    never the value). A Tenant Admin then reads `GET /api/audit` and sees a
    `pii.revealed` record whose `field_names` contains `"email"`, while the unique
    revealed plaintext appears **nowhere** in the entire serialized response body —
    the audit trail records names, not values (the cross-cutting PII axis).
    """
    # A unique email so finding it anywhere in the audit body would unambiguously
    # mean the revealed value leaked into the trail.
    revealed_email = f"reveal-{uuid.uuid4()}@example.com"

    assert (await login_as(db_client, Role.AGENT)).status_code == 200
    create_response = await db_client.post(
        "/api/pii-demo/",
        json={
            "display_name": "Reveal Subject",
            "email": revealed_email,
            "date_of_birth": "1950-03-15",
        },
    )
    assert create_response.status_code == 201
    created_id = create_response.json()["record"]["id"]

    reveal_response = await db_client.post(
        f"/api/pii-demo/{created_id}/reveal",
        json={"field": "email"},
    )
    assert reveal_response.status_code == 200
    assert reveal_response.json()["value"] == revealed_email

    # The Tenant Admin reads the same tenant's audit log on a fresh client.
    admin_login = await login_as(db_client, Role.TENANT_ADMIN)
    assert admin_login.status_code == 200

    response = await db_client.get("/api/audit")
    assert response.status_code == 200
    body = response.json()

    # A `pii.revealed` record for the created entity is present, naming `email`.
    revealed_rows = [
        record
        for record in body["records"]
        if record["event_type"] == "pii.revealed"
        and record["entity_id"] == created_id
    ]
    assert len(revealed_rows) == 1
    assert "email" in revealed_rows[0]["field_names"]

    # The revealed plaintext appears nowhere in the whole serialized body — the
    # whole-body scan idiom: only the field *name* is recorded, never the value.
    assert revealed_email not in response.text


# --- Phase 2: viewing is itself audited (a second view sees the first) -------


async def test_viewing_audit_is_itself_audited(
    seeded, db_client, container_audit_session_factory
):
    """A second `GET /api/audit` sees the `audit.viewed` row the first one wrote.

    The first view reads the existing rows and then writes its own `audit.viewed`
    record before returning, so that record is **not** in the first response. The
    second view, reading after the first's self-audit committed, **does** see an
    `audit.viewed` record attributed to the caller — proving the self-audit is
    written before the response and is itself readable (the requirement that viewing
    audit is an audited operation).
    """
    login_response = await login_as(db_client, Role.TENANT_ADMIN)
    assert login_response.status_code == 200
    actor_user_id = login_response.json()["user"]["id"]

    first_response = await db_client.get("/api/audit")
    assert first_response.status_code == 200
    first_viewed_rows = [
        record
        for record in first_response.json()["records"]
        if record["event_type"] == "audit.viewed"
        and record["actor_user_id"] == actor_user_id
    ]

    second_response = await db_client.get("/api/audit")
    assert second_response.status_code == 200
    second_viewed_rows = [
        record
        for record in second_response.json()["records"]
        if record["event_type"] == "audit.viewed"
        and record["actor_user_id"] == actor_user_id
    ]

    # The second view sees at least one more of the caller's own `audit.viewed`
    # rows than the first — the first view's self-audit is now readable.
    assert len(second_viewed_rows) > len(first_viewed_rows)
    newest = second_viewed_rows[0]
    assert newest["outcome"] == "success"
    assert newest["entity_type"] == "audit_records"
    assert newest["tenant_id"] is not None
