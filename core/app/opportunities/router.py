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
from ..applications.read import serialize_application
from ..applications.service import OneActiveApplicationError, select_quote
from ..applications.steps import application_step_for
from ..demo.session import current_demo_session
from ..models.application import Application
from ..models.contact import Contact
from ..models.opportunity import Opportunity
from ..models.quote import Quote
from ..models.quote_request import QuoteRequest
from ..models.user import Role
from ..quotes.service import STATUS_COMPLETED, request_quotes
from ..tenancy.registry import ProductLine, TenantConfig, tenant_by_schema
from ..tenancy.scoping import get_tenant_db
from .eligibility import ELIGIBLE_AGE_BAND, MedicareEligibilityError, is_blocked_for_medicare
from .pipeline import enabled_stages_for, resolve_pipeline
from .service import change_opportunity_stage
from .state import (
    ACTIVE_STAGES,
    AUTOMATION_OWNED_STAGES,
    AutomationOwnedStageError,
    InvalidStageTransition,
    OpportunityStage,
    next_enabled_stage,
)

router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])


class ChangeStageRequest(BaseModel):
    """The stage-change request body — the canonical stage to move the card to."""

    target_stage: str


class SelectQuoteRequest(BaseModel):
    """The quote-selection request body — the attached quote to turn into an Application."""

    quote_id: uuid.UUID


async def _active_tenant_config(db: AsyncSession) -> TenantConfig:
    """Resolve the caller's tenant config from the scoped session's schema.

    Reads the session's `current_schema()` (the convert endpoint's pattern) and
    maps it to the frozen `TenantConfig`. `get_tenant_db` only ever admits a known
    tenant schema, so the lookup never misses. The config carries the enabled
    stages, the stage labels, and the product-line registry the gate reads.
    """
    active_schema = (await db.execute(text("SELECT current_schema()"))).scalar_one()
    return tenant_by_schema(active_schema)


def _scope_to_session(query, demo_session_id: uuid.UUID | None):
    """Scope an `Opportunity` SELECT to the seed baseline plus the caller's session.

    Mirrors `leads.visibility.visible_to_session` for opportunities: with a live
    session, `demo_session_id IS NULL OR demo_session_id = :session_id` (seed ∪ the
    caller's own rows); without one, just `demo_session_id IS NULL` (seed-only), so
    a session-less caller never sees a visitor's private rows.
    """
    if demo_session_id is None:
        return query.where(Opportunity.demo_session_id.is_(None))
    return query.where(
        Opportunity.demo_session_id.is_(None)
        | (Opportunity.demo_session_id == demo_session_id)
    )


async def _guard_opportunity_for_session(
    opportunity: Opportunity, request: Request, db: AsyncSession
) -> uuid.UUID | None:
    """Enforce demo-session write-isolation on an already-loaded opportunity.

    The mutation twin of `_scope_to_session` (mirrors the convert guard): resolves
    the caller's demo session once and applies two guards in order — a row owned by
    **another** session is a `404` (indistinguishable from not-found, so a visitor
    can neither mutate nor probe for another's), and a shared **seed** row
    (`demo_session_id IS NULL`) while the caller is in a live session is a `409` (a
    visitor must never alter a row every visitor sees). Returns the resolved session
    id so the caller reuses it to stamp events.
    """
    demo_session = await current_demo_session(request, db)
    demo_session_id = demo_session.id if demo_session is not None else None

    if (
        opportunity.demo_session_id is not None
        and opportunity.demo_session_id != demo_session_id
    ):
        raise HTTPException(status_code=404, detail="opportunity not found")

    if demo_session_id is not None and opportunity.demo_session_id is None:
        raise HTTPException(
            status_code=409, detail="seed opportunities cannot be modified"
        )

    return demo_session_id


