"""Unit tests for the auth HTTP router (login / logout / me).

Pure unit tests — no DB, no Docker — matching the no-Docker style of
`test_dependencies.py`. The real `auth_router` is mounted on a throwaway FastAPI
app + `TestClient`. `app.dependency_overrides` swaps in a fixed-`Identity` provider
and a dummy DB session, and `monkeypatch` replaces `router.create_session` /
`router.revoke_session` / `router.get_session_identity` /
`router.record_audit_event` so no session and no audit write ever touches a
database. Patching the audit emit in the router's namespace is the same idiom this
file already uses for the session functions, and it keeps these tests pure while
letting them assert the emitted audit args (Epic 8).

The cases prove: login success returns 200 with the exact identity body (the
sorted capability strings for the role), sets the `pf_session` cookie, and emits
`auth.login` / `success` for the identity; login failure returns a single generic
401 with no cookie and emits a PII-free `auth.login` / `failure`; logout resolves
the identity, revokes the presented token, clears the cookie, returns
`{"detail": "logged out"}`, and emits `auth.logout` / `success` attributed to that
identity — and still succeeds with no cookie, resolving/revoking/emitting nothing;
`me` returns login's identical body for an authenticated caller and inherits the
401 when nobody is signed in.
"""

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.audit.records import EventType, Outcome
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


def capture_audit_events(monkeypatch) -> list[dict]:
    """Patch the router's `record_audit_event` to capture each emit's kwargs.

    Returns the list the fake appends one dict of keyword arguments to per call,
    so a case can assert exactly what (if anything) the route emitted. Patching the
    name in the router's namespace keeps these tests pure — the audit service never
    opens its own session against the unreachable eager engine — the same idiom this
    file uses for `create_session` / `revoke_session`.
    """
    recorded_events: list[dict] = []

    async def fake_record_audit_event(**keyword_arguments):
        recorded_events.append(keyword_arguments)

    monkeypatch.setattr(
        router_module, "record_audit_event", fake_record_audit_event
    )
    return recorded_events


# --- login -----------------------------------------------------------------


def test_login_success_sets_cookie_and_returns_identity(monkeypatch):
    """Valid credentials → 200, the exact identity body, and a `pf_session` cookie.

    Also emits one `auth.login` / `success` audit event attributed to the identity
    and routed by its `tenant_id`.
    """
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
    recorded_events = capture_audit_events(monkeypatch)

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

    # Exactly one audit event: `auth.login` / `success`, attributed to the identity
    # and routed by its tenant.
    assert recorded_events == [
        {
            "tenant_id": AGENT_TENANT_ID,
            "actor_user_id": AGENT_USER_ID,
            "actor_role": Role.AGENT,
            "event_type": EventType.AUTH_LOGIN,
            "outcome": Outcome.SUCCESS,
        }
    ]


def test_login_failure_returns_generic_401_and_no_cookie(monkeypatch):
    """Provider returns `None` → 401 `{"detail": "invalid credentials"}`, no cookie.

    Also emits one PII-free `auth.login` / `failure` audit event to the platform
    store: `tenant_id`, `actor_user_id`, and `actor_role` are all `None`, and the
    attempted username never reaches the call.
    """

    class RejectingProvider:
        async def authenticate(self, db, username, password):
            return None

    recorded_events = capture_audit_events(monkeypatch)

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

    # Exactly one audit event: `auth.login` / `failure`, carrying no identifying
    # PII and routed to the platform store (`tenant_id=None`).
    assert recorded_events == [
        {
            "tenant_id": None,
            "actor_user_id": None,
            "actor_role": None,
            "event_type": EventType.AUTH_LOGIN,
            "outcome": Outcome.FAILURE,
        }
    ]


# --- logout ----------------------------------------------------------------


def test_logout_revokes_token_clears_cookie_and_returns_detail(monkeypatch):
    """Logout resolves, revokes, clears the cookie, returns the detail, and audits.

    The identity is resolved from the session **before** the token is revoked, so
    the emitted `auth.logout` / `success` event is attributed to that identity and
    routed by its `tenant_id`.
    """
    identity = make_agent_identity()
    resolved_tokens = []
    revoked_tokens = []

    async def fake_get_session_identity(db, raw_token):
        resolved_tokens.append(raw_token)
        return identity

    async def fake_revoke_session(db, raw_token):
        revoked_tokens.append(raw_token)

    monkeypatch.setattr(
        router_module, "get_session_identity", fake_get_session_identity
    )
    monkeypatch.setattr(router_module, "revoke_session", fake_revoke_session)
    recorded_events = capture_audit_events(monkeypatch)

    client = TestClient(build_app())
    client.cookies.set("pf_session", "live-token")

    response = client.post("/api/auth/logout")

    assert response.status_code == 200
    assert response.json() == {"detail": "logged out"}
    # The identity is resolved before the token is revoked.
    assert resolved_tokens == ["live-token"]
    assert revoked_tokens == ["live-token"]
    # The cookie is expired on the client.
    assert "Max-Age=0" in response.headers["set-cookie"]

    # Exactly one audit event: `auth.logout` / `success`, attributed to the
    # resolved identity and routed by its tenant.
    assert recorded_events == [
        {
            "tenant_id": AGENT_TENANT_ID,
            "actor_user_id": AGENT_USER_ID,
            "actor_role": Role.AGENT,
            "event_type": EventType.AUTH_LOGOUT,
            "outcome": Outcome.SUCCESS,
        }
    ]


def test_logout_without_cookie_still_succeeds_without_revoking(monkeypatch):
    """Logout with no session cookie → 200, no resolve/revoke, and no audit event."""
    resolve_calls = []
    revoke_calls = []

    async def fake_get_session_identity(db, raw_token):
        resolve_calls.append(raw_token)
        return make_agent_identity()

    async def fake_revoke_session(db, raw_token):
        revoke_calls.append(raw_token)

    monkeypatch.setattr(
        router_module, "get_session_identity", fake_get_session_identity
    )
    monkeypatch.setattr(router_module, "revoke_session", fake_revoke_session)
    recorded_events = capture_audit_events(monkeypatch)

    client = TestClient(build_app())

    response = client.post("/api/auth/logout")

    assert response.status_code == 200
    assert response.json() == {"detail": "logged out"}
    # No cookie → nothing is resolved, revoked, or audited (a no-session logout is
    # not an audit event).
    assert resolve_calls == []
    assert revoke_calls == []
    assert recorded_events == []


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
