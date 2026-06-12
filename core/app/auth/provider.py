"""The pluggable authentication seam: `AuthProvider` plus the local password one.

`AuthProvider` is the interface login calls; `LocalPasswordAuthProvider` is the
one MVP implementation, verifying a password against the stored bcrypt hash. The
point of the seam is future-proofing without future work — a later
`OIDCAuthProvider` can satisfy the same shape (mapping the existing
`external_identity` column on `User`) with no change to callers. No OAuth/OIDC is
built here.

Each provider takes the database session as an argument (matching the
`get_db`/sessions convention), which keeps it stateless and trivially testable.
Every authentication miss — unknown user, inactive user, wrong password — returns
`None` so login failures stay generic and never leak which check failed.
"""

import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.user import Role, User
from .passwords import verify_password


@dataclass(frozen=True)
class Identity:
    """The canonical identity of a signed-in user.

    Frozen (immutable) so it can't be tampered with as it's passed around the
    request. Later epics (sessions, the auth dependencies, the auth router) import
    this value rather than redeclaring their own current-identity type.
    """

    user_id: uuid.UUID
    tenant_id: uuid.UUID | None
    role: Role
    username: str


class AuthProvider(Protocol):
    """The pluggable authentication interface that login calls.

    A provider takes a database session, a username, and a password, and returns
    the matching `Identity` on success or `None` on any failure. The local
    password provider is the MVP implementation; a future OIDC provider would
    satisfy this same shape, mapping the `external_identity` column instead of a
    local password — with no change to the callers that depend on this protocol.
    """

    async def authenticate(
        self, db: AsyncSession, username: str, password: str
    ) -> Identity | None:
        """Return the authenticated `Identity`, or `None` if authentication fails."""
        ...


class LocalPasswordAuthProvider:
    """Authenticates a user against the local bcrypt password hash.

    Looks up the active user by an exact, case-sensitive username, verifies the
    supplied password against the stored hash, and returns an `Identity`. Any
    miss — no such active user, or a wrong password — returns `None` so the
    failure stays generic.
    """

    async def authenticate(
        self, db: AsyncSession, username: str, password: str
    ) -> Identity | None:
        """Look up the active user and verify the password, or return `None`.

        Filters on `is_active = true` and an exact, case-sensitive username match.
        Returns `None` when no such user exists or the password does not verify;
        otherwise returns the user's `Identity`.
        """
        active_user = (
            await db.execute(
                select(User).where(
                    User.username == username,
                    User.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()

        if active_user is None:
            return None

        if not verify_password(password, active_user.password_hash):
            return None

        return Identity(
            user_id=active_user.id,
            tenant_id=active_user.tenant_id,
            role=active_user.role,
            username=active_user.username,
        )
