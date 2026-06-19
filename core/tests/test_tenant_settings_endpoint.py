"""End-to-end endpoint proof for Epic 6 — `GET /api/tenant/settings`.

Drives the route over the real DB-backed client (the same `seeded` + `db_client`
substrate `test_endpoints_db.py` uses), logging in as the actual seeded personas.
Together these prove the isolation guarantee the epic promises end-to-end over
HTTP:

- **Happy path (Phase 1):** a logged-in tenant user reads their own settings row
  → 200, body carrying that tenant's seeded values and matching `tenant_id`.
- **Cross-tenant isolation (Phase 2):** a Sunshine user sees only Sunshine's
  values and a Florida user only Florida's — the values never cross, because the
  endpoint takes no tenant parameter and `get_tenant_db` scopes each caller to
  their own schema.
- **Tenantless guard (Phase 2):** a Platform Admin (`tenant_id is None`) →
  `400 {"detail": "no tenant context"}`, inherited from `get_tenant_db`.

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no
`@pytest.mark.asyncio` decorator. The `seeded`/`db_client` fixtures and the
`login_as`/`email_for_role`/`tenant_slug_for_role` helpers are reused from
`test_endpoints_db.py`.
"""

from app.config import settings
from app.models.user import Role
from app.seed import DEMO_TENANT_SETTINGS, demo_user_specs
from app.tenancy.registry import tenant_by_slug

from .test_endpoints_db import (  # noqa: F401 — `seeded` fixture is used by name
    login_as,
    seeded,
    tenant_slug_for_role,
)


def expected_settings_for_slug(slug: str) -> dict[str, str]:
    """Return the seeded settings a tenant should read back, by tenant slug.

    Mirrors how `seed.py` builds each tenant's row: the brand colour comes from
    the registry (`TenantConfig.brand_primary_color`, the single source of
    truth), the welcome message from `DEMO_TENANT_SETTINGS`, and the logo URL is
    the same per-tenant placeholder built from the registry schema name.
    """
    config = tenant_by_slug(slug)
    return {
        "brand_primary_color": config.brand_primary_color,
        "brand_logo_url": (
            f"https://assets.policyflow.example/{config.schema_name}/logo.svg"
        ),
        "welcome_message": DEMO_TENANT_SETTINGS[slug]["welcome_message"],
    }


def slugs_with_a_tenant_user() -> list[str]:
    """Return each distinct tenant slug that has at least one seeded persona."""
    seen: list[str] = []
    for _email, _role, slug in demo_user_specs():
        if slug is not None and slug not in seen:
            seen.append(slug)
    return seen


# --- Phase 1: happy path -----------------------------------------------------


async def test_tenant_settings_returns_callers_own_row(seeded, db_client):
    """A logged-in tenant user reads their own settings row → 200 with its values."""
    assert (await login_as(db_client, Role.TENANT_ADMIN)).status_code == 200

    response = await db_client.get("/api/tenant/settings")

    assert response.status_code == 200
    tenant_settings = response.json()["settings"]
    assert set(tenant_settings) == {
        "tenant_id",
        "brand_primary_color",
        "brand_logo_url",
        "welcome_message",
    }

    slug = tenant_slug_for_role(Role.TENANT_ADMIN)
    expected = expected_settings_for_slug(slug)
    assert tenant_settings["brand_primary_color"] == expected["brand_primary_color"]
    assert tenant_settings["brand_logo_url"] == expected["brand_logo_url"]
    assert tenant_settings["welcome_message"] == expected["welcome_message"]
    assert tenant_settings["tenant_id"]


# --- Phase 2: cross-tenant isolation -----------------------------------------


async def test_each_tenant_user_sees_only_their_own_settings(seeded, db_client):
    """Each tenant's user reads only their own tenant's values, never crossing.

    Logs in as a persona from each tenant in turn (resolved per-tenant via
    `demo_user_specs()`'s slug) and asserts the response carries that tenant's own
    seeded welcome message — proving the no-parameter endpoint scopes every caller
    to their own schema. The two tenants' `tenant_id`s and welcome messages are
    also asserted distinct, so a leak between them would fail loudly.
    """
    seen_tenant_ids: set[str] = set()
    seen_welcome_messages: set[str] = set()

    slugs = slugs_with_a_tenant_user()
    assert len(slugs) >= 2, "need at least two tenants to prove non-crossing"

    for slug in slugs:
        email = next(
            spec_email
            for spec_email, _role, spec_slug in demo_user_specs()
            if spec_slug == slug
        )
        login_response = await db_client.post(
            "/api/auth/login",
            json={"username": email, "password": settings.seed_user_password},
        )
        assert login_response.status_code == 200

        response = await db_client.get("/api/tenant/settings")
        assert response.status_code == 200
        tenant_settings = response.json()["settings"]

        expected = expected_settings_for_slug(slug)
        assert tenant_settings["welcome_message"] == expected["welcome_message"]
        assert (
            tenant_settings["brand_primary_color"]
            == expected["brand_primary_color"]
        )

        seen_tenant_ids.add(tenant_settings["tenant_id"])
        seen_welcome_messages.add(tenant_settings["welcome_message"])

        # Log out so the next persona starts from a clean session.
        await db_client.post("/api/auth/logout")

    # No two tenants returned the same identity or welcome message — values never
    # crossed between schemas.
    assert len(seen_tenant_ids) == len(slugs)
    assert len(seen_welcome_messages) == len(slugs)


# --- Phase 2: tenantless guard -----------------------------------------------


async def test_tenant_settings_tenantless_caller_is_400(seeded, db_client):
    """A Platform Admin (no tenant_id) → 400 'no tenant context', from get_tenant_db."""
    assert (await login_as(db_client, Role.PLATFORM_ADMIN)).status_code == 200

    response = await db_client.get("/api/tenant/settings")

    assert response.status_code == 400
    assert response.json() == {"detail": "no tenant context"}


async def test_tenant_settings_unauthenticated_is_401(seeded, db_client):
    """A fresh client with no session cookie → 401, inherited from require_authenticated."""
    response = await db_client.get("/api/tenant/settings")

    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}
