"""The renewals HTTP surface: the on-demand sweep endpoints (P2.4 Epic 6/8).

`POST /api/renewals/aep-sweep` and `POST /api/renewals/anniversary-sweep` are the two
on-demand renewal sweeps: a **Platform Admin** button fires one sweep of one rule over
the caller's demo session in their currently-selected tenant, and gets back
`{generated, skipped}`. The two endpoints are identical save the rule they pass to
`generate_renewals` (`"aep"` vs `"anniversary"`), so they share the `_run_sweep` helper
below. AEP bypasses the Oct 15 – Dec 7 seasonal calendar (the on-demand button is always
in season, ADR 0004); the anniversary sweep applies the rolling 60-day window inside the
core. Neither writes an audit record — the outbox event trail is the record (ADR 0006),
mirroring the sibling `reset_demo_session`.

Scope comes entirely from the caller's demo session, not the request body:

- the demo session (`pf_demo_session` cookie) supplies the `demo_session_id` the sweep
  writes its renewals under — no live session → `409 "no active demo session"`;
- the session's `last_tenant_slug` names the single tenant swept — unset → `409 "no
  tenant selected"`.

The owning `tenant_id` is read from `platform.tenants` on the login-role session
**before** opening the scoped tenant write session, because the per-tenant role
`get_public_tenant_db` sets cannot see the `platform` schema — the same
read-tenant_id-before-scoping ordering `ensure_session_leads` uses. `generate_renewals`
then runs inside the scoped block, which commits on exit (the core never commits).
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import require_platform_admin
from ..auth.provider import Identity
from ..db import get_db
from ..demo.session import current_demo_session
from ..models.tenant import Tenant
from ..tenancy.registry import tenant_by_slug
from ..tenancy.scoping import get_public_tenant_db
from .service import generate_renewals

router = APIRouter(prefix="/api/renewals")


async def _run_sweep(request: Request, db: AsyncSession, *, rule: str) -> dict:
    """Run one renewal sweep of ``rule`` over the caller's demo session + tenant.

    The shared body behind both sweep endpoints (they differ only in ``rule``). It
    resolves the caller's demo session and the tenant it last selected, then runs
    `generate_renewals` for ``rule`` inside a scoped tenant write session:

    - no live demo session → `409 {"detail": "no active demo session"}`;
    - a session with no `last_tenant_slug` → `409 {"detail": "no tenant selected"}`.

    Returns the `{"generated": <int>, "skipped": <int>}` summary — a re-run reports the
    already-renewed policies as `skipped` (idempotent, ADR 0001).
    """
    state = await current_demo_session(request, db)
    if state is None or state.id is None:
        raise HTTPException(status_code=409, detail="no active demo session")
    if state.last_tenant_slug is None:
        raise HTTPException(status_code=409, detail="no tenant selected")

    tenant_slug = state.last_tenant_slug
    tenant_config = tenant_by_slug(tenant_slug)

    # Read the owning `tenant_id` on the login role **before** scoping: the scoped
    # tenant role set by `get_public_tenant_db` cannot read `platform.tenants`. A plain
    # scalar, so no ORM row survives into the scoped block (the `ensure_session_leads`
    # ordering).
    tenant_id: Optional[uuid.UUID] = (
        await db.execute(select(Tenant.id).where(Tenant.slug == tenant_slug))
    ).scalar_one_or_none()

    async with get_public_tenant_db(tenant_slug, db) as scoped:
        result = await generate_renewals(
            scoped,
            tenant_config,
            tenant_id=tenant_id,
            rule=rule,
            demo_session_id=state.id,
        )

    return {"generated": result["generated"], "skipped": result["skipped"]}


@router.post("/aep-sweep")
async def aep_sweep(
    request: Request,
    _admin: Identity = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run one AEP renewal sweep over the caller's demo session and selected tenant.

    Gated by `require_platform_admin` (inheriting its `401 "not authenticated"` /
    `403 "insufficient permissions"` paths). Runs `generate_renewals` for the `"aep"`
    rule, which bypasses the seasonal calendar (the on-demand button is always in
    season, ADR 0004). See `_run_sweep` for the shared session/tenant scoping and the
    `409` paths.
    """
    return await _run_sweep(request, db, rule="aep")


@router.post("/anniversary-sweep")
async def anniversary_sweep(
    request: Request,
    _admin: Identity = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run one anniversary renewal sweep over the caller's session and selected tenant.

    The sibling of `aep_sweep` (P2.4 Epic 8): same `require_platform_admin` gate and
    same session/tenant scoping via `_run_sweep`, but runs `generate_renewals` for the
    `"anniversary"` rule — which selects anniversary-line policies falling inside the
    rolling 60-day window (`anniversary_within`, applied in the core). A back-dated
    anniversary policy inside the window renews; `final_expense`/life (non-renewing)
    lines generate nothing. Returns `{"generated": <int>, "skipped": <int>}`, idempotent
    on re-run (ADR 0001).
    """
    return await _run_sweep(request, db, rule="anniversary")
