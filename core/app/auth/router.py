"""The auth HTTP surface: log in, log out, and report the current identity.

This is the thin route layer that wires together the auth ingredients the earlier
epics built in isolation — the pluggable provider (Epic 4), server-side sessions
(Epic 5), the RBAC matrix (Epic 6), and the auth dependencies (Epic 7). It adds no
new auth logic of its own; it only composes those pieces, exactly as
`dependencies.py` composed the ones before it.

Three endpoints under `/api/auth`:

- `POST /login` authenticates the credentials, mints a session, sets the
  `pf_session` cookie, and returns the signed-in identity with its capabilities.
- `POST /logout` revokes the presented session (idempotent) and clears the cookie.
- `GET /me` returns the same identity body for the currently signed-in caller, or
  inherits the 401 from `require_authenticated` when nobody is signed in.

Login and `me` return the **identical body shape**, built once in
`_identity_response`: the user's public fields plus a flat, sorted array of the
capability strings the role holds. Raw `UUID`/`StrEnum` values are returned as-is
and FastAPI's encoder serializes them, the style `health.py` uses.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from .dependencies import require_authenticated
from .provider import AuthProvider, Identity, LocalPasswordAuthProvider
from .rbac import CAPABILITIES
from .sessions import (
    SESSION_COOKIE_NAME,
    clear_session_cookie,
    create_session,
    revoke_session,
    set_session_cookie,
)

router = APIRouter(prefix="/api/auth")


class LoginRequest(BaseModel):
    """The login request body: a username and password to authenticate."""

    username: str
    password: str


def get_auth_provider() -> AuthProvider:
    """Return the authentication provider login should use.

    A FastAPI dependency so the pluggable seam stays a seam: production uses the
    local password provider, while tests can swap in a fixed-`Identity` stub via
    `app.dependency_overrides`. A future OIDC provider would be returned here
    instead, with no change to the login route.
    """
    return LocalPasswordAuthProvider()


def _identity_response(identity: Identity) -> dict:
    """Build the shared response body for both login and `me`.

    Returns the signed-in user's public fields plus a flat, sorted array of the
    capability strings the role holds (per the RBAC matrix). Raw `UUID`/`StrEnum`
    values are left as-is for FastAPI's encoder to serialize.
    """
    capabilities = sorted(
        capability.value for capability in CAPABILITIES[identity.role]
    )
    return {
        "user": {
            "id": identity.user_id,
            "username": identity.username,
            "role": identity.role,
            "tenant_id": identity.tenant_id,
        },
        "capabilities": capabilities,
    }


@router.post("/login")
async def login(
    credentials: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    provider: AuthProvider = Depends(get_auth_provider),
) -> dict:
    """Authenticate the credentials, start a session, and return the identity.

    On success: mints a server-side session for the authenticated user, sets the
    `pf_session` cookie, and returns the identity body (user fields plus
    capabilities). On any failure the provider returns `None`, and a single
    generic `401 {"detail": "invalid credentials"}` is raised so the response
    never leaks which check failed.
    """
    identity = await provider.authenticate(
        db, credentials.username, credentials.password
    )
    if identity is None:
        raise HTTPException(status_code=401, detail="invalid credentials")

    raw_token = await create_session(db, identity.user_id)
    set_session_cookie(response, raw_token)
    return _identity_response(identity)


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Revoke the presented session (if any) and clear the cookie.

    Reads the `pf_session` cookie; when present, revokes that session (idempotent
    — revoking an unknown or already-revoked token is a harmless no-op). The
    cookie is always cleared. Logout is intentionally not guarded: clearing a
    non-session is harmless, so it always returns `200 {"detail": "logged out"}`.
    """
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_token is not None:
        await revoke_session(db, raw_token)
    clear_session_cookie(response)
    return {"detail": "logged out"}


@router.get("/me")
async def get_me(
    identity: Identity = Depends(require_authenticated),
) -> dict:
    """Return the current identity body, mirroring login's shape exactly.

    The 401 for no/expired/revoked session is inherited from
    `require_authenticated` for free.
    """
    return _identity_response(identity)
