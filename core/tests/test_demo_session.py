"""The demo-session lifecycle: mint / reuse / read-only resolve, cookie, logging.

Two layers, mirroring the suite's split:

- **Pure cookie-attribute tests** (no DB) over `_set_demo_session_cookie`, the
  `pf_demo_session` mirror of `auth.sessions.set_session_cookie` — HttpOnly,
  SameSite=lax, the 24h Max-Age, Path, and the Secure toggle.
- **DB-backed lifecycle tests** over `ensure_demo_session` / `current_demo_session`
  on the real container substrate (the `db_session` fixture): a fresh visit mints a
  row + cookie + one INFO line, a cookie naming a live row is reused silently (no
  new row, no cookie rewrite), a slug refreshes `last_tenant_slug`, and an expired
  or unknown cookie resolves to `None` (and re-mints under `ensure`).
- **End-to-end tracer** (`db_client`): `assume-persona` mints the demo session, and
  a following `POST /api/leads` tags both the lead **row** and its `lead.created`
  outbox event with that same minted `demo_session_id`.

`pytest.ini` sets `asyncio_mode = auto`, so the async tests carry no
`@pytest.mark.asyncio` decorator. The `db_session` / `db_client` / `database_engine`
fixtures and the lead read-back helpers are reused by import from the existing
substrate and the Epic-7 intake suite.
"""

import contextlib
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Response
from starlette.requests import Request

from app.config import settings
from app.demo.session import (
    DEMO_SESSION_COOKIE_NAME,
    DemoSessionStatus,
    _set_demo_session_cookie,
    current_demo_session,
    ensure_demo_session,
    read_demo_session_state,
)
from app.events.catalog import EventType
from app.models.demo_session import DemoSession
from app.models.user import Role
from app.tenancy.registry import SUNSHINE

from tests.test_demo_assume_persona import assume  # noqa: F401 — used by name
from tests.test_endpoints_db import login_as, seeded  # noqa: F401 — `seeded` used by name
from tests.test_lead_intake import (
    read_lead_row,
    read_outbox_rows_for_entity,
    unique_contact,
)


# --- request/response test doubles -------------------------------------------


def _request_with_cookie(raw_id: str | None) -> Request:
    """Build a minimal ASGI `Request` carrying (or omitting) the demo cookie.

    A starlette `Request` parses cookies from the `cookie` header, so the only
    scope entry that matters here is that header. `raw_id=None` yields a request
    with no cookie at all (the fresh-visit case).
    """
    headers = []
    if raw_id is not None:
        cookie_value = f"{DEMO_SESSION_COOKIE_NAME}={raw_id}".encode("latin-1")
        headers.append((b"cookie", cookie_value))
    scope = {"type": "http", "headers": headers}
    return Request(scope)


# --- pure cookie-attribute tests (no DB) -------------------------------------


def test_demo_session_cookie_default_attributes():
    """Default cookie: HttpOnly, SameSite=lax, the 24h Max-Age, Path, no Secure."""
    response = Response()

    _set_demo_session_cookie(response, "a-raw-id")

    set_cookie_header = response.headers["set-cookie"]
    assert DEMO_SESSION_COOKIE_NAME in set_cookie_header
    assert "a-raw-id" in set_cookie_header
    assert "HttpOnly" in set_cookie_header
    assert "SameSite=lax" in set_cookie_header
    assert "Max-Age=86400" in set_cookie_header
    assert "Path=/" in set_cookie_header
    assert "Secure" not in set_cookie_header


def test_demo_session_cookie_adds_secure_when_enabled():
    """Toggling `session_cookie_secure` on adds the Secure flag (mirrors pf_session)."""
    response = Response()
    original_secure = settings.session_cookie_secure
    settings.session_cookie_secure = True
    try:
        _set_demo_session_cookie(response, "a-raw-id")
    finally:
        settings.session_cookie_secure = original_secure

    assert "Secure" in response.headers["set-cookie"]


def test_demo_session_cookie_name_is_pf_demo_session():
    """The single cookie-name constant is `pf_demo_session`."""
    assert DEMO_SESSION_COOKIE_NAME == "pf_demo_session"


# --- DB-backed lifecycle: mint -----------------------------------------------


