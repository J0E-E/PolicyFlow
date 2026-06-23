"""The demo HTTP surface: the public tenant list and passwordless assume-persona.

Two endpoints under `/api`, at different sub-paths:

- `GET /tenants` returns the canonical tenant list (`slug`, `display_name`,
  `brand_primary_color`, `product_lines`) in registry order (Sunshine, then
  Florida). It is **public** and **DB-free**: it has no auth dependency and no
  `get_db` dependency, since it runs before anyone signs in and reads only the
  in-memory registry. The `product_lines` array lets both intake forms offer the
  per-tenant choices and the server validate submitted keys.
- `POST /demo/assume-persona` is the passwordless front door **and** every later
  role switch. It takes `{tenant_slug, role}`, resolves a **seeded** demo user
  deterministically, re-mints the server session as that real user, sets the
  `pf_session` cookie, and returns the same identity body login returns. Because
  the visitor literally becomes a distinct seeded user, "RBAC enforced per assumed
  role" is literally true. This route is DB-backed (it reads the seeded users).

The tenant-list body uses the `{"tenants": [...]}` envelope, mirroring the tenant
router's `{"tenant": {...}}` / `{"settings": {...}}` style. The router carries the
`/api` prefix (not `/api/demo`) so the two demo endpoints live at different
sub-paths under `/api`.

The assume-persona flow is kept **whole** — one coherent auth flow that resolves
the persona, revokes any prior session, mints the new one, and audits both ends —
because splitting it would scatter a single correctness-critical transaction.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit.records import EventType, Outcome
from ..audit.service import record_audit_event
from ..auth.identity import build_identity_response
from ..auth.provider import Identity
from ..auth.sessions import (
    SESSION_COOKIE_NAME,
    create_session,
    get_session_identity,
    revoke_session,
    set_session_cookie,
)
from ..config import settings
from ..db import get_db
from ..models.tenant import Tenant
from ..models.user import Role, User
from ..tenancy.registry import TENANTS, tenant_by_slug
from .instantiation import ensure_session_leads
from .session import (
    DemoSessionStatus,
    ensure_demo_session,
    read_demo_session_state,
)

router = APIRouter(prefix="/api")


class AssumePersonaRequest(BaseModel):
    """The assume-persona request body: which tenant and which role to become.

    `role` is typed as the `Role` enum, so an unrecognized role value is rejected
    with a `422` by FastAPI's request validation before the route runs — no manual
    role check is needed.
    """

    tenant_slug: str
    role: Role


@router.get("/tenants")
async def list_tenants() -> dict:
    """Return the public tenant list straight from the registry.

    Loops the registry's `TENANTS` tuple — so the order is Sunshine, then
    Florida — and returns exactly the four public fields per tenant under the
    `{"tenants": [...]}` envelope. Nothing here reads the database or exposes any
    person-level data: the registry is pure in-memory configuration, so the
    response carries only each tenant's `slug`, `display_name`,
    `brand_primary_color`, and `product_lines` (each `{key, label}`).
    """
    return {
        "tenants": [
            {
                "slug": tenant.slug,
                "display_name": tenant.display_name,
                "brand_primary_color": tenant.brand_primary_color,
                "product_lines": [
                    {"key": product_line.key, "label": product_line.label}
                    for product_line in tenant.product_lines
                ],
            }
            for tenant in TENANTS
        ]
    }


@router.get("/demo/session")
async def get_demo_session(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Report the caller's demo-session state for the live masthead countdown.

    **Public** and read-only: no auth dependency and no mint or cookie write — it
    only resolves the `pf_demo_session` cookie to one of three states the frontend
    needs (`active` / `expired` / `none`). The masthead fetches this once on mount
    and then ticks the countdown locally from `expires_at`, so no polling.

    The body is the PII-free `DemoSessionState` shape, with `DemoSessionState.id`
    surfaced as `demo_session_id`. Fields absent for a status are omitted: `none`
    returns just `{"status": "none"}`; `expired` adds `expires_at` and
    `last_tenant_slug` (the seam the graceful-expiry epic reuses to preserve the
    tenant on a fresh mint); `active` carries all four fields.
    """
    state = await read_demo_session_state(request, db)
    if state.status is DemoSessionStatus.NONE:
        return {"status": state.status.value}

    body: dict = {"status": state.status.value}
    if state.id is not None:
        body["demo_session_id"] = str(state.id)
    if state.expires_at is not None:
        body["expires_at"] = state.expires_at.isoformat()
    if state.last_tenant_slug is not None:
        body["last_tenant_slug"] = state.last_tenant_slug
    return body