def _opportunity_row(
    opportunity: Opportunity,
    contact: Contact | None,
    product_line: ProductLine | None,
    enabled_stages: frozenset[OpportunityStage],
) -> dict:
    """Serialize one opportunity to the board's enriched row shape.

    Carries the stage machinery (`stage`, the next *enabled* `next_stage`,
    `can_mark_lost`) plus the card's display fields: the value fields
    (`estimated_annual_premium` as a string / `target_close_date` as ISO, each
    `null` until P2.3 populates them — the board renders an em-dash), the contact's
    plaintext name, the owner, the tenant's `product_line_label`, and the
    `eligibility` flags (`medicare_gated` from the product line, `age_eligible` from
    the contact's plaintext age band). `contact` / `product_line` are tolerated as
    `None` defensively, though every opportunity has both.
    """
    current_stage = OpportunityStage(opportunity.stage)
    forward = next_enabled_stage(current_stage, enabled_stages)
    age_band = contact.age_band if contact is not None else None
    premium = opportunity.estimated_annual_premium
    close_date = opportunity.target_close_date
    # The Advance control is offered only when the next stage is manually reachable:
    # an automation-owned next stage (e.g. *Application Started* after *Quoted*) is
    # driven by the money-path automation, so the board suppresses Advance for it
    # rather than offer a button that would 422 (D6 lockdown).
    can_advance = forward is not None and forward not in AUTOMATION_OWNED_STAGES
    return {
        "id": str(opportunity.id),
        "contact_id": str(opportunity.contact_id),
        "household_id": str(opportunity.household_id),
        "product_line": opportunity.product_line,
        "product_line_label": (
            product_line.label if product_line is not None else opportunity.product_line
        ),
        "stage": current_stage.value,
        "next_stage": forward.value if forward is not None else None,
        "can_advance": can_advance,
        "can_mark_lost": current_stage in ACTIVE_STAGES,
        "estimated_annual_premium": str(premium) if premium is not None else None,
        "target_close_date": close_date.isoformat() if close_date is not None else None,
        "contact_first_name": contact.first_name if contact is not None else None,
        "contact_last_name": contact.last_name if contact is not None else None,
        "owner_username": opportunity.owner_username,
        "eligibility": {
            "medicare_gated": (
                product_line.requires_medicare_age if product_line is not None else False
            ),
            "age_eligible": age_band == ELIGIBLE_AGE_BAND,
        },
    }


