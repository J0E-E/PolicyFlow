"""FastAPI auth dependencies: the reusable gate every protected endpoint leans on.

A FastAPI *dependency* is a small function FastAPI runs before a route, wiring its
result into the handler (or raising 401/403 to stop the request). This module adds
no new auth logic of its own — it **composes** what the earlier epics already
built into one enforcement seam:

- `get_current_identity` reads the `pf_session` cookie off the request and turns it
  into the current `Identity` via `get_session_identity` (Epic 5), or `None`.
- `require_authenticated` rejects the unauthenticated caller with a 401.
- `require_capability(capability)` is a factory: it returns a dependency that
  inherits the 401 path and then checks the matrix (Epic 6), rejecting a signed-in
  caller who lacks the capability with a 403.

Error bodies are FastAPI's flat shape: `401 {"detail": "not authenticated"}` and
`403 {"detail": "insufficient permissions"}`. No `WWW-Authenticate` header.

Names are reused from their single source of truth — `Identity` from
`auth.provider`, `has_capability`/`Capability` from `auth.rbac`,
`SESSION_COOKIE_NAME`/`get_session_identity` from `auth.sessions`, and `get_db`
from `app.db`. Nothing is redeclared here.
"""

from typing import Callable

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models.user import Role
from .provider import Identity
from .rbac import Capability, has_capability
from .sessions import SESSION_COOKIE_NAME, get_session_identity


async def get_current_identity(
    request: Request, db: AsyncSession = Depends(get_db)
) -> Identity | None:
    """Resolve the `pf_session` cookie to the current `Identity`, or `None`.

    Reads the raw session token from the cookie; with no cookie there is nobody
    signed in, so returns `None`. Otherwise hands the token to
    `get_session_identity`, which returns the `Identity` for a valid session or
    `None` for one that is expired, revoked, or unrecognized.
    """
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_token is None:
        return None
    return await get_session_identity(db, raw_token)


async def require_authenticated(
    identity: Identity | None = Depends(get_current_identity),
) -> Identity:
    """Return the current `Identity`, or raise 401 if nobody is signed in.

    The 401 seam every protected route inherits: when `get_current_identity`
    found no valid session, the request is rejected with
    `{"detail": "not authenticated"}`.
    """
    if identity is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return identity


def require_capability(capability: Capability) -> Callable:
    """Build a dependency that requires a signed-in caller to hold `capability`.

    Returns a FastAPI dependency that first inherits the 401 path via
    `require_authenticated`, then checks the RBAC matrix: a caller whose role
    lacks `capability` is rejected with `{"detail": "insufficient permissions"}`
    (403); otherwise the `Identity` is returned for the route to use.
    """

    async def check_capability(
        identity: Identity = Depends(require_authenticated),
    ) -> Identity:
        if not has_capability(identity.role, capability):
            raise HTTPException(
                status_code=403, detail="insufficient permissions"
            )
        return identity

    return check_capability


async def require_platform_admin(
    identity: Identity = Depends(require_authenticated),
) -> Identity:
    """Return the current `Identity`, or raise 403 unless it is the Platform Admin.

    The gate for the platform carve-out: the cross-tenant operational read path is
    reachable **only** by the Platform Admin role. It inherits the 401 path via
    `require_authenticated` (no session → not authenticated), then checks the role
    directly — any other signed-in role is rejected with
    `{"detail": "insufficient permissions"}` (403).

    This is a deliberate **role check, not a capability cell**: the RBAC matrix in
    `rbac.py` stays untouched, because the carve-out is a single privileged path
    rather than a per-role capability (per the phase's TDD decision 8).
    """
    if identity.role is not Role.PLATFORM_ADMIN:
        raise HTTPException(status_code=403, detail="insufficient permissions")
    return identity
