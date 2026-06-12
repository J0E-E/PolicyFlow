"""Unit tests for the guarded tenant router (`GET /api/tenant/config`).

Pure unit tests — no DB, no Docker — matching the no-Docker style of
`test_router.py` / `test_dependencies.py`. The real `tenant_router` is mounted on a
throwaway FastAPI app + `TestClient`. The seam overridden is `get_current_identity`
(which `require_capability` is built on, via `require_authenticated`), so the
**real** `require_capability` matrix check runs: only a Tenant Admin reaches the
handler. `get_db` is overridden to yield a tiny fake async session whose
`execute(...)` returns a stub result, mirroring the `FakeAsyncSession` approach in
`test_provider.py`, so no session ever touches a database.

The cases prove: a Tenant Admin gets 200 with the exact `{"tenant": {...}}` body;
every other role (Agent, Read-Only, Platform Admin) is rejected with 403 by the
real matrix; and the anonymous caller (no session) inherits the 401.
"""

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_identity
from app.auth.provider import Identity
from app.db import get_db
from app.models.tenant import Tenant
from app.models.user import Role
from app.tenant.router import router as tenant_router

TENANT_ID = uuid.uuid4()
USER_ID = uuid.uuid4()


class FakeResult:
    """A stand-in for a SQLAlchemy `Result` that yields one preset row.

    `scalar_one_or_none()` returns whatever single row (a `Tenant` or `None`) the
    fake session was told to hand back, so the route's lookup can be exercised with
    no database.
    """

    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class FakeAsyncSession:
    """A minimal async session whose `execute` returns a preset result.

    This is all the surface the tenant route touches: it runs one `select(Tenant)`
    and reads `scalar_one_or_none()` off the result.
    """

    def __init__(self, row):
        self._row = row

    async def execute(self, statement):
        return FakeResult(self._row)


def make_identity(role: Role) -> Identity:
    """Build a fixed `Identity` for `role`, pointing at the shared tenant."""
    return Identity(
        user_id=USER_ID,
        tenant_id=TENANT_ID,
        role=role,
        username="ada",
    )


def make_tenant() -> Tenant:
    """Build an in-memory `Tenant` row the fake session hands back."""
    return Tenant(id=TENANT_ID, name="Acme Insurance", slug="acme")


def build_app(identity: Identity | None, tenant_row) -> FastAPI:
    """A throwaway app mounting the real tenant router.

    Overrides `get_current_identity` with `identity` (so the real
    `require_capability` matrix check still runs) and `get_db` with a fake session
    yielding `tenant_row`.
    """
    app = FastAPI()
    app.include_router(tenant_router)

    async def override_get_current_identity():
        return identity

    async def override_get_db():
        yield FakeAsyncSession(tenant_row)

    app.dependency_overrides[get_current_identity] = override_get_current_identity
    app.dependency_overrides[get_db] = override_get_db
    return app


def test_tenant_admin_gets_tenant_config():
    """Tenant Admin → 200 with the exact `{"tenant": {id, name, slug}}` body."""
    app = build_app(make_identity(Role.TENANT_ADMIN), make_tenant())
    client = TestClient(app)

    response = client.get("/api/tenant/config")

    assert response.status_code == 200
    assert response.json() == {
        "tenant": {
            "id": str(TENANT_ID),
            "name": "Acme Insurance",
            "slug": "acme",
        }
    }


def test_agent_is_forbidden():
    """Agent lacks `VIEW_TENANT_CONFIG` → 403 from the real matrix check."""
    app = build_app(make_identity(Role.AGENT), make_tenant())
    client = TestClient(app)

    response = client.get("/api/tenant/config")

    assert response.status_code == 403
    assert response.json() == {"detail": "insufficient permissions"}


def test_read_only_is_forbidden():
    """Read-Only lacks `VIEW_TENANT_CONFIG` → 403."""
    app = build_app(make_identity(Role.READ_ONLY), make_tenant())
    client = TestClient(app)

    response = client.get("/api/tenant/config")

    assert response.status_code == 403
    assert response.json() == {"detail": "insufficient permissions"}


def test_platform_admin_is_forbidden():
    """Platform Admin lacks `VIEW_TENANT_CONFIG` → 403 (single-role guarantee)."""
    app = build_app(make_identity(Role.PLATFORM_ADMIN), make_tenant())
    client = TestClient(app)

    response = client.get("/api/tenant/config")

    assert response.status_code == 403
    assert response.json() == {"detail": "insufficient permissions"}


def test_anonymous_caller_is_unauthenticated():
    """No session → the inherited 401 `{"detail": "not authenticated"}`."""
    app = build_app(None, make_tenant())
    client = TestClient(app)

    response = client.get("/api/tenant/config")

    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}