@router.get("")
async def list_opportunities(
    request: Request,
    identity: Identity = Depends(require_authenticated),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Return the caller's opportunities as the board's enriched rows, newest first.

    Any authenticated tenant user may read, so the guard is `require_authenticated`.
    There is **no tenant parameter** — `get_tenant_db` scopes the query to the
    caller's schema, and `_scope_to_session` further scopes it to the shared seed
    baseline plus the caller's own demo session, so one visitor never sees another's
    rows. The board carries the caller's resolved `pipeline.stages` alongside the
    enriched opportunity rows (value fields, contact name, owner, eligibility).
    """
    # Resolve the caller's tenant config to build the board's pipeline columns, the
    # enabled-stage set, and the product-line registry the rows label/flag against.
    tenant_config = await _active_tenant_config(db)
    enabled_stages = enabled_stages_for(tenant_config)
    product_lines_by_key = {line.key: line for line in tenant_config.product_lines}
    pipeline_stages = [
        {"key": stage.key, "label": stage.label, "is_optional": stage.is_optional}
        for stage in resolve_pipeline(tenant_config)
    ]

    # Scope to the seed baseline ∪ the caller's session (the lead read pattern).
    demo_session = await current_demo_session(request, db)
    demo_session_id = demo_session.id if demo_session is not None else None
    query = _scope_to_session(
        select(Opportunity).order_by(Opportunity.created_at.desc()), demo_session_id
    )
    opportunities = (await db.execute(query)).scalars().all()

    # Load the listed opportunities' contacts in one query for the row name + age.
    contact_ids = {opportunity.contact_id for opportunity in opportunities}
    contacts_by_id: dict[uuid.UUID, Contact] = {}
    if contact_ids:
        contacts = (
            await db.execute(select(Contact).where(Contact.id.in_(contact_ids)))
        ).scalars().all()
        contacts_by_id = {contact.id: contact for contact in contacts}

    return {
        "pipeline": {"stages": pipeline_stages},
        "opportunities": [
            _opportunity_row(
                opportunity,
                contacts_by_id.get(opportunity.contact_id),
                product_lines_by_key.get(opportunity.product_line),
                enabled_stages,
            )
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
    2. **Demo-session write-isolation** — a foreign session's row is a `404`, a
       shared seed row (with a live session) a `409`. The resolved session id is
       reused to stamp the events.
    3. **Holder** — the owner **or** any Tenant Admin may move it (D5); else `403`.
    4. **Transition** — `assert_transition` (via the service) rejects an illegal
       move with `InvalidStageTransition`, mapped to `409` naming current + target.
    5. **Medicare gate** — a move to *Quoted* on a `requires_medicare_age` product
       line for an under-65 contact raises `MedicareEligibilityError`, mapped to a
       `422` (distinct from the 409) carrying a clear reason.

    An unknown `target_stage` string is a `422`. On success the service sets the
    stage and emits the event on the request transaction; the updated row is
    returned under `{"opportunity": …}` with a 200.
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

    # Demo-session write-isolation, before the holder / transition guards: a foreign
    # session's row is a 404, a shared seed row a 409. The resolved session id is
    # reused for the events without a second `platform` read.
    demo_session_id = await _guard_opportunity_for_session(opportunity, request, db)

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
    except AutomationOwnedStageError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except MedicareEligibilityError as error:
        raise HTTPException(status_code=422, detail=str(error))

    return {
        "opportunity": _opportunity_row(
            opportunity, contact, product_line, enabled_stages
        )
    }


def _quote_request_row(quote_request: QuoteRequest) -> dict:
    """Serialize one `QuoteRequest` to the round-trip's pollable shape.

    The `status` (`pending` → `completed`) is the column the agent polls; the `id`
    is what the poll endpoint is keyed by. Non-PII throughout.
    """
    return {
        "id": str(quote_request.id),
        "opportunity_id": str(quote_request.opportunity_id),
        "status": quote_request.status,
        "product_line": quote_request.product_line,
    }


def _quote_row(quote: Quote) -> dict:
    """Serialize one returned `Quote` option for the quote list (non-PII)."""
    return {
        "id": str(quote.id),
        "carrier": quote.carrier,
        "product_label": quote.product_label,
        "coverage_amount": quote.coverage_amount,
        "premium_monthly": quote.premium_monthly,
        "premium_annual": quote.premium_annual,
    }


async def _product_line_for(
    opportunity: Opportunity, tenant_config: TenantConfig
) -> ProductLine:
    """Resolve the opportunity's `ProductLine` from the tenant registry, or 409.

    The registry is the source of truth for the product line the quote stub reads
    its options by and the Medicare gate flags on. A missing line is corrupt data,
    so it is a `409` naming the key (the `change_stage` precedent).
    """
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
    return product_line


@router.post("/{opportunity_id}/quote-requests")
async def create_quote_request(
    opportunity_id: uuid.UUID,
    request: Request,
    identity: Identity = Depends(require_capability(Capability.CREATE_EDIT_RECORDS)),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Open a carrier-quote round-trip for one *Qualified* opportunity.

    Guards in the `change_stage` order: load / `404`, demo-session write-isolation
    (foreign `404`, seed `409`), holder (owner or Tenant Admin) / `403`. The
    opportunity must be at *Qualified* — the coherent precondition for requesting
    quotes — else `409`. The Medicare gate is **re-checked** here (BRD §7): a
    `requires_medicare_age` line for an under-65 contact is a `422` before any write.
    On success `request_quotes` writes the `pending` row and enqueues
    `quote.requested` on the request transaction; the new request is returned under
    `{"quote_request": …}`.
    """
    opportunity = (
        await db.execute(select(Opportunity).where(Opportunity.id == opportunity_id))
    ).scalar_one_or_none()
    if opportunity is None:
        raise HTTPException(status_code=404, detail="opportunity not found")

    demo_session_id = await _guard_opportunity_for_session(opportunity, request, db)

    is_owner = opportunity.owner_user_id == identity.user_id
    is_tenant_admin = identity.role == Role.TENANT_ADMIN
    if not (is_owner or is_tenant_admin):
        raise HTTPException(
            status_code=403,
            detail="only the opportunity's owner or a tenant admin can request quotes",
        )

    if OpportunityStage(opportunity.stage) != OpportunityStage.QUALIFIED:
        raise HTTPException(
            status_code=409,
            detail="quotes can only be requested for a qualified opportunity",
        )

    tenant_config = await _active_tenant_config(db)
    product_line = await _product_line_for(opportunity, tenant_config)

    # The contact's plaintext age band is the Medicare gate's age signal (no
    # decryption), re-checked here so a blocked line never opens a round-trip.
    contact = (
        await db.execute(select(Contact).where(Contact.id == opportunity.contact_id))
    ).scalar_one_or_none()
    age_band = contact.age_band if contact is not None else None
    if is_blocked_for_medicare(product_line, age_band):
        raise HTTPException(
            status_code=422, detail=str(MedicareEligibilityError(product_line.key, age_band))
        )

    quote_request = await request_quotes(
        db,
        identity.tenant_id,
        opportunity_id=opportunity.id,
        product_line=opportunity.product_line,
        correlation_id=opportunity.correlation_id,
        actor_user_id=identity.user_id,
        actor_role=identity.role,
        demo_session_id=demo_session_id,
    )
    return {"quote_request": _quote_request_row(quote_request)}


@router.get("/{opportunity_id}/quote-requests/{quote_request_id}")
async def get_quote_request(
    opportunity_id: uuid.UUID,
    quote_request_id: uuid.UUID,
    request: Request,
    identity: Identity = Depends(require_authenticated),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Poll one quote round-trip — its `status` and, once `completed`, its options.

    A **pure read** any authenticated tenant user may poll (Read-Only included): the
    *Quoted* stage move rides the consumer's completing transaction, not this
    endpoint, so polling never mutates. Scoped to the seed baseline ∪ the caller's
    demo session — an opportunity or request owned by another session is a `404`. The
    `quotes` list is empty until the request is `completed`, then carries the
    attached options. The opportunity's current `stage` is returned so the client can
    reflect the *Quoted* move without a second call.
    """
    demo_session = await current_demo_session(request, db)
    demo_session_id = demo_session.id if demo_session is not None else None

    opportunity = (
        await db.execute(
            _scope_to_session(
                select(Opportunity).where(Opportunity.id == opportunity_id),
                demo_session_id,
            )
        )
    ).scalar_one_or_none()
    if opportunity is None:
        raise HTTPException(status_code=404, detail="opportunity not found")

    quote_request = (
        await db.execute(
            select(QuoteRequest).where(
                QuoteRequest.id == quote_request_id,
                QuoteRequest.opportunity_id == opportunity_id,
            )
        )
    ).scalar_one_or_none()
    if quote_request is None or (
        quote_request.demo_session_id is not None
        and quote_request.demo_session_id != demo_session_id
    ):
        raise HTTPException(status_code=404, detail="quote request not found")

    quotes: list[Quote] = []
    if quote_request.status == STATUS_COMPLETED:
        quotes = list(
            (
                await db.execute(
                    select(Quote)
                    .where(Quote.quote_request_id == quote_request_id)
                    .order_by(Quote.created_at, Quote.id)
                )
            ).scalars().all()
        )

    return {
        "quote_request": _quote_request_row(quote_request),
        "quotes": [_quote_row(quote) for quote in quotes],
        "opportunity_stage": OpportunityStage(opportunity.stage).value,
    }


@router.post("/{opportunity_id}/applications")
async def create_application(
    opportunity_id: uuid.UUID,
    selection: SelectQuoteRequest,
    request: Request,
    identity: Identity = Depends(require_capability(Capability.CREATE_EDIT_RECORDS)),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Select an attached quote — create a Draft Application, advance the opportunity.

    Guards in the `change_stage` order: load / `404`, demo-session write-isolation
    (foreign `404`, seed `409`), holder (owner or Tenant Admin) / `403`. The
    opportunity must be at *Quoted* (selection follows the quotes attaching) — else
    `409`. The chosen quote must belong to this opportunity — else `404`. On success
    `select_quote` creates the `Draft` Application, sets the estimated annual
    premium, advances the opportunity to *Application Started* via the internal
    setter, and emits `application.started`; the new Application is returned under
    `{"application": …}`.
    """
    opportunity = (
        await db.execute(select(Opportunity).where(Opportunity.id == opportunity_id))
    ).scalar_one_or_none()
    if opportunity is None:
        raise HTTPException(status_code=404, detail="opportunity not found")

    demo_session_id = await _guard_opportunity_for_session(opportunity, request, db)

    is_owner = opportunity.owner_user_id == identity.user_id
    is_tenant_admin = identity.role == Role.TENANT_ADMIN
    if not (is_owner or is_tenant_admin):
        raise HTTPException(
            status_code=403,
            detail="only the opportunity's owner or a tenant admin can select a quote",
        )

    if OpportunityStage(opportunity.stage) != OpportunityStage.QUOTED:
        raise HTTPException(
            status_code=409,
            detail="a quote can only be selected for a quoted opportunity",
        )

    quote = (
        await db.execute(
            select(Quote).where(
                Quote.id == selection.quote_id,
                Quote.opportunity_id == opportunity_id,
            )
        )
    ).scalar_one_or_none()
    if quote is None:
        raise HTTPException(status_code=404, detail="quote not found")

    try:
        application = await select_quote(
            db,
            identity.tenant_id,
            opportunity=opportunity,
            quote=quote,
            actor_user_id=identity.user_id,
            actor_role=identity.role,
            demo_session_id=demo_session_id,
        )
    except OneActiveApplicationError:
        raise HTTPException(
            status_code=409,
            detail="this opportunity already has an active application",
        )
    tenant_config = await _active_tenant_config(db)
    application_step = application_step_for(opportunity.product_line, tenant_config)
    return {"application": serialize_application(application, application_step)}