async def test_ensure_mints_a_session_and_sets_the_cookie(db_session):
    """A fresh visit mints a `demo_sessions` row, returns ACTIVE, and sets the cookie."""
    request = _request_with_cookie(None)
    response = Response()

    state = await ensure_demo_session(db_session, request, response)

    assert state.status is DemoSessionStatus.ACTIVE
    assert isinstance(state.id, uuid.UUID)
    # The row is durable in the DB.
    row = await db_session.get(DemoSession, state.id)
    assert row is not None
    # The cookie carries the raw id and the 24h window.
    set_cookie_header = response.headers["set-cookie"]
    assert f"{DEMO_SESSION_COOKIE_NAME}={state.id}" in set_cookie_header
    assert "Max-Age=86400" in set_cookie_header


async def test_ensure_sets_expires_at_one_lifetime_ahead(db_session):
    """The minted `expires_at` is ~`DEMO_SESSION_LIFETIME_SECONDS` from now."""
    request = _request_with_cookie(None)
    response = Response()

    state = await ensure_demo_session(db_session, request, response)

    expected = datetime.now(timezone.utc) + timedelta(
        seconds=settings.demo_session_lifetime_seconds
    )
    # Generous window — the row's clock and the test clock are seconds apart.
    assert abs((state.expires_at - expected).total_seconds()) < 120


class _CapturingHandler(logging.Handler):
    """A tiny handler that keeps the messages it is given.

    `caplog` cannot be used here: the session-scoped DB substrate runs Alembic,
    whose `fileConfig` reconfigures the root logger and drops `caplog`'s capture
    handler, so propagation-based capture silently sees nothing. Attaching our own
    handler directly to the `app.demo.session` logger (and forcing its level)
    sidesteps that entirely.
    """

    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@contextlib.contextmanager
def _capture_demo_session_logs():
    """Capture INFO logs from the `app.demo.session` logger, restoring it after.

    The session-scoped DB substrate runs Alembic, whose `fileConfig` defaults to
    `disable_existing_loggers=True` and so **disables** the `app.demo.session`
    logger that was created at import — a test-substrate artifact (the app's own
    boot never re-runs `fileConfig` in-process). Re-enabling it and forcing its
    level here makes the capture deterministic regardless of run order.
    """
    logger = logging.getLogger("app.demo.session")
    handler = _CapturingHandler()
    previous_level = logger.level
    previous_disabled = logger.disabled
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.disabled = False
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        logger.disabled = previous_disabled


async def test_ensure_logs_one_info_line_on_mint(db_session):
    """Minting logs exactly one INFO line carrying the session id (mint-only)."""
    request = _request_with_cookie(None)
    response = Response()

    with _capture_demo_session_logs() as handler:
        state = await ensure_demo_session(db_session, request, response)

    mint_messages = [
        message for message in handler.messages if "demo session minted" in message
    ]
    assert len(mint_messages) == 1
    assert str(state.id) in mint_messages[0]


# --- DB-backed lifecycle: reuse (no new row, silent, no cookie rewrite) -------


async def test_ensure_reuses_a_live_cookie_session(db_session):
    """A cookie naming a live row is reused: same id, ACTIVE, no second row minted."""
    minted = await ensure_demo_session(
        db_session, _request_with_cookie(None), Response()
    )

    reuse_request = _request_with_cookie(str(minted.id))
    reuse_response = Response()
    reused = await ensure_demo_session(db_session, reuse_request, reuse_response)

    assert reused.id == minted.id
    assert reused.status is DemoSessionStatus.ACTIVE
    # Reuse is silent: it does not set the cookie again.
    assert "set-cookie" not in reuse_response.headers


async def test_ensure_does_not_log_on_reuse(db_session):
    """Reuse is silent — no INFO mint line on the hot path."""
    minted = await ensure_demo_session(
        db_session, _request_with_cookie(None), Response()
    )

    with _capture_demo_session_logs() as handler:
        await ensure_demo_session(
            db_session, _request_with_cookie(str(minted.id)), Response()
        )

    mint_messages = [
        message for message in handler.messages if "demo session minted" in message
    ]
    assert mint_messages == []


async def test_ensure_refreshes_last_tenant_slug_on_reuse(db_session):
    """Reusing with a `tenant_slug` updates the row's informational `last_tenant_slug`."""
    minted = await ensure_demo_session(
        db_session, _request_with_cookie(None), Response()
    )
    assert minted.last_tenant_slug is None

    reused = await ensure_demo_session(
        db_session,
        _request_with_cookie(str(minted.id)),
        Response(),
        tenant_slug=SUNSHINE.slug,
    )

    assert reused.last_tenant_slug == SUNSHINE.slug
    row = await db_session.get(DemoSession, minted.id)
    await db_session.refresh(row)
    assert row.last_tenant_slug == SUNSHINE.slug


