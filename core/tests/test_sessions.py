"""Unit tests for the server-side session plumbing.

Pure unit tests — no DB, no Docker — matching the no-Docker style of
`test_provider.py`. The session functions are driven through a tiny fake async
session that records what was added, executed, and committed, and (for the
resolve path) returns a stub result whose `scalar_one_or_none()` yields a chosen
in-memory `User` (or `None`). A `User()` and an `AuthSession()` can be built in
memory without a live session, so no database is touched. The cookie helpers are
exercised against a real `fastapi.Response`.

The cases prove: `_hash_token` is deterministic, 64 hex chars, and differs per
token; `create_session` returns a fresh url-safe token, adds exactly one
`AuthSession` whose hash matches the returned token with the expected expiry, and
commits; two creates return different tokens; `get_session_identity` maps a stub
user to the right `Identity` and a missing row to `None`; `revoke_session` issues
an update and commits; and the cookie helpers emit the expected attributes.
"""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Response

from app.auth import sessions
from app.auth.provider import Identity
from app.auth.sessions import (
    SESSION_COOKIE_NAME,
    _hash_token,
    clear_session_cookie,
    create_session,
    get_session_identity,
    revoke_session,
    set_session_cookie,
)
from app.config import settings
from app.models.auth_session import AuthSession
from app.models.user import Role, User


class FakeResult:
    """A stand-in for a SQLAlchemy `Result` that yields one preset row."""

    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class FakeAsyncSession:
    """A minimal async session that records adds, executes, and commits.

    Returns a `FakeResult` carrying a preset row for `execute`, and remembers
    the added objects, the executed statements, and how many times it committed
    so tests can assert against the session lifecycle with no database.
    """

    def __init__(self, row=None):
        self._row = row
        self.added_objects = []
        self.executed_statements = []
        self.commit_count = 0

    def add(self, instance):
        self.added_objects.append(instance)

    async def execute(self, statement):
        self.executed_statements.append(statement)
        return FakeResult(self._row)

    async def commit(self):
        self.commit_count += 1


def make_user() -> User:
    """Build an in-memory `User` for the resolve mapping tests."""
    return User(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        username="ada",
        email="ada@example.com",
        password_hash="not-checked-here",
        role=Role.AGENT,
        is_active=True,
    )


def test_hash_token_is_deterministic_and_64_hex_chars():
    """`_hash_token` returns a stable 64-char hex digest for the same token."""
    digest = _hash_token("a-raw-token")

    assert digest == _hash_token("a-raw-token")
    assert len(digest) == 64
    assert all(character in "0123456789abcdef" for character in digest)
    assert digest == hashlib.sha256(b"a-raw-token").hexdigest()


def test_hash_token_differs_for_different_tokens():
    """Different raw tokens hash to different digests."""
    assert _hash_token("token-one") != _hash_token("token-two")


async def test_create_session_stores_hash_and_returns_raw_token():
    """`create_session` adds one session row, hashes the token, and commits."""
    user = make_user()
    session = FakeAsyncSession()

    before = datetime.now(timezone.utc)
    raw_token = await create_session(session, user.id, lifetime_seconds=28800)
    after = datetime.now(timezone.utc)

    # A url-safe token came back (token_urlsafe(32) yields ~43 chars, no padding).
    assert isinstance(raw_token, str)
    assert len(raw_token) >= 32
    assert "=" not in raw_token

    assert len(session.added_objects) == 1
    stored_session = session.added_objects[0]
    assert isinstance(stored_session, AuthSession)
    assert stored_session.user_id == user.id
    # Only the hash is stored, and it matches the returned raw token.
    assert stored_session.token_hash == hashlib.sha256(
        raw_token.encode("utf-8")
    ).hexdigest()

    # expires_at is roughly now + lifetime, within the call window plus a margin.
    earliest = before + timedelta(seconds=28800)
    latest = after + timedelta(seconds=28800 + 2)
    assert earliest <= stored_session.expires_at <= latest

    assert session.commit_count == 1


async def test_create_session_defaults_to_configured_lifetime():
    """With no explicit lifetime, the configured `session_lifetime_seconds` is used."""
    user = make_user()
    session = FakeAsyncSession()

    before = datetime.now(timezone.utc)
    await create_session(session, user.id)
    after = datetime.now(timezone.utc)

    stored_session = session.added_objects[0]
    earliest = before + timedelta(seconds=settings.session_lifetime_seconds)
    latest = after + timedelta(seconds=settings.session_lifetime_seconds + 2)
    assert earliest <= stored_session.expires_at <= latest


async def test_create_session_returns_unique_tokens():
    """Two `create_session` calls return different random tokens."""
    user = make_user()

    first_token = await create_session(FakeAsyncSession(), user.id)
    second_token = await create_session(FakeAsyncSession(), user.id)

    assert first_token != second_token


async def test_get_session_identity_maps_user_to_identity():
    """A matching user row resolves to its `Identity`."""
    user = make_user()
    session = FakeAsyncSession(user)

    identity = await get_session_identity(session, "a-raw-token")

    assert identity == Identity(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        username=user.username,
    )
    assert len(session.executed_statements) == 1


async def test_get_session_identity_returns_none_when_no_row():
    """No matching session row (revoked/expired/unknown) resolves to `None`."""
    session = FakeAsyncSession(None)

    identity = await get_session_identity(session, "a-raw-token")

    assert identity is None
    assert len(session.executed_statements) == 1


async def test_revoke_session_issues_update_and_commits():
    """`revoke_session` runs an UPDATE statement and commits."""
    session = FakeAsyncSession()

    await revoke_session(session, "a-raw-token")

    assert len(session.executed_statements) == 1
    statement = session.executed_statements[0]
    assert statement.__visit_name__ == "update"
    assert statement.table.name == "auth_sessions"
    assert session.commit_count == 1


def test_set_session_cookie_default_attributes():
    """Default cookie carries HttpOnly, SameSite=lax, Max-Age, Path, and no Secure."""
    response = Response()

    set_session_cookie(response, "a-raw-token")

    set_cookie_header = response.headers["set-cookie"]
    assert SESSION_COOKIE_NAME in set_cookie_header
    assert "a-raw-token" in set_cookie_header
    assert "HttpOnly" in set_cookie_header
    assert "SameSite=lax" in set_cookie_header
    assert "Max-Age=28800" in set_cookie_header
    assert "Path=/" in set_cookie_header
    assert "Secure" not in set_cookie_header


def test_set_session_cookie_adds_secure_when_enabled():
    """Toggling `session_cookie_secure` on adds the Secure flag."""
    response = Response()
    original_secure = settings.session_cookie_secure
    settings.session_cookie_secure = True
    try:
        set_session_cookie(response, "a-raw-token")
    finally:
        settings.session_cookie_secure = original_secure

    assert "Secure" in response.headers["set-cookie"]


def test_clear_session_cookie_expires_the_cookie():
    """`clear_session_cookie` expires the cookie (Max-Age=0)."""
    response = Response()

    clear_session_cookie(response)

    set_cookie_header = response.headers["set-cookie"]
    assert SESSION_COOKIE_NAME in set_cookie_header
    assert "Max-Age=0" in set_cookie_header


def test_cookie_name_is_pf_session():
    """The single cookie-name constant is `pf_session`."""
    assert SESSION_COOKIE_NAME == "pf_session"
    assert sessions.SESSION_COOKIE_NAME == "pf_session"
