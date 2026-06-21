"""The demo-session lifecycle: mint, reuse, and read-only resolve.

A visit to the demo is identified by a server-side `platform.demo_sessions` row,
carried to the browser in its own `pf_demo_session` cookie (the **raw** session
UUID, independent of the login `pf_session`). This module is the one place that
mints, reuses, and reads that identity:

- `ensure_demo_session(db, request, response, *, tenant_slug=None)` — the single
  **mint point**. It reuses the cookie's live session (refreshing
  `last_tenant_slug` when a slug is given) or mints a fresh row, sets the cookie,
  and logs one INFO line. Called by `assume-persona` (this epic) and, later,
  public intake + the fresh-session button.
- `current_demo_session(request)` — a read-only resolve of the cookie to a live,
  unexpired session, or `None`. No mint, no cookie write; used on the read paths
  (here, the agent intake route tags a created lead with the resolved id).

Both return a `DemoSessionState` value, never the ORM row, so callers depend only
on the small `{id, expires_at, last_tenant_slug, status}` shape. Validity is
judged against the **database** clock (`func.now()`), matching `auth_sessions`.
The cookie's `max_age` is set **once at mint** to the configured lifetime and is
**not** slid on reuse — a demo visit is a fixed 24-hour window.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

import sqlalchemy as sa
from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.demo_session import DemoSession

logger = logging.getLogger(__name__)

# The single place the demo-session cookie name lives.
DEMO_SESSION_COOKIE_NAME = "pf_demo_session"


class DemoSessionStatus(str, Enum):
    """Whether the cookie resolves to a live session, an expired one, or none."""

    ACTIVE = "active"
    EXPIRED = "expired"
    NONE = "none"


@dataclass(frozen=True)
class DemoSessionState:
    """A PII-free view of the current demo session for callers and the frontend.

    `status` is `ACTIVE` for a live session (then `id` / `expires_at` are set),
    `EXPIRED` when the cookie names a session whose window has passed, and `NONE`
    when there is no usable session at all.
    """

    status: DemoSessionStatus
    id: Optional[uuid.UUID] = None
    expires_at: Optional[datetime] = None
    last_tenant_slug: Optional[str] = None


def _set_demo_session_cookie(response: Response, raw_id: str) -> None:
    """Write the `pf_demo_session` cookie carrying the raw session UUID.

    Mirrors `auth.sessions.set_session_cookie`: HttpOnly, SameSite=Lax, `path=/`,
    and Secure per `session_cookie_secure`. `max_age` is the demo lifetime and is
    written only here — at mint — so the 24-hour window is fixed, never slid.
    Settings are read inside the call so a per-test override is honored.
    """
    response.set_cookie(
        key=DEMO_SESSION_COOKIE_NAME,
        value=raw_id,
        max_age=settings.demo_session_lifetime_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        path="/",
    )


def _parse_cookie_id(request: Request) -> Optional[uuid.UUID]:
    """Return the demo-session UUID from the cookie, or `None` if absent/malformed.

    A missing cookie or a value that is not a well-formed UUID both resolve to
    `None` (treated as "no session"), so a tampered cookie never raises.
    """
    raw_id = request.cookies.get(DEMO_SESSION_COOKIE_NAME)
    if raw_id is None:
        return None
    try:
        return uuid.UUID(raw_id)
    except ValueError:
        return None


async def _get_live_session(
    db: AsyncSession, session_id: uuid.UUID
) -> Optional[DemoSession]:
    """Load the `demo_sessions` row for `session_id` if it is unexpired, else `None`.

    Expiry is judged against the database clock (`func.now()`), matching how
    `auth_sessions` resolution compares times.
    """
    return (
        await db.execute(
            select(DemoSession).where(
                DemoSession.id == session_id,
                DemoSession.expires_at > sa.func.now(),
            )
        )
    ).scalar_one_or_none()


async def ensure_demo_session(
    db: AsyncSession,
    request: Request,
    response: Response,
    *,
    tenant_slug: Optional[str] = None,
) -> DemoSessionState:
    """Reuse the cookie's live demo session, or mint a fresh one — the mint point.

    If the cookie names a live, unexpired session: reuse it. When `tenant_slug` is
    given, refresh the row's `last_tenant_slug` (so a fresh session can later
    preserve the tenant). The cookie and `expires_at` are left untouched — reuse
    is silent and does not slide the window.

    Otherwise (no cookie, malformed, or expired): mint a new `demo_sessions` row
    with `expires_at = now + DEMO_SESSION_LIFETIME_SECONDS`, set the cookie to the
    raw id, log one INFO line, and return the new state.

    Commits its own transaction (mint or slug refresh), matching the auth-session
    plumbing's self-contained style.
    """
    session_id = _parse_cookie_id(request)
    if session_id is not None:
        live_session = await _get_live_session(db, session_id)
        if live_session is not None:
            if tenant_slug is not None and (
                live_session.last_tenant_slug != tenant_slug
            ):
                live_session.last_tenant_slug = tenant_slug
                await db.commit()
            return DemoSessionState(
                status=DemoSessionStatus.ACTIVE,
                id=live_session.id,
                expires_at=live_session.expires_at,
                last_tenant_slug=live_session.last_tenant_slug,
            )

    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=settings.demo_session_lifetime_seconds
    )
    minted = DemoSession(expires_at=expires_at, last_tenant_slug=tenant_slug)
    db.add(minted)
    await db.commit()
    await db.refresh(minted)

    _set_demo_session_cookie(response, str(minted.id))
    logger.info(
        "demo session minted: id=%s expires_at=%s",
        minted.id,
        minted.expires_at.isoformat(),
    )

    return DemoSessionState(
        status=DemoSessionStatus.ACTIVE,
        id=minted.id,
        expires_at=minted.expires_at,
        last_tenant_slug=minted.last_tenant_slug,
    )


async def current_demo_session(
    request: Request, db: AsyncSession
) -> Optional[DemoSessionState]:
    """Resolve the cookie to a live, unexpired demo session, or `None`. Read-only.

    No mint, no cookie write — this is the read path the tagging routes use to
    learn the caller's session id. Returns `None` when there is no cookie, the
    cookie is malformed, or the named session has expired (or never existed).
    """
    session_id = _parse_cookie_id(request)
    if session_id is None:
        return None

    live_session = await _get_live_session(db, session_id)
    if live_session is None:
        return None

    return DemoSessionState(
        status=DemoSessionStatus.ACTIVE,
        id=live_session.id,
        expires_at=live_session.expires_at,
        last_tenant_slug=live_session.last_tenant_slug,
    )
