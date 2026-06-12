"""Unit tests for the FastAPI auth dependencies.

Pure unit tests — no DB, no Docker — matching the no-Docker style of
`test_provider.py` / `test_sessions.py`. Each dependency is driven through a tiny
throwaway FastAPI app + `TestClient`, with `app.dependency_overrides` stubbing the
`get_db` session and (where useful) the resolved `Identity`, so no database is
touched. The session resolver itself is stubbed via `monkeypatch` on
`dependencies.get_session_identity`, so these tests exercise the dependency wiring
(cookie reading, 401 seam, 403 matrix check) in isolation.

The cases prove, for Phase 1: no cookie → 401 `{"detail": "not authenticated"}`;
a cookie whose token resolves → the `Identity` flows through (200); a cookie whose
token does not resolve (expired/revoked/garbage) → 401. And for Phase 2: a route
guarded by `require_capability(VIEW_TENANT_CONFIG)` returns 200 for a Tenant Admin,
403 `{"detail": "insufficient permissions"}` for an Agent, and 401 with no session.
"""

import uuid

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth import dependencies
from app.auth.dependencies import (
    get_current_identity,
    require_authenticated,
    require_capability,
)
from app.auth.provider import Identity
from app.auth.rbac import Capability
from app.db import get_db
from app.models.user import Role


async def stub_get_db():
    """Stand in for the request-scoped DB dependency, yielding a dummy session.

    The real resolver is monkeypatched out, so the session object is never used;
    it only needs to satisfy the dependency wiring.
    """
    yield object()


def make_identity(role: Role) -> Identity:
    """Build an in-memory `Identity` with the given role for the guard tests."""
    return Identity(
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        role=role,
        username="ada",
    )


def build_app() -> FastAPI:
    """A throwaway app exposing one route per dependency under test."""
    app = FastAPI()

    @app.get("/current")
    async def read_current(
        identity: Identity | None = Depends(get_current_identity),
    ):
        return {"username": identity.username if identity else None}

    @app.get("/protected")
    async def read_protected(
        identity: Identity = Depends(require_authenticated),
    ):
        return {"username": identity.username}

    @app.get("/tenant-config")
    async def read_tenant_config(
        identity: Identity = Depends(
            require_capability(Capability.VIEW_TENANT_CONFIG)
        ),
    ):
        return {"username": identity.username}

    app.dependency_overrides[get_db] = stub_get_db
    return app


# --- Phase 1: identity resolution + the 401 seam ---------------------------


def test_require_authenticated_rejects_when_no_cookie():
    """No `pf_session` cookie → 401 `{"detail": "not authenticated"}`."""
    client = TestClient(build_app())

    response = client.get("/protected")

    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}


def test_require_authenticated_returns_identity_when_token_resolves(monkeypatch):
    """A cookie whose token resolves flows the `Identity` through (200)."""
    resolved = make_identity(Role.AGENT)

    async def fake_get_session_identity(db, raw_token):
        assert raw_token == "good-token"
        return resolved

    monkeypatch.setattr(
        dependencies, "get_session_identity", fake_get_session_identity
    )
    client = TestClient(build_app())
    client.cookies.set("pf_session", "good-token")

    response = client.get("/protected")

    assert response.status_code == 200
    assert response.json() == {"username": "ada"}


def test_require_authenticated_rejects_when_token_does_not_resolve(monkeypatch):
    """A cookie whose token does not resolve (expired/revoked/garbage) → 401."""

    async def fake_get_session_identity(db, raw_token):
        return None

    monkeypatch.setattr(
        dependencies, "get_session_identity", fake_get_session_identity
    )
    client = TestClient(build_app())
    client.cookies.set("pf_session", "stale-token")

    response = client.get("/protected")

    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}


def test_get_current_identity_returns_none_without_cookie():
    """`get_current_identity` yields `None` (not a 401) when no cookie is present."""
    client = TestClient(build_app())

    response = client.get("/current")

    assert response.status_code == 200
    assert response.json() == {"username": None}


# --- Phase 2: the require_capability 403 layer -----------------------------


def test_require_capability_allows_role_that_holds_it():
    """A Tenant Admin holds VIEW_TENANT_CONFIG → 200 with the identity."""
    app = build_app()
    app.dependency_overrides[require_authenticated] = lambda: make_identity(
        Role.TENANT_ADMIN
    )
    client = TestClient(app)

    response = client.get("/tenant-config")

    assert response.status_code == 200
    assert response.json() == {"username": "ada"}


def test_require_capability_rejects_role_that_lacks_it():
    """An Agent lacks VIEW_TENANT_CONFIG → 403 `insufficient permissions`."""
    app = build_app()
    app.dependency_overrides[require_authenticated] = lambda: make_identity(
        Role.AGENT
    )
    client = TestClient(app)

    response = client.get("/tenant-config")

    assert response.status_code == 403
    assert response.json() == {"detail": "insufficient permissions"}


def test_require_capability_rejects_when_unauthenticated():
    """No session → the inherited 401 seam fires before the capability check."""
    client = TestClient(build_app())

    response = client.get("/tenant-config")

    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}
