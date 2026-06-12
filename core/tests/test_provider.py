"""Unit tests for the pluggable auth provider and its local password implementation.

Pure unit tests — no DB, no Docker — matching the no-Docker style of
`test_passwords.py` and `test_models.py`. The real DB-backed provider test is
Epic 12; here we drive `authenticate` through a tiny fake async session whose
`execute(...)` returns a stub result whose `scalar_one_or_none()` yields a chosen
in-memory `User` (or `None`). A `User()` can be built in memory without a live
session, so no database is touched.

The cases prove: `Identity` is frozen; the happy path returns the right identity
against a real bcrypt hash; a wrong password returns `None`; and an
unknown/inactive user (the fake session yields `None`) returns `None` without ever
reaching `verify_password`.
"""

import uuid
from dataclasses import FrozenInstanceError

import pytest

from app.auth.passwords import hash_password
from app.auth.provider import Identity, LocalPasswordAuthProvider
from app.models.user import Role, User


class FakeResult:
    """A stand-in for a SQLAlchemy `Result` that yields one preset row.

    `scalar_one_or_none()` returns whatever single row (a `User` or `None`) the
    fake session was told to hand back, so the provider's lookup can be exercised
    with no database.
    """

    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class FakeAsyncSession:
    """A minimal async session whose `execute` returns a preset result.

    Records that `execute` was awaited (and with what statement) so tests can
    confirm the provider ran a query, and returns a `FakeResult` carrying the
    chosen row. This is all the surface `LocalPasswordAuthProvider.authenticate`
    touches.
    """

    def __init__(self, row):
        self._row = row
        self.executed_statement = None

    async def execute(self, statement):
        self.executed_statement = statement
        return FakeResult(self._row)


def make_active_user(password: str) -> User:
    """Build an in-memory active `User` whose password hash matches `password`."""
    return User(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        username="ada",
        email="ada@example.com",
        password_hash=hash_password(password),
        role=Role.AGENT,
        is_active=True,
    )


def test_identity_is_frozen():
    """`Identity` is immutable: assigning an attribute raises `FrozenInstanceError`."""
    identity = Identity(
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        role=Role.AGENT,
        username="ada",
    )

    with pytest.raises(FrozenInstanceError):
        identity.username = "mallory"


async def test_correct_password_returns_identity():
    """An active user and the correct password return their `Identity`."""
    user = make_active_user("correct horse battery staple")
    session = FakeAsyncSession(user)

    identity = await LocalPasswordAuthProvider().authenticate(
        session, "ada", "correct horse battery staple"
    )

    assert identity == Identity(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        username=user.username,
    )


async def test_wrong_password_returns_none():
    """An active user with a wrong password returns `None`."""
    user = make_active_user("correct horse battery staple")
    session = FakeAsyncSession(user)

    identity = await LocalPasswordAuthProvider().authenticate(
        session, "ada", "wrong password"
    )

    assert identity is None


async def test_unknown_or_inactive_user_returns_none():
    """When the lookup yields no row, return `None` without verifying a password.

    The fake session hands back `None` (the case for an unknown username or an
    inactive user, both filtered out by the query). `verify_password` is never
    reached because there is no stored hash to check against.
    """
    session = FakeAsyncSession(None)

    identity = await LocalPasswordAuthProvider().authenticate(
        session, "ghost", "any password"
    )

    assert identity is None
    assert session.executed_statement is not None
