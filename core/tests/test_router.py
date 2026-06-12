"""Unit tests for the auth HTTP router (login / logout / me).

Pure unit tests — no DB, no Docker — matching the no-Docker style of
`test_dependencies.py`. The real `auth_router` is mounted on a throwaway FastAPI
app + `TestClient`. `app.dependency_overrides` swaps in a fixed-`Identity` provider
and a dummy DB session, and `monkeypatch` replaces `router.create_session` /
`router.revoke_session` so no session ever touches a database.

The cases prove: login success returns 200 with the exact identity body (the
sorted capability strings for the role) and sets the `pf_session` cookie; login
failure returns a single generic 401 with no cookie; logout revokes the presented
token, clears the cookie, and returns `{"detail": "logged out"}` — and still
succeeds with no cookie (no revoke); `me` returns login's identical body for an
authenticated caller and inherits the 401 when nobody is signed in.
"""

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import router as router_module
from app.auth.dependencies import require_authenticated
from app.auth.provider import Identity
from app.auth.rbac import CAPABILITIES
from app.auth.router import get_auth_provider, router as auth_router
from app.db import get_db
from app.models.user import Role

AGENT_USER_ID = uuid.uuid4()
AGENT_TENANT_ID = uuid.uuid4()


async def stub_get_db():
    """Stand in for the request-scoped DB dependency, yielding a dummy session.

    The session functions are monkeypatched out, so this object is never used; it
    only needs to satisfy the dependency wiring.
    """
    yield object()


def make_agent_identity() -> Identity:
    """Build a fixed Agent `Identity` shared by the login and `me` assertions."""
    return Identity(
        user_id=AGENT_USER_ID,
        tenant_id=AGENT_TENANT_ID,
        role=Role.AGENT,
        username="ada",
    )


def expected_agent_body() -> dict:
    """The identity body both login and `me` must return for the Agent identity."""
    return {
        "user": {
            "id": str(AGENT_USER_ID),
            "username": "ada",
            "role": Role.AGENT.value,
            "tenant_id": str(AGENT_TENANT_ID),
        },
        "capabilities": sorted(
            capability.value for capability in CAPABILITIES[Role.AGENT]
        ),
    }


def build_app() -> FastAPI:
    """A throwaway app mounting the real auth router with a stubbed DB."""
    app = FastAPI()
    app.include_router(auth_router)
    app.dependency_overrides[get_db] = stub_get_db
    return app


# --- login -----------------------------------------------------------------


def test_login_success_sets_cookie_and_returns_identity(monkeypatch):
    """Valid credentials → 200, the exact identity body, and a `pf_session` cookie."""
    identity = make_agent_identity()

    class FixedProvider:
        async def authenticate(self, db, username, password):
            assert username == "ada"
            assert password == "correct-horse"
            return identity

    async def fake_create_session(db, user_id):
        assert user_id == AGENT_USER_ID
        return "fresh-token"

    monkeypatch.setattr(router_module, "create_session", fake_create_session)

    app = build_app()
    app.dependency_overrides[get_auth_provider] = lambda: FixedProvider()
    client = TestClient(app)

    response = client.post(
        "/api/auth/login",
        json={"username": "ada", "password": "correct-horse"},
    )

    assert response.status_code == 200
    assert response.json() == expected_agent_body()
    set_cookie_header = response.headers["set-cookie"]
    assert "pf_session=fresh-token" in set_cookie_header


def test_login_failure_returns_generic_401_and_no_cookie():
    """Provider returns `None` → 401 `{"detail": "invalid credentials"}`, no cookie."""

    class RejectingProvider:
        async def authenticate(self, db, username, password):
            return None

    app = build_app()
    app.dependency_overrides[get_auth_provider] = lambda: RejectingProvider()
    client = TestClient(app)

    response = client.post(
        "/api/auth/login",
        json={"username": "ada", "password": "wrong"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "invalid credentials"}
    assert "set-cookie" not in response.headers


# --- logout ----------------------------------------------------------------


def test_logout_revokes_token_clears_cookie_and_returns_detail(monkeypatch):
    """Logout revokes the presented token, clears the cookie, and returns the detail."""
    revoked_tokens = []

    async def fake_revoke_session(db, raw_token):
        revoked_tokens.append(raw_token)

    monkeypatch.setattr(router_module, "revoke_session", fake_revoke_session)

    client = TestClient(build_app())
    client.cookies.set("pf_session", "live-token")

    response = client.post("/api/auth/logout")

    assert response.status_code == 200
    assert response.json() == {"detail": "logged out"}
    assert revoked_tokens == ["live-token"]
    # The cookie is expired on the client.
    assert "Max-Age=0" in response.headers["set-cookie"]


def test_logout_without_cookie_still_succeeds_without_revoking(monkeypatch):
    """Logout with no session cookie → 200 and no revoke call (harmless no-op)."""
    revoke_calls = []

    async def fake_revoke_session(db, raw_token):
        revoke_calls.append(raw_token)

    monkeypatch.setattr(router_module, "revoke_session", fake_revoke_session)

    client = TestClient(build_app())

    response = client.post("/api/auth/logout")

    assert response.status_code == 200
    assert response.json() == {"detail": "logged out"}
    assert revoke_calls == []


# --- me --------------------------------------------------------------------


def test_me_returns_identity_body_for_authenticated_caller():
    """`me` returns login's identical body shape for the signed-in identity."""
    app = build_app()
    app.dependency_overrides[require_authenticated] = make_agent_identity
    client = TestClient(app)

    response = client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json() == expected_agent_body()


def test_me_rejects_when_unauthenticated():
    """No session → the inherited 401 `{"detail": "not authenticated"}`."""
    client = TestClient(build_app())

    response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}
