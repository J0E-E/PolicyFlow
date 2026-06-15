"""End-to-end endpoint proof for Epic 7 — `GET /api/platform/tenant-settings`.

Drives the platform carve-out over the real DB-backed client (the same `seeded` +
`db_client` substrate the other endpoint tests use), logging in as the actual
seeded personas. Together these prove the carve-out's guarantees end-to-end over
HTTP:

- **Happy path (Phase 1):** a logged-in **Platform Admin** lists every tenant's
  settings → 200, body carrying **both** seeded tenants, each item with the four
  settings fields plus its registry `slug`, matching that tenant's seeded values.
  This success path also drives the now-filled audit seam
  `record_platform_read_for_audit`, which writes exactly one
  `platform.cross_tenant_read` record to the platform store — proven by
  `test_platform_read_is_audited`.
- **Rejection (Phase 2):** every non-platform role (Tenant Admin, Agent,
  Read-Only) → `403 {"detail": "insufficient permissions"}` — also the "a tenant
  role cannot reach this path" proof — and an unauthenticated caller →
  `401 {"detail": "not authenticated"}`, both inherited from
  `require_platform_admin`.

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no
`@pytest.mark.asyncio` decorator. The `seeded`/`db_client` fixtures and the
`login_as` helper are reused from `test_endpoints_db.py`, and
`expected_settings_for_slug` from the Epic-6 `test_tenant_settings_endpoint.py`.
"""

import uuid

import pytest
from sqlalchemy import text

from app.audit.records import EventType, Outcome
from app.models.user import Role
from app.tenancy.registry import TENANTS

from .test_endpoints_db import (  # noqa: F401 — `seeded` fixture is used by name
    login_as,
    seeded,
)
from .test_tenant_settings_endpoint import expected_settings_for_slug


async def _read_platform_audit_rows_for_actor(session_factory, actor_user_id):
    """Return `platform.audit_records` rows written by one actor, newest-first.

    Mirrors `test_audit_service.py::_read_rows_for_actor`: a plain
    ``SELECT … WHERE actor_user_id = :id ORDER BY occurred_at DESC``. The
    session-scoped container DB is never reset between tests, so filtering by a
    single actor keeps each assertion attributable to its own test.
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


# --- Phase 1: happy path -----------------------------------------------------


async def test_platform_admin_lists_every_tenants_settings(seeded, db_client):
    """A Platform Admin reads every tenant's settings → 200 with all tenants' values.

    The seam this success path drives now writes one `platform.cross_tenant_read`
    record to the platform store (no longer a no-op); that audit write is proven
    separately by `test_platform_read_is_audited`.
    """
    assert (await login_as(db_client, Role.PLATFORM_ADMIN)).status_code == 200

    response = await db_client.get("/api/platform/tenant-settings")

    assert response.status_code == 200
    tenants = response.json()["tenants"]

    # Every registered tenant appears exactly once, keyed by its registry slug.
    returned_by_slug = {item["slug"]: item for item in tenants}
    expected_slugs = {tenant.slug for tenant in TENANTS}
    assert set(returned_by_slug) == expected_slugs
    assert len(tenants) == len(expected_slugs)

    for slug, item in returned_by_slug.items():
        assert set(item) == {
            "tenant_id",
            "brand_primary_color",
            "brand_logo_url",
            "welcome_message",
            "slug",
        }
        expected = expected_settings_for_slug(slug)
        assert item["brand_primary_color"] == expected["brand_primary_color"]
        assert item["brand_logo_url"] == expected["brand_logo_url"]
        assert item["welcome_message"] == expected["welcome_message"]
        assert item["tenant_id"]


async def test_platform_read_is_audited(
    seeded, db_client, container_audit_session_factory
):
    """A successful cross-tenant read writes exactly one platform audit record.

    Logs in as the Platform Admin, captures that actor's `user_id` from the login
    body, snapshots `platform.audit_records` for that actor before and after the
    read, and asserts the count rose by exactly one (a before/after delta, not a
    global `== 1` — the session-scoped container DB is never reset between tests).
    Then inspects the newest row to lock down what the filled seam writes.
    """
    login_response = await login_as(db_client, Role.PLATFORM_ADMIN)
    assert login_response.status_code == 200
    actor_user_id = uuid.UUID(login_response.json()["user"]["id"])

    rows_before = await _read_platform_audit_rows_for_actor(
        container_audit_session_factory, actor_user_id
    )

    response = await db_client.get("/api/platform/tenant-settings")
    assert response.status_code == 200

    rows_after = await _read_platform_audit_rows_for_actor(
        container_audit_session_factory, actor_user_id
    )

    # Exactly one new record was written by this read.
    assert len(rows_after) == len(rows_before) + 1

    # The newest row is the one this read wrote — inspect its fields.
    written = rows_after[0]
    assert written.tenant_id is None
    assert written.event_type == EventType.PLATFORM_CROSS_TENANT_READ
    assert written.actor_role == Role.PLATFORM_ADMIN
    assert written.entity_type == "tenant_settings"
    assert written.outcome == Outcome.SUCCESS
    assert not written.field_names


# --- Phase 2: rejection & boundary proofs ------------------------------------


@pytest.mark.parametrize(
    "role",
    [Role.TENANT_ADMIN, Role.AGENT, Role.READ_ONLY],
)
async def test_non_platform_roles_are_rejected(seeded, db_client, role):
    """Every non-platform role → 403 — a tenant role cannot reach the carve-out."""
    assert (await login_as(db_client, role)).status_code == 200

    response = await db_client.get("/api/platform/tenant-settings")

    assert response.status_code == 403
    assert response.json() == {"detail": "insufficient permissions"}


async def test_platform_settings_unauthenticated_is_401(seeded, db_client):
    """A fresh client with no session cookie → 401, from require_authenticated."""
    response = await db_client.get("/api/platform/tenant-settings")

    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}
