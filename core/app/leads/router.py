"""The authenticated agent lead HTTP surface: create one lead, and the masked reads.

This is the thin route layer for the agent-facing lead endpoints. Like
`pii_demo/router.py`, it adds **no** new crypto, masking, matching, or event logic
of its own — it composes the shared `create_lead` core (`app.leads.intake`) and the
single masked read builder (`app.leads.masking`). It carries three routes:

- **`POST /api/leads`** — the first end-to-end intake slice (TDD §5.4): create one
  agent-entered lead, masked. It owns the two agent-route-specific things:
  - **The product-line key check.** Each submitted `product_lines_of_interest` key
    must be one the caller's tenant actually offers. The schema is resolved from the
    scoped session (`SELECT current_schema()`), mapped to its `TenantConfig` via the
    registry, and any key outside that tenant's key set is rejected with a `422`.
    (The ≥1-key structural rule is enforced earlier, by `CreateLeadRequest`.)
  - **The born framing.** An agent-entered lead is born `Working`, owned by the
    entering agent (`agent_entered`); the core handles everything downstream.
- **`GET /api/leads`** — the masked, newest-first list (TDD §5.4), with an optional
  `unassigned` filter backing the two-tab queue UI (unowned **and** still `New`).
- **`GET /api/leads/{lead_id}`** — the masked detail read; a missing or cross-tenant
  id is a `404 "lead not found"`, mirroring `pii_demo`'s get.
- **`POST /api/leads/{lead_id}/claim`** — the claim action (TDD §5.4): move a `New`
  lead to `Working`, set its owner to the caller, and publish `lead.assigned`. It
  guards the move through the shared state machine — an illegal move (the lead is not
  `New`) is a `409` — and reuses the row's `correlation_id` so all of one lead's
  events share one trace id. No new resource is created, so it returns `200`.
- **`POST /api/leads/{lead_id}/qualify`** — the qualify action (TDD §5.4): move a
  `Working` lead to `Qualified` and publish `lead.qualified` (an `entity_id`-only
  payload). Same load→guard→transition→publish→masked shape and 409 mapping as claim.
- **`POST /api/leads/{lead_id}/reject`** — the reject action (TDD §5.4): move a
  `Working` lead to `Rejected`, store an **optional** free-text reason on the row's
  `rejection_reason` column (surfaced in the masked read, never in the event), and
  publish `lead.rejected` with `{entity_id, reason_kind: "qualify_reject"}`.
- **`POST /api/leads/{lead_id}/resolve-duplicate`** — the duplicate-resolution
  action (TDD §5.4): resolve a lead the matcher flagged. The body's `action` picks
  one of three moves on a **flagged** lead (`duplicate_of_lead_id` set, else a 409
  `"lead is not flagged as a duplicate"`): `link` records the linkage
  (`duplicate_resolution = "linked"`, no event), `new` clears the flag
  (`duplicate_resolution = "new"`, `duplicate_of_lead_id` nulled, no event), and
  `reject` moves a `New` lead to `Rejected` (`duplicate_resolution = "rejected"`,
  linkage kept) and publishes `lead.rejected` with `reason_kind = "duplicate"`. It
  owns the `New → Rejected` move (Epic 13's `/reject` owns `Working → Rejected`), so
  a non-`New` lead is a 409.

All ride `get_tenant_db`, so isolation is automatic — there is **no tenant
parameter** — and the inherited 401 (no session) / 400 (tenantless Platform Admin)
come for free; `POST /api/leads` and the qualify / reject / resolve-duplicate actions require
`CREATE_EDIT_RECORDS`, the claim action requires `CLAIM_LEADS_MANAGE_TASKS` (else
403), while the two reads only require an authenticated tenant user (Read-Only
included). Every
response uses the named-envelope style the other routers use (`{"lead": …}` /
`{"leads": […]}`), built through `build_masked_lead` so the masked-by-default
contract lives in one place. No audit record is written on create — the audit enum
has no lead member; the create is observed only through the `lead.created` (+
`lead.duplicate_detected`) outbox events the core enqueues.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import require_authenticated, require_capability
from ..auth.provider import Identity
from ..auth.rbac import Capability
from ..events.catalog import EventType as EventBusEventType
from ..events.envelope import build_envelope
from ..events.outbox import enqueue_event
from ..models.lead import Lead
from ..tenancy.registry import tenant_by_schema
from ..tenancy.scoping import get_tenant_db
from .intake import create_lead
from .masking import build_masked_lead
from .schemas import CreateLeadRequest, RejectLeadRequest, ResolveDuplicateRequest
from .state import InvalidLeadTransition, LeadSource, LeadStatus, assert_transition

router = APIRouter(prefix="/api/leads")

# A simple safety cap on the list read, not pagination: the newest-first query
# returns at most this many leads. Real paging is a deliberate non-goal for the
# small demo seed (the two-tab UI shows one tenant's modest lead set), so this is a
# named constant rather than a request-tunable page size.
LEAD_LIST_LIMIT = 200


@router.post("", status_code=201)
async def create_lead_endpoint(
    new_lead: CreateLeadRequest,
    identity: Identity = Depends(
        require_capability(Capability.CREATE_EDIT_RECORDS)
    ),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Create one agent-entered lead for the caller's tenant; return it masked.

    The agent intake walking skeleton. The guard hands the route an `Identity` only
    when the caller holds `CREATE_EDIT_RECORDS` (every other role gets a 403, the
    anonymous caller a 401); `get_tenant_db` scopes the write to the caller's own
    schema and rejects a tenantless Platform Admin with a 400 — all inherited, no
    tenant parameter.

    `CreateLeadRequest` has already enforced the structural rules (the field set and
    ≥1 product line) as a 422 before this runs. This handler adds the one
    tenant-aware check: every submitted product-line key must be one the caller's
    tenant offers. The active schema is read from the scoped session
    (`SELECT current_schema()`), mapped to its `TenantConfig` via the registry, and
    any key outside that tenant's key set is rejected with a `422` before the lead is
    created — so a lead can never carry a product line its tenant does not sell.

    The shared `create_lead` core then does the rest (encrypt, fingerprint, derive
    `age_band`, insert, run the matcher, enqueue `lead.created` and — on a duplicate
    hit — `lead.duplicate_detected`), born `Working` / owned by the entering agent /
    `agent_entered`. The lead is returned through `build_masked_lead` under the
    `{"lead": …}` envelope with a 201. Nothing is committed here — `get_tenant_db`
    owns the request transaction.
    """
    active_schema = (await db.execute(text("SELECT current_schema()"))).scalar_one()
    tenant_config = tenant_by_schema(active_schema)
    allowed_keys = {product_line.key for product_line in tenant_config.product_lines}

    unknown_keys = [
        key
        for key in new_lead.product_lines_of_interest
        if key not in allowed_keys
    ]
    if unknown_keys:
        raise HTTPException(
            status_code=422,
            detail=f"unknown product line(s): {', '.join(unknown_keys)}",
        )

    lead = await create_lead(
        db,
        identity.tenant_id,
        first_name=new_lead.first_name,
        last_name=new_lead.last_name,
        email=new_lead.email,
        phone=new_lead.phone,
        date_of_birth=new_lead.date_of_birth,
        zip_code=new_lead.zip_code,
        product_lines_of_interest=new_lead.product_lines_of_interest,
        street_address=new_lead.street_address,
        preferred_contact_method=new_lead.preferred_contact_method,
        notes=new_lead.notes,
        lead_source=LeadSource.AGENT_ENTERED,
        status=LeadStatus.WORKING,
        owner_user_id=identity.user_id,
        owner_username=identity.username,
        actor_user_id=identity.user_id,
        actor_role=identity.role,
    )

    return {"lead": await build_masked_lead(identity.tenant_id, lead)}


