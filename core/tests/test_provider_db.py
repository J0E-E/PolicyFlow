"""Real-database tests for the local password auth provider (Epic 12).

Re-proves `LocalPasswordAuthProvider.authenticate` (`core/app/auth/provider.py`)
against the migrated container database — real SQL, a real bcrypt hash on the
seeded user — covering the success path and the standard failure cases (wrong
password, unknown username, inactive user, case-sensitive mismatch). Every miss
must return `None` so login failures stay generic.

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no
`@pytest.mark.asyncio` decorator.
"""

from app.auth.provider import LocalPasswordAuthProvider

from .factories import insert_active_user

KNOWN_PASSWORD = "correct horse battery staple"


async def test_authenticate_succeeds_for_active_user(db_session):
    """Correct username and password return an `Identity` matching the user."""
    user = await insert_active_user(db_session, password=KNOWN_PASSWORD)

    identity = await LocalPasswordAuthProvider().authenticate(
        db_session, user.username, KNOWN_PASSWORD
    )

    assert identity is not None
    assert identity.user_id == user.id
    assert identity.tenant_id == user.tenant_id
    assert identity.role == user.role
    assert identity.username == user.username


async def test_authenticate_wrong_password_returns_none(db_session):
    """A wrong password returns `None`."""
    user = await insert_active_user(db_session, password=KNOWN_PASSWORD)

    identity = await LocalPasswordAuthProvider().authenticate(
        db_session, user.username, "the wrong password"
    )

    assert identity is None


async def test_authenticate_unknown_username_returns_none(db_session):
    """An unknown username returns `None`."""
    identity = await LocalPasswordAuthProvider().authenticate(
        db_session, "nobody-by-this-name", KNOWN_PASSWORD
    )

    assert identity is None


async def test_authenticate_inactive_user_returns_none(db_session):
    """An inactive user with the correct password still returns `None`."""
    user = await insert_active_user(
        db_session, password=KNOWN_PASSWORD, is_active=False
    )

    identity = await LocalPasswordAuthProvider().authenticate(
        db_session, user.username, KNOWN_PASSWORD
    )

    assert identity is None


async def test_authenticate_is_case_sensitive_on_username(db_session):
    """An upper-cased username does not match the exact stored one."""
    user = await insert_active_user(db_session, password=KNOWN_PASSWORD)

    identity = await LocalPasswordAuthProvider().authenticate(
        db_session, user.username.upper(), KNOWN_PASSWORD
    )

    assert identity is None
