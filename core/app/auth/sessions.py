"""Server-side session plumbing: create, resolve, and revoke login sessions.

On login we mint an opaque random token, store **only its SHA-256 hash** in the
`platform.auth_sessions` table, and hand the raw token to the browser in the
`pf_session` cookie. A later request presents that cookie; we hash it, look the
row up, and recover the current `Identity`. Logout stamps `revoked_at`; expired
or revoked rows stop resolving.

This module is the plumbing only — it mounts no HTTP route (Epic 8) and does not
read the cookie off the request (Epic 7). The three session functions are
self-contained discrete operations: each commits its own transaction, so callers
don't manage one. `expires_at` is written from the app's UTC clock while
resolution compares against the database clock (`func.now()`); that is fine
because the app and the database share one host and one wall clock.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from fastapi import Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.auth_session import AuthSession
from ..models.user import User
from .provider import Identity

# The single place the session cookie name lives.
SESSION_COOKIE_NAME = "pf_session"


def set_session_cookie(response: Response, raw_token: str) -> None:
    """Write the `pf_session` cookie carrying the raw session token.

    Settings are read inside the call so a per-environment or per-test override
    of the lifetime or the Secure flag is honored.
    """
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        max_age=settings.session_lifetime_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    """Expire the `pf_session` cookie on the client (used on logout)."""
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
    )


def _hash_token(raw_token: str) -> str:
    """Return the SHA-256 hex digest of a raw token.

    The raw token is never stored; only this digest goes to the database, and
    lookups hash the presented token the same way before comparing.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


async def create_session(
    db: AsyncSession, user: User, *, lifetime_seconds: int | None = None
) -> str:
    """Mint a session for `user`, store its token hash, and return the raw token.

    Generates an opaque url-safe token, records a new `AuthSession` row holding
    only the token's SHA-256 hash and its expiry, commits, and hands back the
    raw token for the caller to set in the cookie. When `lifetime_seconds` is
    `None` the configured `session_lifetime_seconds` is used; an explicit value
    (including a negative one, to forge an already-expired session in tests)
    overrides it.
    """
    if lifetime_seconds is None:
        lifetime_seconds = settings.session_lifetime_seconds

    raw_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=lifetime_seconds)

    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=_hash_token(raw_token),
            expires_at=expires_at,
        )
    )
    await db.commit()

    return raw_token


async def get_session_identity(
    db: AsyncSession, raw_token: str
) -> Identity | None:
    """Resolve a raw session token back to the current `Identity`, or `None`.

    Looks up the user joined to a session whose token hash matches and which is
    neither revoked nor expired (validity is judged against the database clock).
    Returns `None` when no such valid session exists; otherwise builds the
    user's `Identity`, matching the provider's mapping.
    """
    matching_user = (
        await db.execute(
            select(User)
            .join(AuthSession, AuthSession.user_id == User.id)
            .where(
                AuthSession.token_hash == _hash_token(raw_token),
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > sa.func.now(),
            )
        )
    ).scalar_one_or_none()

    if matching_user is None:
        return None

    return Identity(
        user_id=matching_user.id,
        tenant_id=matching_user.tenant_id,
        role=matching_user.role,
        username=matching_user.username,
    )


async def revoke_session(db: AsyncSession, raw_token: str) -> None:
    """Revoke the session for a raw token by stamping `revoked_at`, then commit.

    Idempotent: re-revoking an already-revoked (or unknown) token matches no row
    and is a harmless no-op.
    """
    await db.execute(
        update(AuthSession)
        .where(
            AuthSession.token_hash == _hash_token(raw_token),
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=sa.func.now())
    )
    await db.commit()