@router.get("")
async def list_leads(
    unassigned: bool = False,
    identity: Identity = Depends(require_authenticated),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Return the caller's tenant leads, masked, newest first; the queue when filtered.

    Any authenticated tenant user reads the masked list — Read-Only included — so the
    guard is `require_authenticated`, not a capability check. There is **no tenant
    parameter**: `get_tenant_db` scopes the query to the caller's own schema, so the
    list can only ever contain that one tenant's leads; another tenant's rows are
    physically out of reach.

    Rows are ordered newest first (`created_at` DESC, tie-broken by `id` for a stable
    order across requests) and capped at `LEAD_LIST_LIMIT` — a simple safety cap, not
    pagination. The optional `unassigned` query param backs the two-tab queue UI:
    `false` (the default) returns all leads; `true` restricts to the unclaimed queue —
    leads with no owner **and** still `New` (the `AND` excludes both an owned lead and
    an unowned lead that has already left `New`). Each row is returned through the
    shared `build_masked_lead` builder under the `{"leads": […]}` envelope. The
    dependency chain inherits 401 (no session) and 400 (tenantless caller).
    """
    query = select(Lead).order_by(Lead.created_at.desc(), Lead.id)

    if unassigned:
        query = query.where(
            Lead.owner_user_id.is_(None), Lead.status == LeadStatus.NEW.value
        )

    leads = (
        await db.execute(query.limit(LEAD_LIST_LIMIT))
    ).scalars().all()

    tenant_id = identity.tenant_id
    return {
        "leads": [await build_masked_lead(tenant_id, lead) for lead in leads]
    }


@router.get("/{lead_id}")
async def get_lead(
    lead_id: uuid.UUID,
    identity: Identity = Depends(require_authenticated),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Return one of the caller's tenant leads by id, masked.

    The detail read, mirroring `pii_demo`'s `get_record`. Any authenticated tenant
    user reads the masked shape, so the guard is `require_authenticated`. There is
    deliberately **no tenant parameter** — `get_tenant_db` points the session's
    `search_path` at the caller's own schema, so the lookup resolves only within that
    tenant. A lead id absent in this tenant (whether it does not exist or belongs to
    another tenant) yields a `404 "lead not found"`, so a caller can neither read nor
    probe for another tenant's leads. The dependency chain inherits 401 (no session)
    and 400 (tenantless caller).

    The matched lead is returned through the shared `build_masked_lead` builder under
    the `{"lead": …}` envelope.
    """
    lead = (
        await db.execute(select(Lead).where(Lead.id == lead_id))
    ).scalar_one_or_none()

    if lead is None:
        raise HTTPException(status_code=404, detail="lead not found")

    return {"lead": await build_masked_lead(identity.tenant_id, lead)}


@router.post("/{lead_id}/claim")
async def claim_lead(
    lead_id: uuid.UUID,
    identity: Identity = Depends(
        require_capability(Capability.CLAIM_LEADS_MANAGE_TASKS)
    ),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Claim one `New` lead for the caller, moving it to `Working`; return it masked.

    The first lead action endpoint. An agent picks an unclaimed lead off the queue
    and takes ownership: the lead moves `New → Working`, its owner is set to the
    calling agent, and a `lead.assigned` event is published. No new resource is
    created — the lead already exists — so this returns a `200`, not a `201`.

    The guard hands the route an `Identity` only when the caller holds
    `CLAIM_LEADS_MANAGE_TASKS` (every other role gets a 403, the anonymous caller a
    401); `get_tenant_db` scopes the lookup and write to the caller's own schema and
    rejects a tenantless Platform Admin with a 400 — all inherited, no tenant
    parameter. The handler then runs four steps:

    1. **Load the lead** by id within the caller's schema. An id absent in this tenant
       (whether it does not exist or belongs to another tenant) yields a
       `404 "lead not found"`, mirroring `get_lead` — schema scoping makes another
       tenant's row physically out of reach, so the cross-tenant case is covered here
       too.
    2. **Guard the move** through the shared state machine: `assert_transition` allows
       only `New → Working`. A lead in any other status (already `Working`,
       `Qualified`, or `Rejected`) raises the framework-free `InvalidLeadTransition`,
       which is mapped to a `409` naming the current status. The 409 is a cross-epic
       contract — Epics 13/14 catch the same exception and map it the same way.
    3. **Apply the claim** — the lead's `status` becomes `Working`, its `owner_user_id`
       / `owner_username` become the calling agent's, and the change is flushed. The
       handler does **not** commit; `get_tenant_db` owns the request transaction, so
       the row change and the outbox event all land or all roll back together.
    4. **Publish `lead.assigned`** onto this tenant's outbox (a non-PII payload: the
       entity reference plus the new owner's id), reusing the row's own
       `correlation_id` so every event for this lead shares one trace id.

    The claimed lead is returned through the shared `build_masked_lead` builder under
    the `{"lead": …}` envelope.
    """
    lead = (
        await db.execute(select(Lead).where(Lead.id == lead_id))
    ).scalar_one_or_none()

    if lead is None:
        raise HTTPException(status_code=404, detail="lead not found")

    try:
        assert_transition(LeadStatus(lead.status), LeadStatus.WORKING)
    except InvalidLeadTransition:
        raise HTTPException(
            status_code=409,
            detail=f"lead cannot be claimed (status: {lead.status})",
        )

    lead.status = LeadStatus.WORKING.value
    lead.owner_user_id = identity.user_id
    lead.owner_username = identity.username
    await db.flush()

    # Reuse the row's `correlation_id` so this `lead.assigned` event shares the trace
    # id of the lead's `lead.created` (and any later) events — read it back off the
    # row (TDD §5.4). Published on the same request transaction as the status change
    # (the transactional outbox: the claim and its event land or roll back together).
    await enqueue_event(
        db,
        build_envelope(
            event_type=EventBusEventType.LEAD_ASSIGNED,
            tenant_id=identity.tenant_id,
            actor_user_id=identity.user_id,
            actor_role=identity.role,
            payload={
                "entity_id": str(lead.id),
                "owner_user_id": str(identity.user_id),
            },
            correlation_id=lead.correlation_id,
        ),
    )

    return {"lead": await build_masked_lead(identity.tenant_id, lead)}


@router.post("/{lead_id}/qualify")
async def qualify_lead(
    lead_id: uuid.UUID,
    identity: Identity = Depends(
        require_capability(Capability.CREATE_EDIT_RECORDS)
    ),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Qualify one `Working` lead, moving it to `Qualified`; return it masked.

    A terminal-transition action that mirrors `claim_lead`'s shape exactly: load →
    guard → transition → publish → masked. An agent marks a lead they have been
    working as qualified — the lead moves `Working → Qualified` and a `lead.qualified`
    event is published. No new resource is created, so this returns a `200`.

    The guard hands the route an `Identity` only when the caller holds
    `CREATE_EDIT_RECORDS` (every other role gets a 403, the anonymous caller a 401) —
    the create/edit capability, **not** claim's `CLAIM_LEADS_MANAGE_TASKS`.
    `get_tenant_db` scopes the lookup and write to the caller's own schema and rejects
    a tenantless Platform Admin with a 400 — all inherited, no tenant parameter. The
    handler then runs four steps:

    1. **Load the lead** by id within the caller's schema. An id absent in this tenant
       (whether it does not exist or belongs to another tenant) yields a
       `404 "lead not found"`, mirroring `get_lead` — schema scoping makes another
       tenant's row physically out of reach, so the cross-tenant case is covered here
       too.
    2. **Guard the move** through the shared state machine: `assert_transition` allows
       only `Working → Qualified`. A lead in any other status raises the framework-free
       `InvalidLeadTransition`, mapped to a `409` naming the current status (the same
       409 contract `claim_lead` set).
    3. **Apply the transition** — the lead's `status` becomes `Qualified` and the change
       is flushed. The handler does **not** commit; `get_tenant_db` owns the request
       transaction, so the row change and the outbox event all land or all roll back
       together.
    4. **Publish `lead.qualified`** onto this tenant's outbox (an `entity_id`-only
       payload — no other field), reusing the row's own `correlation_id` so every event
       for this lead shares one trace id.

    The qualified lead is returned through the shared `build_masked_lead` builder under
    the `{"lead": …}` envelope.
    """
    lead = (
        await db.execute(select(Lead).where(Lead.id == lead_id))
    ).scalar_one_or_none()

    if lead is None:
        raise HTTPException(status_code=404, detail="lead not found")

    try:
        assert_transition(LeadStatus(lead.status), LeadStatus.QUALIFIED)
    except InvalidLeadTransition:
        raise HTTPException(
            status_code=409,
            detail=f"lead cannot be qualified (status: {lead.status})",
        )

    lead.status = LeadStatus.QUALIFIED.value
    await db.flush()

    # Reuse the row's `correlation_id` so this `lead.qualified` event shares the lead's
    # trace id. The payload is `entity_id` only (no owner or reason). On the same
    # request transaction as the status change (the transactional outbox).
    await enqueue_event(
        db,
        build_envelope(
            event_type=EventBusEventType.LEAD_QUALIFIED,
            tenant_id=identity.tenant_id,
            actor_user_id=identity.user_id,
            actor_role=identity.role,
            payload={"entity_id": str(lead.id)},
            correlation_id=lead.correlation_id,
        ),
    )

    return {"lead": await build_masked_lead(identity.tenant_id, lead)}


@router.post("/{lead_id}/reject")
async def reject_lead(
    lead_id: uuid.UUID,
    rejection: RejectLeadRequest,
    identity: Identity = Depends(
        require_capability(Capability.CREATE_EDIT_RECORDS)
    ),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Reject one `Working` lead, moving it to `Rejected`; return it masked.

    The qualify endpoint's twin, with one extra: an **optional** free-text reason. An
    agent marks a lead they have been working as rejected — the lead moves
    `Working → Rejected`, the optional reason is stored on the row's `rejection_reason`
    column (kept separate from intake `notes`), and a `lead.rejected` event is
    published. No new resource is created, so this returns a `200`.

    The gate and error mapping are identical to qualify: `CREATE_EDIT_RECORDS` (403 /
    401 otherwise), `get_tenant_db` scoping (400 tenantless), `404 "lead not found"` on
    a missing or cross-tenant id, and an illegal move (the lead is not `Working`) mapped
    to a `409`. The handler runs four steps:

    1. **Load the lead** by id within the caller's schema (404 on missing /
       cross-tenant, exactly as qualify).
    2. **Guard the move** through `assert_transition` (`Working → Rejected` only); any
       other status raises `InvalidLeadTransition`, mapped to a `409`.
    3. **Apply the transition and store the reason** — the lead's `status` becomes
       `Rejected` and `rejection_reason` is set to the supplied reason (or left `None`
       when none was given — a reason-less reject is allowed). The change is flushed; no
       commit here (`get_tenant_db` owns the transaction).
    4. **Publish `lead.rejected`** with payload `{entity_id, reason_kind: "qualify_reject"}`,
       reusing the row's `correlation_id`. The free-text reason is **never** in the
       event — it stays on the row, surfaced only in the masked read. `reason_kind`
       categorizes this path; Epic 14's duplicate-reject reuses the same event with
       `reason_kind = "duplicate"`.

    The rejected lead is returned through the shared `build_masked_lead` builder under
    the `{"lead": …}` envelope.
    """
    lead = (
        await db.execute(select(Lead).where(Lead.id == lead_id))
    ).scalar_one_or_none()

    if lead is None:
        raise HTTPException(status_code=404, detail="lead not found")

    # This qualify/reject path rejects only a `Working` lead. The state machine
    # legally allows `New → Rejected` too, but that path belongs to Epic 14's
    # duplicate-resolution reject (same event, `reason_kind = "duplicate"`), so a
    # `New` lead here is an illegal move for *this* endpoint — guard the current
    # status explicitly before the formal `assert_transition`, mapping anything but
    # `Working` to the same 409.
    if LeadStatus(lead.status) is not LeadStatus.WORKING:
        raise HTTPException(
            status_code=409,
            detail=f"lead cannot be rejected (status: {lead.status})",
        )

    try:
        assert_transition(LeadStatus(lead.status), LeadStatus.REJECTED)
    except InvalidLeadTransition:
        raise HTTPException(
            status_code=409,
            detail=f"lead cannot be rejected (status: {lead.status})",
        )

    lead.status = LeadStatus.REJECTED.value
    lead.rejection_reason = rejection.reason
    await db.flush()

    # Reuse the row's `correlation_id` so this `lead.rejected` event shares the lead's
    # trace id. The payload carries the entity reference and the `reason_kind` that
    # categorizes the rejection — never the free-text reason, which stays on the row.
    await enqueue_event(
        db,
        build_envelope(
            event_type=EventBusEventType.LEAD_REJECTED,
            tenant_id=identity.tenant_id,
            actor_user_id=identity.user_id,
            actor_role=identity.role,
            payload={
                "entity_id": str(lead.id),
                "reason_kind": "qualify_reject",
            },
            correlation_id=lead.correlation_id,
        ),
    )

    return {"lead": await build_masked_lead(identity.tenant_id, lead)}


@router.post("/{lead_id}/resolve-duplicate")
async def resolve_duplicate_lead(
    lead_id: uuid.UUID,
    resolution: ResolveDuplicateRequest,
    identity: Identity = Depends(
        require_capability(Capability.CREATE_EDIT_RECORDS)
    ),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Resolve a lead the matcher flagged as a possible duplicate; return it masked.

    When intake found a prior matching lead, the new lead carries a
    `duplicate_of_lead_id` linkage and an unresolved flag. This endpoint is the agent's
    one way to clear that flag — and it exists **only** to resolve a flag: a lead that
    is not flagged (`duplicate_of_lead_id IS NULL`) is a `409 "lead is not flagged as a
    duplicate"` for every action. The body's `action` (a strict `Literal`; an unknown
    value is a 422 before this runs) picks one of three moves. No new resource is
    created, so this returns a `200`.

    The gate and scoping mirror qualify / reject: `CREATE_EDIT_RECORDS` (403 / 401
    otherwise), `get_tenant_db` scoping (400 tenantless, 404 on a missing or
    cross-tenant id). The three actions are:

    - **`link`** — confirm the match is the same person: set
      `duplicate_resolution = "linked"`, **keep** the `duplicate_of_lead_id`. No event.
    - **`new`** — it is genuinely a different person: set `duplicate_resolution = "new"`
      and clear `duplicate_of_lead_id` to null. No event.
    - **`reject`** — discard the lead as a duplicate. This owns the `New → Rejected`
      move (Epic 13's `/reject` owns `Working → Rejected`), so the current status is
      guarded as `New` explicitly — a non-`New` lead (a flagged `Working` lead is
      rejected via `/reject` instead) is a `409`. On a `New` lead it runs the formal
      `assert_transition(New, Rejected)`, sets `status = Rejected` **and**
      `duplicate_resolution = "rejected"` (the linkage is **kept**), and publishes
      `lead.rejected` with `{entity_id, reason_kind: "duplicate"}` reusing the row's
      `correlation_id`. It sets **no** `rejection_reason` — that free-text column is the
      qualify/reject path's, not this one's.

    Nothing is committed here — `get_tenant_db` owns the request transaction, so the row
    change and any outbox event land or roll back together. The resolved lead is
    returned through the shared `build_masked_lead` builder under the `{"lead": …}`
    envelope.
    """
    lead = (
        await db.execute(select(Lead).where(Lead.id == lead_id))
    ).scalar_one_or_none()

    if lead is None:
        raise HTTPException(status_code=404, detail="lead not found")

    # The endpoint exists only to resolve a flag: every action requires the lead to be
    # flagged. An unflagged lead has nothing to resolve, so it is a 409 before any
    # action-specific logic runs.
    if lead.duplicate_of_lead_id is None:
        raise HTTPException(
            status_code=409,
            detail="lead is not flagged as a duplicate",
        )

    if resolution.action == "link":
        # Confirm the match is the same person: record the resolution, keep the linkage.
        lead.duplicate_resolution = "linked"
        await db.flush()
        return {"lead": await build_masked_lead(identity.tenant_id, lead)}

    if resolution.action == "new":
        # A genuinely different person: clear the flag (drop the linkage too).
        lead.duplicate_resolution = "new"
        lead.duplicate_of_lead_id = None
        await db.flush()
        return {"lead": await build_masked_lead(identity.tenant_id, lead)}

    # action == "reject": discard the lead as a duplicate. This path owns the
    # `New → Rejected` move; the qualify/reject path owns `Working → Rejected`. Guard
    # the current status as `New` explicitly so the start-state partition holds — a
    # non-`New` lead (e.g. a flagged `Working` lead, rejected via `/reject` instead) is
    # a 409 before the formal `assert_transition`.
    if LeadStatus(lead.status) is not LeadStatus.NEW:
        raise HTTPException(
            status_code=409,
            detail=f"lead cannot be duplicate-rejected (status: {lead.status})",
        )

    try:
        assert_transition(LeadStatus(lead.status), LeadStatus.REJECTED)
    except InvalidLeadTransition:
        raise HTTPException(
            status_code=409,
            detail=f"lead cannot be duplicate-rejected (status: {lead.status})",
        )

    lead.status = LeadStatus.REJECTED.value
    lead.duplicate_resolution = "rejected"
    await db.flush()

    # Reuse the row's `correlation_id` so this `lead.rejected` event shares the lead's
    # trace id. The payload carries the entity reference and `reason_kind = "duplicate"`
    # (this is the duplicate-reject path; the qualify/reject path emits
    # `"qualify_reject"`). No `rejection_reason` is set on this path.
    await enqueue_event(
        db,
        build_envelope(
            event_type=EventBusEventType.LEAD_REJECTED,
            tenant_id=identity.tenant_id,
            actor_user_id=identity.user_id,
            actor_role=identity.role,
            payload={
                "entity_id": str(lead.id),
                "reason_kind": "duplicate",
            },
            correlation_id=lead.correlation_id,
        ),
    )

    return {"lead": await build_masked_lead(identity.tenant_id, lead)}
