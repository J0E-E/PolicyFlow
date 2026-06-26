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
from ..models.contact import Contact
from ..models.opportunity import Opportunity
from ..models.user import Role
from ..tenancy.registry import TenantConfig, tenant_by_schema
from ..tenancy.scoping import get_tenant_db
from .eligibility import MedicareEligibilityError
from .pipeline import enabled_stages_for, resolve_pipeline
from .service import change_opportunity_stage
from .state import (
    ACTIVE_STAGES,
    InvalidStageTransition,
    OpportunityStage,
    next_enabled_stage,
)

router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])


class ChangeStageRequest(BaseModel):
    """The stage-change request body — the canonical stage to move the card to."""

    target_stage: str


async def _active_tenant_config(db: AsyncSession) -> TenantConfig:
    """Resolve the caller's tenant config from the scoped session's schema.

    Reads the session's `current_schema()` (the convert endpoint's pattern) and
    maps it to the frozen `TenantConfig`. `get_tenant_db` only ever admits a known
    tenant schema, so the lookup never misses. The config carries the enabled
    stages, the stage labels, and the product-line registry the gate reads.
    """
    active_schema = (await db.execute(text("SELECT current_schema()"))).scalar_one()
    return tenant_by_schema(active_schema)


def _opportunity_row(
    opportunity: Opportunity, enabled_stages: frozenset[OpportunityStage]
) -> dict:
    """Serialize one opportunity to the board's minimal row shape.

    Carries the current `stage`, the server-computed `next_stage` (the next
    *enabled* stage for this tenant — a disabled optional stage is skipped — or
    `None` at a terminal stage) so the board's Advance control has its target, and
    `can_mark_lost` (true while the opportunity is at an active, non-terminal stage)
    so the board shows the Mark Lost action without re-deriving the rule. The richer
    card fields (value fields, contact name, owner, eligibility) land in Epic 7.
    """
    current_stage = OpportunityStage(opportunity.stage)
    forward = next_enabled_stage(current_stage, enabled_stages)
    return {
        "id": str(opportunity.id),
        "contact_id": str(opportunity.contact_id),
        "product_line": opportunity.product_line,
        "stage": current_stage.value,
        "next_stage": forward.value if forward is not None else None,
        "can_mark_lost": current_stage in ACTIVE_STAGES,
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
    # Resolve the caller's tenant config to build the board's pipeline columns and
    # the enabled-stage set each row's `next_stage` is computed against.
    tenant_config = await _active_tenant_config(db)
    enabled_stages = enabled_stages_for(tenant_config)
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
        "opportunities": [
            _opportunity_row(opportunity, enabled_stages)
            for opportunity in opportunities
        ],
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
    4. **Medicare gate** — a move to *Quoted* on a `requires_medicare_age` product
       line for an under-65 contact raises `MedicareEligibilityError`, mapped to a
       `422` (distinct from the 409) carrying a clear reason.

    An unknown `target_stage` string is a `422`. Demo-session write isolation
    (Epic 7) layers on here later. On success the service sets the stage and emits
    the event on the request transaction; the updated row is returned under
    `{"opportunity": …}` with a 200.
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

    # The tenant config drives the transition (enabled-stage skip) and the Medicare
    # gate (the product-line `requires_medicare_age` flag + the contact's age band).
    tenant_config = await _active_tenant_config(db)
    enabled_stages = enabled_stages_for(tenant_config)
    product_line = next(
        (
            line
            for line in tenant_config.product_lines
            if line.key == opportunity.product_line
        ),
        None,
    )
    if product_line is None:
        raise HTTPException(
            status_code=409,
            detail=f"unknown product line: {opportunity.product_line}",
        )

    # The contact's plaintext age band is the Medicare gate's age signal (no
    # decryption). The opportunity always has a contact (convert creates it).
    contact = (
        await db.execute(
            select(Contact).where(Contact.id == opportunity.contact_id)
        )
    ).scalar_one_or_none()
    age_band = contact.age_band if contact is not None else None

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
            enabled_stages=enabled_stages,
            product_line=product_line,
            age_band=age_band,
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
    except MedicareEligibilityError as error:
        raise HTTPException(status_code=422, detail=str(error))

    return {"opportunity": _opportunity_row(opportunity, enabled_stages)}
