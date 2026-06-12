"""Real-database tests for the server-side session module (Epic 12).

Re-proves `core/app/auth/sessions.py` against the migrated container database —
real SQL, the real `expires_at > now()` clock comparison — rather than the
in-memory fakes the module was first proven with. Covers the create → resolve →
revoke happy path plus the standard expiry, revocation, and unknown-token edge
cases.

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no
`@pytest.mark.asyncio` decorator.
"""

from app.auth.sessions import (
    create_session,
    get_session_identity,
    revoke_session,
)

from .factories import insert_active_user


async def test_create_session_resolves_to_seeded_identity(db_session):
    """A freshly created session resolves to the seeded user's `Identity`."""
    user = await insert_active_user(db_session)

    raw_token = await create_session(db_session, user.id)
    identity = await get_session_identity(db_session, raw_token)

    assert identity is not None
    assert identity.user_id == user.id
    assert identity.tenant_id == user.tenant_id
    assert identity.role == user.role
    assert identity.username == user.username


async def test_expired_session_does_not_resolve(db_session):
    """A session forged already-expired resolves to `None` (the real clock filter)."""
    user = await insert_active_user(db_session)

    raw_token = await create_session(db_session, user.id, lifetime_seconds=-1)

    assert await get_session_identity(db_session, raw_token) is None


async def test_revoked_session_does_not_resolve(db_session):
    """A revoked session no longer resolves."""
    user = await insert_active_user(db_session)
    raw_token = await create_session(db_session, user.id)

    await revoke_session(db_session, raw_token)

    assert await get_session_identity(db_session, raw_token) is None


async def test_unknown_token_does_not_resolve(db_session):
    """An unrecognised token resolves to `None`."""
    assert await get_session_identity(db_session, "not-a-real-token") is None


async def test_double_revoke_is_a_harmless_no_op(db_session):
    """Revoking an already-revoked token, or an unknown token, raises nothing."""
    user = await insert_active_user(db_session)
    raw_token = await create_session(db_session, user.id)

    await revoke_session(db_session, raw_token)
    await revoke_session(db_session, raw_token)
    await revoke_session(db_session, "not-a-real-token")

    assert await get_session_identity(db_session, raw_token) is None