# --- DB-backed lifecycle: expired / unknown ----------------------------------


async def _insert_expired_session(db_session) -> uuid.UUID:
    """Insert a `demo_sessions` row already past its window; return its id."""
    expired = DemoSession(
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
    )
    db_session.add(expired)
    await db_session.commit()
    await db_session.refresh(expired)
    return expired.id


async def test_current_returns_none_for_no_cookie(db_session):
    """`current_demo_session` with no cookie resolves to `None` (read-only, no mint)."""
    result = await current_demo_session(_request_with_cookie(None), db_session)
    assert result is None


async def test_current_returns_none_for_expired_session(db_session):
    """An expired cookie resolves to `None` — the window has passed."""
    expired_id = await _insert_expired_session(db_session)

    result = await current_demo_session(
        _request_with_cookie(str(expired_id)), db_session
    )

    assert result is None


async def test_current_returns_none_for_unknown_and_malformed_cookie(db_session):
    """A cookie naming no row, or a non-UUID value, both resolve to `None`."""
    unknown = await current_demo_session(
        _request_with_cookie(str(uuid.uuid4())), db_session
    )
    assert unknown is None

    malformed = await current_demo_session(
        _request_with_cookie("not-a-uuid"), db_session
    )
    assert malformed is None


async def test_current_resolves_a_live_session(db_session):
    """A cookie naming a live row resolves to its ACTIVE state, read-only."""
    minted = await ensure_demo_session(
        db_session, _request_with_cookie(None), Response()
    )

    resolved = await current_demo_session(
        _request_with_cookie(str(minted.id)), db_session
    )

    assert resolved is not None
    assert resolved.id == minted.id
    assert resolved.status is DemoSessionStatus.ACTIVE


async def test_ensure_remints_when_the_cookie_session_has_expired(db_session):
    """`ensure` with an expired cookie mints a fresh row (not a silent reuse)."""
    expired_id = await _insert_expired_session(db_session)
    response = Response()

    state = await ensure_demo_session(
        db_session, _request_with_cookie(str(expired_id)), response
    )

    assert state.status is DemoSessionStatus.ACTIVE
    assert state.id != expired_id
    assert "set-cookie" in response.headers


# --- tri-state resolver: read_demo_session_state -----------------------------


async def test_read_state_is_none_for_no_cookie(db_session):
    """No cookie → NONE, with no id / expiry / tenant surfaced."""
    state = await read_demo_session_state(_request_with_cookie(None), db_session)

    assert state.status is DemoSessionStatus.NONE
    assert state.id is None
    assert state.expires_at is None
    assert state.last_tenant_slug is None


async def test_read_state_is_none_for_unknown_and_malformed_cookie(db_session):
    """A cookie naming no row, or a non-UUID value, both resolve to NONE."""
    unknown = await read_demo_session_state(
        _request_with_cookie(str(uuid.uuid4())), db_session
    )
    assert unknown.status is DemoSessionStatus.NONE

    malformed = await read_demo_session_state(
        _request_with_cookie("not-a-uuid"), db_session
    )
    assert malformed.status is DemoSessionStatus.NONE


async def test_read_state_is_active_for_a_live_session(db_session):
    """A cookie naming a live row → ACTIVE with all fields populated."""
    minted = await ensure_demo_session(
        db_session,
        _request_with_cookie(None),
        Response(),
        tenant_slug=SUNSHINE.slug,
    )

    state = await read_demo_session_state(
        _request_with_cookie(str(minted.id)), db_session
    )

    assert state.status is DemoSessionStatus.ACTIVE
    assert state.id == minted.id
    assert state.expires_at == minted.expires_at
    assert state.last_tenant_slug == SUNSHINE.slug


