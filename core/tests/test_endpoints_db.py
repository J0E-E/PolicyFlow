"""End-to-end endpoint enforcement tests over the real DB-backed client (Epic 13).

Locks down the HTTP contract of the auth and tenant routers by driving them as
the actual seeded personas a user would log in as. Each test seeds the real demo
data (`app.seed.seed`), logs in over `POST /api/auth/login` with
`settings.seed_user_password`, and asserts the per-role status codes and response
bodies end-to-end: login success/failure, `/api/auth/me` authenticated /
unauthenticated / after-logout, and the `GET /api/tenant/config` role matrix
(Tenant Admin 200, every other role 403, anonymous 401).

These tests use the real personas, not the `insert_active_user` factory — proving
the seeded users are signable-in today. `pytest.ini` sets `asyncio_mode = auto`,
so these async tests carry no `@pytest.mark.asyncio` decorator.
"""

import pytest_asyncio

from app.config import settings
from app.models.user import Role
from app.seed import demo_user_specs, seed


@pytest_asyncio.fixture
async def seeded(db_session):
    """Seed the demo tenants and personas. Idempotent: a no-op after the first call."""
    await seed(db_session)


def email_for_role(role: Role) -> str:
    """Return the email/username of the first seeded persona holding `role`."""
    return next(
        email for email, spec_role, _slug in demo_user_specs() if spec_role is role
    )


def tenant_slug_for_role(role: Role) -> str:
    """Return the tenant slug of the first seeded persona holding `role`."""
    return next(
        slug for _email, spec_role, slug in demo_user_specs() if spec_role is role
    )


async def login_as(client, role: Role):
    """Log in as the first seeded persona for `role`; return the login response."""
    return await client.post(
        "/api/auth/login",
        json={
            "username": email_for_role(role),
            "password": settings.seed_user_password,
        },
    )


# --- Login -------------------------------------------------------------------


async def test_login_succeeds_for_seeded_tenant_admin(seeded, db_client):
    """A seeded Tenant Admin logs in → 200, identity body, and a `pf_session` cookie."""
    response = await login_as(db_client, Role.TENANT_ADMIN)

    assert response.status_code == 200
    body = response.json()
    user = body["user"]
    assert set(user) == {"id", "username", "role", "tenant_id"}
    assert user["username"] == email_for_role(Role.TENANT_ADMIN)
    assert user["role"] == Role.TENANT_ADMIN.value
    assert isinstance(body["capabilities"], list)
    assert "pf_session" in db_client.cookies


async def test_login_wrong_password_is_generic_401(seeded, db_client):
    """A correct user with the wrong password → generic 401."""
    response = await db_client.post(
        "/api/auth/login",
        json={
            "username": email_for_role(Role.TENANT_ADMIN),
            "password": "the wrong password",
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "invalid credentials"}


async def test_login_unknown_user_is_generic_401(seeded, db_client):
    """An unknown username → the identical generic 401, indistinguishable from above."""
    response = await db_client.post(
        "/api/auth/login",
        json={
            "username": "nobody-by-this-name@policyflow.example",
            "password": settings.seed_user_password,
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "invalid credentials"}


# --- /api/auth/me ------------------------------------------------------------


async def test_me_returns_identity_when_authenticated(seeded, db_client):
    """After login, GET /me → 200 with the same identity shape and user id."""
    login_response = await login_as(db_client, Role.TENANT_ADMIN)
    assert login_response.status_code == 200

    me_response = await db_client.get("/api/auth/me")

    assert me_response.status_code == 200
    assert me_response.json()["user"]["id"] == login_response.json()["user"]["id"]


async def test_me_unauthenticated_is_401(seeded, db_client):
    """A fresh client with no session cookie, GET /me → 401."""
    response = await db_client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}


async def test_me_after_logout_is_401(seeded, db_client):
    """Login → logout (200) → GET /me → 401: the session is revoked and cookie cleared."""
    assert (await login_as(db_client, Role.TENANT_ADMIN)).status_code == 200

    logout_response = await db_client.post("/api/auth/logout")
    assert logout_response.status_code == 200
    assert logout_response.json() == {"detail": "logged out"}

    me_response = await db_client.get("/api/auth/me")
    assert me_response.status_code == 401


# --- GET /api/tenant/config — the per-role matrix ----------------------------


async def test_tenant_config_allows_tenant_admin(seeded, db_client):
    """A Tenant Admin reads their tenant config → 200 with the matching slug."""
    assert (await login_as(db_client, Role.TENANT_ADMIN)).status_code == 200

    response = await db_client.get("/api/tenant/config")

    assert response.status_code == 200
    tenant = response.json()["tenant"]
    assert set(tenant) == {"id", "name", "slug"}
    assert tenant["slug"] == tenant_slug_for_role(Role.TENANT_ADMIN)


async def test_tenant_config_forbids_agent(seeded, db_client):
    """An Agent lacks VIEW_TENANT_CONFIG → 403."""
    assert (await login_as(db_client, Role.AGENT)).status_code == 200

    response = await db_client.get("/api/tenant/config")

    assert response.status_code == 403
    assert response.json() == {"detail": "insufficient permissions"}


async def test_tenant_config_forbids_read_only(seeded, db_client):
    """A Read-Only user lacks VIEW_TENANT_CONFIG → 403."""
    assert (await login_as(db_client, Role.READ_ONLY)).status_code == 200

    response = await db_client.get("/api/tenant/config")

    assert response.status_code == 403
    assert response.json() == {"detail": "insufficient permissions"}


async def test_tenant_config_forbids_platform_admin(seeded, db_client):
    """A Platform Admin lacks VIEW_TENANT_CONFIG → 403."""
    assert (await login_as(db_client, Role.PLATFORM_ADMIN)).status_code == 200

    response = await db_client.get("/api/tenant/config")

    assert response.status_code == 403
    assert response.json() == {"detail": "insufficient permissions"}


async def test_tenant_config_unauthenticated_is_401(seeded, db_client):
    """A fresh client with no session cookie → 401."""
    response = await db_client.get("/api/tenant/config")

    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}
