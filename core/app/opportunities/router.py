"""The opportunities API — the pipeline board read and the stage-change mutation.

Two endpoints under `/api/opportunities`, both riding `get_tenant_db` so isolation
is automatic (the caller's schema scopes every query — no tenant parameter):

- **`GET /api/opportunities`** — the board: the caller's converted opportunities,
  newest first, each with its current `stage` and the server-computed `next_stage`
  (so the board's Advance control knows where to go without re-deriving the
  machine). Guard: `require_authenticated` (any tenant user may read).
- **`POST /api/opportunities/{id}/stage`** — advance one opportunity to
  `target_stage`. Guard: `require_capability(CREATE_EDIT_RECORDS)` (Agent /
  Tenant Admin), then the handler applies its guards **in order**: load / `404`,
  holder (owner or Tenant Admin) / `403`, transition / `409`.

This is the **tracer slice** (P2.2 Epic 2): the enabled-stage set is the full
forward spine (every stage on) until the per-tenant resolver lands (Epic 3/4), the
list carries a minimal payload, and the deferred guards — demo-session write
isolation (Epic 7) and the Medicare eligibility gate (Epic 5) — are not here yet.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import require_authenticated, require_capability
from ..auth.provider import Identity
from ..auth.rbac import Capability
from ..demo.session import current_demo_session
from ..models.opportunity import Opportunity
from ..models.user import Role
from ..tenancy.registry import tenant_by_schema
from ..tenancy.scoping import get_tenant_db
from .pipeline import resolve_pipeline
from .service import change_opportunity_stage
from .state import (
    CANONICAL_FORWARD_ORDER,
    InvalidStageTransition,
    OpportunityStage,
    next_enabled_stage,
)

router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])

# The tracer's enabled-stage set: every stage on the forward spine. The per-tenant
# resolver (Epic 3) replaces this with the tenant's configured enabled set (Epic 4),
# at which point disabled optional stages start being skipped.
FULL_ENABLED_STAGES: frozenset[OpportunityStage] = frozenset(CANONICAL_FORWARD_ORDER)


class ChangeStageRequest(BaseModel):
    """The stage-change request body — the canonical stage to move the card to."""

    target_stage: str


def _opportunity_row(opportunity: Opportunity) -> dict:
    """Serialize one opportunity to the board's minimal row shape (tracer payload).

    Carries the current `stage` and the server-computed `next_stage` (the next
    enabled stage, or `None` at a terminal stage) so the board's Advance control
    has its target without re-implementing the machine. The richer card fields
    (value fields, contact name, owner, eligibility) land in Epic 7.
    """
    current_stage = OpportunityStage(opportunity.stage)
    forward = next_enabled_stage(current_stage, FULL_ENABLED_STAGES)
    return {
        "id": str(opportunity.id),
        "contact_id": str(opportunity.contact_id),
        "product_line": opportunity.product_line,
        "stage": current_stage.value,
        "next_stage": forward.value if forward is not None else None,
    }


@router.get("")
async def list_opportunities(
    identity: Identity = Depends(require_authenticated),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Return the caller's opportunities as the board's minimal rows, newest first.

    Any authenticated tenant user may read, so the guard is `require_authenticated`.
    There is **no tenant parameter** — `get_tenant_db` scopes the query to the
    caller's schema. The board carries the caller's resolved `pipeline.stages`
    (the tenant's enabled, labeled stages in canonical order) alongside the rows.
    Full demo-session visibility scoping (NULL baseline ∪ the caller's session) is
    Epic 7; the tracer returns the schema's rows directly.
    """
    # Resolve the caller's tenant config from the scoped session's schema (the
    # convert endpoint's pattern) to build the board's pipeline columns.
    active_schema = (await db.execute(text("SELECT current_schema()"))).scalar_one()
    tenant_config = tenant_by_schema(active_schema)
    pipeline_stages = [
        {"key": stage.key, "label": stage.label, "is_optional": stage.is_optional}
        for stage in resolve_pipeline(tenant_config)
    ]

    opportunities = (
        await db.execute(
            select(Opportunity).order_by(Opportunity.created_at.desc())
        )
    ).scalars().all()
    return {
        "pipeline": {"stages": pipeline_stages},
        "opportunities": [_opportunity_row(o) for o in opportunities],
    }


@router.post("/{opportunity_id}/stage")
async def change_stage(
    opportunity_id: uuid.UUID,
    change: ChangeStageRequest,
    request: Request,
    identity: Identity = Depends(
        require_capability(Capability.CREATE_EDIT_RECORDS)
    ),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Advance one opportunity to `target_stage`; emit `opportunity.stage_changed`.

    The guard hands the route an `Identity` only when the caller holds
    `CREATE_EDIT_RECORDS` (every other role a 403, the anonymous caller a 401);
    `get_tenant_db` scopes to the caller's schema. The handler then guards **in
    order**:

    1. **Load** the opportunity by id in the caller's schema; missing / cross-tenant
       is a `404`.
    2. **Holder** — the owner **or** any Tenant Admin may move it (D5); else `403`.
    3. **Transition** — `assert_transition` (via the service) rejects an illegal
       move with `InvalidStageTransition`, mapped to `409` naming current + target.

    An unknown `target_stage` string is a `422`. Demo-session write isolation
    (Epic 7) and the Medicare gate (Epic 5) layer on here later. On success the
    service sets the stage and emits the event on the request transaction; the
    updated row is returned under `{"opportunity": …}` with a 200.
    """
    try:
        target_stage = OpportunityStage(change.target_stage)
    except ValueError:
        raise HTTPException(
            status_code=422, detail=f"unknown stage: {change.target_stage}"
        )

    opportunity = (
        await db.execute(
            select(Opportunity).where(Opportunity.id == opportunity_id)
        )
    ).scalar_one_or_none()
    if opportunity is None:
        raise HTTPException(status_code=404, detail="opportunity not found")

    # Holder guard: the owning agent or any Tenant Admin may change the stage (D5) —
    # broader than convert's owner-only, because the BRD lets admins move cards.
    is_owner = opportunity.owner_user_id == identity.user_id
    is_tenant_admin = identity.role == Role.TENANT_ADMIN
    if not (is_owner or is_tenant_admin):
        raise HTTPException(
            status_code=403,
            detail="only the opportunity's owner or a tenant admin can change its stage",
        )

    # Resolve the caller's demo session so the emitted event carries it (the tracer
    # does not yet *guard* on session — that isolation is Epic 7).
    demo_session = await current_demo_session(request, db)
    demo_session_id = demo_session.id if demo_session is not None else None

    try:
        await change_opportunity_stage(
            db,
            identity.tenant_id,
            opportunity=opportunity,
            target_stage=target_stage,
            enabled_stages=FULL_ENABLED_STAGES,
            actor_user_id=identity.user_id,
            actor_role=identity.role,
            demo_session_id=demo_session_id,
        )
    except InvalidStageTransition:
        raise HTTPException(
            status_code=409,
            detail=(
                f"cannot move opportunity from {opportunity.stage} "
                f"to {target_stage.value}"
            ),
        )

    return {"opportunity": _opportunity_row(opportunity)}