async def test_read_state_is_expired_for_a_known_expired_session(db_session):
    """A cookie naming a real but expired row → EXPIRED, keeping expiry + tenant.

    Unlike `current_demo_session` (which collapses this to `None`), the tri-state
    resolver reports `EXPIRED` and surfaces `last_tenant_slug` + `expires_at` —
    the seam the graceful-expiry epic reuses to preserve the tenant.
    """
    expired = DemoSession(
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        last_tenant_slug=SUNSHINE.slug,
    )
    db_session.add(expired)
    await db_session.commit()
    await db_session.refresh(expired)

    state = await read_demo_session_state(
        _request_with_cookie(str(expired.id)), db_session
    )

    assert state.status is DemoSessionStatus.EXPIRED
    assert state.id == expired.id
    assert state.expires_at == expired.expires_at
    assert state.last_tenant_slug == SUNSHINE.slug


# --- public endpoint: GET /api/demo/session ----------------------------------


async def test_get_demo_session_endpoint_reports_none_without_a_cookie(db_client):
    """The public endpoint returns just `{"status": "none"}` with no cookie."""
    response = await db_client.get("/api/demo/session")

    assert response.status_code == 200
    assert response.json() == {"status": "none"}


async def test_get_demo_session_endpoint_reports_active(seeded, db_client):  # noqa: F811 — `seeded` is a fixture param, not a redefinition
    """After assume-persona mints a session, the endpoint reports it ACTIVE.

    Drives the real mint via `assume-persona` (which sets the cookie on the
    client), then reads `GET /api/demo/session` back — the seam the masthead
    countdown consumes. The body carries `demo_session_id`, `expires_at`, and the
    remembered tenant.
    """
    assume_response = await assume(
        db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT
    )
    assert assume_response.status_code == 200
    minted_id = db_client.cookies[DEMO_SESSION_COOKIE_NAME]

    response = await db_client.get("/api/demo/session")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "active"
    assert body["demo_session_id"] == minted_id
    assert "expires_at" in body
    assert body["last_tenant_slug"] == SUNSHINE.slug


async def test_get_demo_session_endpoint_reports_expired(db_client, db_session):
    """A cookie naming a known-but-expired row → status `expired` + its fields.

    Inserts an expired row directly, points the client's cookie at it, and reads
    the endpoint back — proving the `expired` branch the graceful-expiry epic
    relies on (distinct from a plain `none`).
    """
    expired = DemoSession(
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        last_tenant_slug=SUNSHINE.slug,
    )
    db_session.add(expired)
    await db_session.commit()
    await db_session.refresh(expired)

    db_client.cookies.set(DEMO_SESSION_COOKIE_NAME, str(expired.id))
    response = await db_client.get("/api/demo/session")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "expired"
    assert body["demo_session_id"] == str(expired.id)
    assert body["last_tenant_slug"] == SUNSHINE.slug
    assert "expires_at" in body


# --- End-to-end tracer: mint -> carry -> tag -> observe ----------------------


async def test_assume_persona_then_create_lead_tags_row_and_event(
    seeded, db_client, database_engine  # noqa: F811 — `seeded` is a fixture param, not a redefinition
):
    """TRACER: assume-persona mints the session; a created lead + its event carry its id.

    The thin mint → carry → tag → observe thread on the real substrate. Assuming a
    Sunshine Agent persona mints a demo session and sets the `pf_demo_session`
    cookie on the client. A following `POST /api/leads` resolves that cookie
    (read-only) and tags both the stored lead **row** and its `lead.created` outbox
    event with the same `demo_session_id`.
    """
    assume_response = await assume(
        db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT
    )
    assert assume_response.status_code == 200
    # The mint set the demo-session cookie on the client.
    assert DEMO_SESSION_COOKIE_NAME in db_client.cookies
    minted_id = uuid.UUID(db_client.cookies[DEMO_SESSION_COOKIE_NAME])

    email, phone = unique_contact()
    create_response = await db_client.post(
        "/api/leads",
        json={
            "first_name": "Tracer",
            "last_name": "Bullet",
            "email": email,
            "phone": phone,
            "date_of_birth": "1950-03-15",
            "zip_code": "33101",
            "product_lines_of_interest": ["medicare_advantage"],
        },
    )
    assert create_response.status_code == 201
    lead_id = uuid.UUID(create_response.json()["lead"]["id"])

    # The lead row carries the minted demo-session id.
    row = await read_lead_row(database_engine, SUNSHINE.schema_name, lead_id)
    assert row.demo_session_id == minted_id

    # The `lead.created` event carries the same id.
    created_rows = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.LEAD_CREATED, lead_id
    )
    assert len(created_rows) == 1
    assert created_rows[0].demo_session_id == minted_id