@router.post("/demo/assume-persona")
async def assume_persona(
    request: Request,
    response: Response,
    persona_request: AssumePersonaRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Become a seeded persona: revoke any prior session, mint a new one, audit both.

    The one seam serving both the passwordless front door (tenant-pick = "assume
    Agent") and every later role switch. In order:

    1. If `demo_login_enabled` is off, refuse with `403 {"detail": "demo login is
       disabled"}` — the route exists but is the off-switch for a non-demo
       deployment.
    2. Resolve the seeded persona for `{tenant_slug, role}` (deterministic, lowest
       username for the two-Agent tie-break). A tenant-scoped role with an unknown
       slug → `404`; Platform Admin ignores the slug and resolves the global
       tenantless admin.
    3. If a `pf_session` cookie is present, resolve its identity **before** revoking
       (a revoked row stops resolving), revoke that session, and — if it resolved —
       record an `auth.logout` / `success` audit event routed by the **old**
       identity's `tenant_id`. This is the role-switch re-mint path.
    4. Mint a fresh session for the persona, set the `pf_session` cookie, and record
       an `auth.login` / `success` audit event routed by the **new** persona's
       `tenant_id` (a tenant user lands in their tenant store; the tenantless
       Platform Admin lands in the platform store).
    5. Return the persona's identity body — the same shape login and `me` return.

    No password ever crosses the wire: only `{tenant_slug, role}` go in, and the
    response is the same PII-free identity body login already returns.
    """
    if not settings.demo_login_enabled:
        raise HTTPException(status_code=403, detail="demo login is disabled")

    persona = await _get_seeded_persona(
        db, persona_request.tenant_slug, persona_request.role
    )

    # Role-switch re-mint: retire any prior session before minting the new one.
    # Resolve the old identity first (a revoked session no longer resolves) so the
    # logout is audited under the tenant the visitor was previously in.
    prior_token = request.cookies.get(SESSION_COOKIE_NAME)
    if prior_token is not None:
        prior_identity = await get_session_identity(db, prior_token)
        await revoke_session(db, prior_token)
        if prior_identity is not None:
            await record_audit_event(
                tenant_id=prior_identity.tenant_id,
                actor_user_id=prior_identity.user_id,
                actor_role=prior_identity.role,
                event_type=EventType.AUTH_LOGOUT,
                outcome=Outcome.SUCCESS,
            )

    raw_token = await create_session(db, persona.id)
    set_session_cookie(response, raw_token)

    persona_identity = Identity(
        user_id=persona.id,
        tenant_id=persona.tenant_id,
        role=persona.role,
        username=persona.username,
    )
    await record_audit_event(
        tenant_id=persona_identity.tenant_id,
        actor_user_id=persona_identity.user_id,
        actor_role=persona_identity.role,
        event_type=EventType.AUTH_LOGIN,
        outcome=Outcome.SUCCESS,
    )

    # Reuse-or-mint the demo-visit session that spans this whole visit (every role
    # and tenant switch). A tenant-scoped persona refreshes `last_tenant_slug`; the
    # tenantless Platform Admin passes `None` so the remembered tenant is unchanged.
    visit_tenant_slug = (
        persona_request.tenant_slug
        if persona_identity.tenant_id is not None
        else None
    )
    demo_state = await ensure_demo_session(
        db, request, response, tenant_slug=visit_tenant_slug
    )

    # Instantiate this visit's private, claimable New queue in the assumed tenant —
    # idempotently, ledger-guarded — so a tenant-scoped visitor lands on their own
    # working queue (Epic 7). Tenant-scoped personas only: the tenantless Platform
    # Admin has no tenant queue to seed and skips it. `demo_state.id` is a plain UUID
    # on a frozen dataclass (no ORM row survives), and `ensure_session_leads` opens
    # its own scoped transaction via `get_public_tenant_db` and resets it on exit —
    # so `db` is back on the default login role for `build_identity_response` below.
    if persona_identity.tenant_id is not None and demo_state.id is not None:
        await ensure_session_leads(
            db, tenant_by_slug(persona_request.tenant_slug), demo_state.id
        )

    return await build_identity_response(db, persona_identity)


async def _get_seeded_persona(
    db: AsyncSession, tenant_slug: str, role: Role
) -> User:
    """Resolve the seeded `User` for a `{tenant_slug, role}` pair, deterministically.

    Two branches:

    - **Platform Admin** ignores `tenant_slug` (the admin belongs to no tenant) and
      resolves the single global user where `role == PLATFORM_ADMIN` and
      `tenant_id IS NULL`. An unknown slug does **not** 404 for this role.
    - **Any tenant-scoped role** registry-validates `tenant_slug` first (an unknown
      slug → `404`), looks up the `Tenant` row by slug for its `tenant_id`, then
      picks the persona with that `(tenant_id, role)` and the **lowest username**.
      Ordering by username is the deterministic tie-break for the two seeded Agents
      (`agent.one` wins over `agent.two`), and falls out harmlessly for the
      single-user roles.

    A missing persona row → `404`: the demo always seeds every persona, so an
    absent one is a misconfiguration, not a client error to leak details about.
    """
    if role is Role.PLATFORM_ADMIN:
        persona = (
            await db.execute(
                select(User).where(
                    User.role == Role.PLATFORM_ADMIN,
                    User.tenant_id.is_(None),
                )
            )
        ).scalar_one_or_none()
        if persona is None:
            raise HTTPException(status_code=404, detail="persona not found")
        return persona

    try:
        tenant_by_slug(tenant_slug)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown tenant")

    tenant = (
        await db.execute(select(Tenant).where(Tenant.slug == tenant_slug))
    ).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="unknown tenant")

    persona = (
        await db.execute(
            select(User)
            .where(User.tenant_id == tenant.id, User.role == role)
            .order_by(User.username)
            .limit(1)
        )
    ).scalar_one_or_none()
    if persona is None:
        raise HTTPException(status_code=404, detail="persona not found")
    return persona
