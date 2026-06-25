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
- **`POST /api/leads/{lead_id}/convert`** — the convert action (TDD §5.4): turn a
  held `Qualified` lead (owner-only, else 403) into a new Household + Contact + one
  Opportunity per product line + a note-Task (when the lead has notes), freeze it
  `Converted`, and publish the four conversion events — all atomically on the request
  transaction (the shared `convert_lead` core). Returns the masked frozen lead (`200`).
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
- **`POST /api/leads/{lead_id}/reveal`** — the guarded PII reveal (TDD §5.4),
  mirroring `pii_demo`'s reveal: unmask **one** encrypted field of one lead. Every
  encrypted column is revealable (`email`, `phone`, `date_of_birth`,
  `street_address`); any other field name is a generic `422 "field is not
  revealable"` refused **before** the DB read (leads have no never-revealable
  deny-list). The one allow-listed field is decrypted, the `on_pii_revealed` audit
  seam is awaited, and `{"field": …, "value": …}` is returned. It gates on
  `REVEAL_PII` (the only route here that does), and an absent optional blob (no
  street address) returns `value: null`.

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

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import require_authenticated, require_capability
from ..auth.provider import Identity
from ..auth.rbac import Capability
from ..demo.session import current_demo_session
from ..events.catalog import EventType as EventBusEventType
from ..events.envelope import build_envelope
from ..events.outbox import enqueue_event
from ..models.lead import Lead
from ..pii.reveal_seam import on_pii_revealed
from ..pii.service import decrypt_field
from ..tenancy.registry import tenant_by_schema
from ..tenancy.scoping import get_tenant_db
from .conversion import convert_lead, get_conversion_summary
from .intake import create_lead
from .masking import build_masked_lead
from .timeline import get_lead_timeline_rows
from .visibility import visible_to_session
from .schemas import (
    ConvertLeadRequest,
    CreateLeadRequest,
    RejectLeadRequest,
    ResolveDuplicateRequest,
    RevealLeadRequest,
)
from .state import InvalidLeadTransition, LeadSource, LeadStatus, assert_transition

router = APIRouter(prefix="/api/leads")

# A simple safety cap on the list read, not pagination: the newest-first query
# returns at most this many leads. Real paging is a deliberate non-goal for the
# small demo seed (the two-tab UI shows one tenant's modest lead set), so this is a
# named constant rather than a request-tunable page size.
LEAD_LIST_LIMIT = 200

# The reveal endpoint's single field allow-list — the one source of truth for what
# `POST /{lead_id}/reveal` will unmask. It maps each accepted request field name to
# the encrypted column attribute on `Lead` whose blob the handler decrypts. **Every**
# encrypted field is revealable (no `pii_demo`-style never-revealable deny-list: a
# lead has no `mock_medicare_id`-equivalent), so any name outside this map falls
# through to a single generic 422.
REVEALABLE_FIELDS: dict[str, str] = {
    "email": "email_encrypted",
    "phone": "phone_encrypted",
    "date_of_birth": "date_of_birth_encrypted",
    "street_address": "street_address_encrypted",
}


async def _guard_loaded_lead_for_session(
    lead: Lead,
    request: Request,
    db: AsyncSession,
    *,
    refuse_seed: bool,
) -> uuid.UUID | None:
    """Enforce demo-session write-isolation on an **already-loaded** lead.

    The action-endpoint twin of `get_lead`'s read-isolation check, shared across the
    four mutating actions (claim / qualify / reject / resolve-duplicate) and reused —
    `refuse_seed=False` — by `reveal`. It resolves the caller's demo session once
    (from the `pf_demo_session` cookie, read-only — the `demo_sessions` table lives in
    `platform`, which the tenant-scoped session can read) and applies up to two guards
    in order:

    - **Foreign session → `404 "lead not found"`** — a row owned by **another** demo
      session (`demo_session_id` neither `NULL` nor the caller's resolved id) is
      treated as if it did not exist, identical to the cross-tenant not-found, so one
      visitor can neither mutate nor probe for another's lead. Always applied.
    - **Seed row → `409`** — when `refuse_seed` is set **and the caller is in a live
      demo session**, a shared seed row (`demo_session_id IS NULL`) is refused: a
      visitor must never alter a row every visitor sees. The guard is gated on the
      caller *having* a session, because `demo_session_id IS NULL` is also every
      ordinary non-demo lead — a session-less caller (no `pf_demo_session` cookie) is
      operating outside the demo, where `NULL` rows are normal data and the action must
      proceed. `reveal` passes `refuse_seed=False`, since revealing shared seed PII is
      fine.

    Returns the resolved `demo_session_id` (or `None`) so a caller can reuse it for a
    later event without a second `platform` read. Run this **before** the endpoint's
    state-machine / flag guards.
    """
    demo_session = await current_demo_session(request, db)
    demo_session_id = demo_session.id if demo_session is not None else None

    if lead.demo_session_id is not None and lead.demo_session_id != demo_session_id:
        raise HTTPException(status_code=404, detail="lead not found")

    if refuse_seed and demo_session_id is not None and lead.demo_session_id is None:
        raise HTTPException(
            status_code=409,
            detail="seed leads cannot be modified",
        )

    return demo_session_id


@router.post("", status_code=201)
async def create_lead_endpoint(
    new_lead: CreateLeadRequest,
    request: Request,
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

    # Resolve the caller's demo-visit session from the `pf_demo_session` cookie so
    # the new lead (and its events) carry the session id — read-only, no mint here
    # (`assume-persona` is the mint point). Outside the demo the cookie is absent and
    # this is `None`, leaving the lead untagged. The `demo_sessions` table is in the
    # `platform` schema, so the tenant-scoped session resolves it fine.
    demo_session = await current_demo_session(request, db)
    demo_session_id = demo_session.id if demo_session is not None else None

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
        demo_session_id=demo_session_id,
    )

    return {
        "lead": await build_masked_lead(identity.tenant_id, lead, demo_session_id)
    }


@router.get("")
async def list_leads(
    request: Request,
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

    In the shared demo tenant, schema scoping is not enough — many visitors share one
    schema — so the caller's demo session is resolved from the `pf_demo_session`
    cookie (read-only) and `visible_to_session` scopes the list to the shared seed
    baseline (`demo_session_id IS NULL`) plus the caller's own session rows. No demo
    cookie (or an expired one) resolves to `None` ⇒ seed-only. The predicate is
    applied to **both** the default list and the `unassigned` queue branch, so neither
    can ever surface another visitor's leads.

    Rows are ordered newest first (`created_at` DESC, tie-broken by `id` for a stable
    order across requests) and capped at `LEAD_LIST_LIMIT` — a simple safety cap, not
    pagination. The optional `unassigned` query param backs the two-tab queue UI:
    `false` (the default) returns all leads; `true` restricts to the unclaimed queue —
    leads with no owner **and** still `New` (the `AND` excludes both an owned lead and
    an unowned lead that has already left `New`). Each row is returned through the
    shared `build_masked_lead` builder under the `{"leads": […]}` envelope. The
    dependency chain inherits 401 (no session) and 400 (tenantless caller).
    """
    demo_session = await current_demo_session(request, db)
    demo_session_id = demo_session.id if demo_session is not None else None

    query = select(Lead).order_by(Lead.created_at.desc(), Lead.id)

    if unassigned:
        query = query.where(
            Lead.owner_user_id.is_(None), Lead.status == LeadStatus.NEW.value
        )

    query = visible_to_session(query, demo_session_id)

    leads = (
        await db.execute(query.limit(LEAD_LIST_LIMIT))
    ).scalars().all()

    tenant_id = identity.tenant_id
    return {
        "leads": [
            await build_masked_lead(tenant_id, lead, demo_session_id)
            for lead in leads
        ]
    }


@router.get("/{lead_id}")
async def get_lead(
    lead_id: uuid.UUID,
    request: Request,
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

    In the shared demo tenant, a session check matches the list path: after the load,
    a row owned by **another** demo session (`demo_session_id` neither `NULL` nor the
    caller's resolved session id) is treated as if it did not exist — the same
    `404 "lead not found"` as the cross-tenant case, so one visitor can neither read
    nor probe for another's lead. Seed rows (`NULL`) and the caller's own session rows
    resolve normally; a caller with no demo session sees only seed rows.

    The matched lead is returned through the shared `build_masked_lead` builder under
    the `{"lead": …}` envelope.
    """
    lead = (
        await db.execute(select(Lead).where(Lead.id == lead_id))
    ).scalar_one_or_none()

    if lead is None:
        raise HTTPException(status_code=404, detail="lead not found")

    # Demo-session read-isolation: a foreign session's row is a 404, identical to the
    # cross-tenant not-found. `refuse_seed=False` — a read may see shared seed rows. The
    # resolved session id is reused below so the masked read can derive `is_seed` /
    # `is_session_record` without a second `platform` read.
    demo_session_id = await _guard_loaded_lead_for_session(
        lead, request, db, refuse_seed=False
    )

    return {
        "lead": await build_masked_lead(identity.tenant_id, lead, demo_session_id)
    }


@router.get("/{lead_id}/timeline")
async def get_lead_timeline(
    lead_id: uuid.UUID,
    request: Request,
    identity: Identity = Depends(require_authenticated),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Return one lead's own domain events as an oldest-first timeline.

    The P1.9 tracer slice (Epic 1): a pure read/visibility surface over the lead's
    own `outbox` events. It guards the lead **exactly** as `get_lead` does — same
    load, same `_guard_loaded_lead_for_session(refuse_seed=False)` — so a missing,
    cross-tenant, or cross-session lead is the same `404 "lead not found"` as the
    detail read, and no caller can read or probe for a lead they cannot already see.
    Any authenticated tenant user may read it (the same `require_authenticated` as the
    detail read), with no tenant parameter — `get_tenant_db` scopes the outbox query
    to the caller's own schema.

    Once the lead is visible, `get_lead_timeline_rows` selects its outbox rows
    (keyed on `payload->>'entity_id'`, which every lead event carries) oldest-first
    and shapes them into neutral `kind="event"` / `status="occurred"` rows. The rows
    are returned under the `{"rows": […]}` envelope (an empty list when the lead has
    no events yet — the frontend console still renders, showing a calm empty note).
    Reaction sibling rows are a later epic's job; this tracer returns events only.
    """
    lead = (
        await db.execute(select(Lead).where(Lead.id == lead_id))
    ).scalar_one_or_none()

    if lead is None:
        raise HTTPException(status_code=404, detail="lead not found")

    # Reuse the detail read's isolation guard verbatim: a foreign session's row is a
    # 404, identical to the cross-tenant / missing not-found. `refuse_seed=False` — the
    # timeline is a read, so it may see shared seed rows (seed leads are empty until
    # Epic 5 seeds their trails).
    await _guard_loaded_lead_for_session(lead, request, db, refuse_seed=False)

    return {"rows": await get_lead_timeline_rows(db, lead_id)}


@router.post("/{lead_id}/claim")
async def claim_lead(
    lead_id: uuid.UUID,
    request: Request,
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

    # Demo-session write-isolation, **before** the state-machine guard: a foreign
    # session's row is a 404, a shared seed row a 409. The resolved session id is
    # reused below so this event carries it without a second `platform` read.
    demo_session_id = await _guard_loaded_lead_for_session(
        lead, request, db, refuse_seed=True
    )

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
            demo_session_id=demo_session_id,
        ),
    )

    return {
        "lead": await build_masked_lead(identity.tenant_id, lead, demo_session_id)
    }


@router.post("/{lead_id}/qualify")
async def qualify_lead(
    lead_id: uuid.UUID,
    request: Request,
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

    # Demo-session write-isolation, **before** the state-machine guard: a foreign
    # session's row is a 404, a shared seed row a 409. The resolved session id is
    # reused below so this event carries it without a second `platform` read.
    demo_session_id = await _guard_loaded_lead_for_session(
        lead, request, db, refuse_seed=True
    )

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
            demo_session_id=demo_session_id,
        ),
    )

    return {
        "lead": await build_masked_lead(identity.tenant_id, lead, demo_session_id)
    }


@router.get("/{lead_id}/conversion")
async def get_lead_conversion(
    lead_id: uuid.UUID,
    request: Request,
    identity: Identity = Depends(require_authenticated),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Return the non-PII "converted to" summary for a converted lead.

    Feeds the frozen-lead "Converted to" panel (TDD §5.5): the new Contact's name, its
    Household's name, and the opportunities opened (product-line key + stage). It is a
    read, so it gates on `require_authenticated` and reuses `get_lead`'s visibility
    guard exactly — a missing / cross-tenant / cross-session lead is a
    `404 "lead not found"` (`refuse_seed=False`, since a shared seed row is readable).

    A lead that exists and is visible but is **not** `Converted` has nothing to
    summarize, so it is a `409 "lead is not converted"` — distinct from the 404, so the
    UI can tell "no such lead" from "this lead hasn't been converted". The summary
    decrypts no PII (the contact's plaintext name is shown as-is) and is returned flat
    (TDD §5.5), not under an envelope.
    """
    lead = (
        await db.execute(select(Lead).where(Lead.id == lead_id))
    ).scalar_one_or_none()

    if lead is None:
        raise HTTPException(status_code=404, detail="lead not found")

    await _guard_loaded_lead_for_session(lead, request, db, refuse_seed=False)

    if lead.status != LeadStatus.CONVERTED.value:
        raise HTTPException(status_code=409, detail="lead is not converted")

    return await get_conversion_summary(db, lead)


@router.post("/{lead_id}/convert")
async def convert_lead_endpoint(
    lead_id: uuid.UUID,
    conversion: ConvertLeadRequest,
    request: Request,
    identity: Identity = Depends(
        require_capability(Capability.CREATE_EDIT_RECORDS)
    ),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Convert one held `Qualified` lead into the converted-world entities; freeze it.

    The core customer-value transaction (TDD §5.4 / §5.5). The guard hands the route
    an `Identity` only when the caller holds `CREATE_EDIT_RECORDS` (every other role a
    403, the anonymous caller a 401); `get_tenant_db` scopes the lookup and writes to
    the caller's schema and rejects a tenantless Platform Admin with a 400. The handler
    then applies its guards **in order** before doing any work:

    1. **Load the lead** by id within the caller's schema; a missing / cross-tenant id
       is a `404 "lead not found"` (schema scoping makes another tenant's row
       unreachable).
    2. **Demo-session write-isolation** (`refuse_seed=True`): a foreign session's row is
       a `404`, a shared seed row a `409` — a demo visitor never converts a row every
       visitor sees. The resolved session id is reused for the conversion's events.
    3. **Holder** — only the lead's owner may convert it; any other caller is a `403`.
    4. **Transition** — `assert_transition(Qualified → Converted)`; a lead in any other
       status is a `409` naming the current status.
    5. **Product-line keys** — every supplied key must be one the caller's tenant offers
       (resolved from the scoped session via the registry); any unknown key is a `422`.
       (The ≥1 structural rule is enforced earlier by `ConvertLeadRequest`.)

    Only then does `convert_lead` run the atomic sequence (new Household + Contact + one
    Opportunity per product line + a note-Task when the lead has notes, freeze, four
    events) on this request transaction — nothing is committed here. No new top-level
    resource is created from the caller's view (the lead is frozen in place), so the
    frozen lead is returned through `build_masked_lead` under `{"lead": …}` with a 200.
    """
    lead = (
        await db.execute(select(Lead).where(Lead.id == lead_id))
    ).scalar_one_or_none()

    if lead is None:
        raise HTTPException(status_code=404, detail="lead not found")

    # Demo-session write-isolation, before the holder / transition guards: a foreign
    # session's row is a 404, a shared seed row a 409. The resolved session id is
    # reused for the conversion's events without a second `platform` read.
    demo_session_id = await _guard_loaded_lead_for_session(
        lead, request, db, refuse_seed=True
    )

    # Holder guard: only the agent who owns the lead may convert it (a 403 otherwise).
    # Unlike qualify/reject, conversion is owner-only — the converting agent becomes the
    # owner of every entity it creates.
    if lead.owner_user_id != identity.user_id:
        raise HTTPException(
            status_code=403,
            detail="only the lead's owner can convert it",
        )

    try:
        assert_transition(LeadStatus(lead.status), LeadStatus.CONVERTED)
    except InvalidLeadTransition:
        raise HTTPException(
            status_code=409,
            detail=f"lead cannot be converted (status: {lead.status})",
        )

    # Every submitted product-line key must be one the caller's tenant offers — the
    # same per-request tenant check `create_lead_endpoint` runs, resolved from the
    # scoped session's `current_schema()` via the registry.
    active_schema = (await db.execute(text("SELECT current_schema()"))).scalar_one()
    tenant_config = tenant_by_schema(active_schema)
    allowed_keys = {product_line.key for product_line in tenant_config.product_lines}
    unknown_keys = [
        key for key in conversion.product_lines if key not in allowed_keys
    ]
    if unknown_keys:
        raise HTTPException(
            status_code=422,
            detail=f"unknown product line(s): {', '.join(unknown_keys)}",
        )

    await convert_lead(
        db,
        identity.tenant_id,
        lead=lead,
        product_lines=conversion.product_lines,
        actor_user_id=identity.user_id,
        actor_username=identity.username,
        actor_role=identity.role,
        demo_session_id=demo_session_id,
    )

    return {
        "lead": await build_masked_lead(identity.tenant_id, lead, demo_session_id)
    }


@router.post("/{lead_id}/reject")
async def reject_lead(
    lead_id: uuid.UUID,
    rejection: RejectLeadRequest,
    request: Request,
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

    # Demo-session write-isolation, **before** the state-machine guard: a foreign
    # session's row is a 404, a shared seed row a 409. The resolved session id is
    # reused below so this event carries it without a second `platform` read.
    demo_session_id = await _guard_loaded_lead_for_session(
        lead, request, db, refuse_seed=True
    )

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
            demo_session_id=demo_session_id,
        ),
    )

    return {
        "lead": await build_masked_lead(identity.tenant_id, lead, demo_session_id)
    }


@router.post("/{lead_id}/resolve-duplicate")
async def resolve_duplicate_lead(
    lead_id: uuid.UUID,
    resolution: ResolveDuplicateRequest,
    request: Request,
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

    # Demo-session write-isolation, **before** the flag / state-machine guards: a
    # foreign session's row is a 404, a shared seed row a 409. Resolved once up front so
    # the `reject` branch's event can reuse the id without a second `platform` read (the
    # `link` / `new` branches return before the event but still pass through this guard).
    demo_session_id = await _guard_loaded_lead_for_session(
        lead, request, db, refuse_seed=True
    )

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
        return {
        "lead": await build_masked_lead(identity.tenant_id, lead, demo_session_id)
    }

    if resolution.action == "new":
        # A genuinely different person: clear the flag (drop the linkage too).
        lead.duplicate_resolution = "new"
        lead.duplicate_of_lead_id = None
        await db.flush()
        return {
        "lead": await build_masked_lead(identity.tenant_id, lead, demo_session_id)
    }

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
            demo_session_id=demo_session_id,
        ),
    )

    return {
        "lead": await build_masked_lead(identity.tenant_id, lead, demo_session_id)
    }


@router.post("/{lead_id}/reveal")
async def reveal_field(
    lead_id: uuid.UUID,
    reveal: RevealLeadRequest,
    request: Request,
    identity: Identity = Depends(require_capability(Capability.REVEAL_PII)),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Decrypt and return **one** unmasked field of one of the caller's leads.

    The lead twin of `pii_demo`'s reveal — the only place plaintext lead PII crosses
    the API boundary, so it is the most guarded route here. It composes only existing
    pieces (no new crypto, masking, or scoping). Unlike `pii_demo`, a lead has **no**
    never-revealable deny-list: **every** encrypted field is revealable, so there is a
    single field check, not two. The flow is:

    1. **Refuse any unknown field** with a generic `422 "field is not revealable"`.
       The check runs **before** the database read, because the refusal is about the
       field, not the lead — an unknown field is a 422 even for an id that does not
       exist (mirroring `pii_demo`).
    2. **Fetch the lead by id** within the caller's tenant schema; an id absent in
       this tenant (missing or another tenant's) is a `404 "lead not found"`, reusing
       the read endpoints' string. In the shared demo tenant a foreign session's row is
       the same 404 (seed rows reveal normally — revealing shared seed PII is fine).
    3. **Decrypt** the requested field's stored blob with `decrypt_field`. An absent
       optional field (a lead with no street address) is returned as `value: null`
       with a 200 — the same uniform call site, matching the masked read's `null`
       rendering of absent optionals.
    4. **Await the reveal seam** (`on_pii_revealed`) *before* returning, with
       `entity_type = "lead"`, so the audit and the `pii.revealed` event record the
       reveal before the value leaves. The request session `db` is threaded in so the
       event enqueue rides this request transaction.
    5. Return `{"field": …, "value": …}`.

    The guard hands the route an `Identity` only when the caller holds `REVEAL_PII`
    (Read-Only and Platform Admin lack it → 403, the anonymous caller → 401);
    `get_tenant_db` points the session's `search_path` at the caller's own schema, so
    a caller can only ever reveal their own tenant's lead — all inherited, no tenant
    parameter. `decrypt_field` additionally binds `tenant_id` as AES-GCM associated
    data, so even a cross-tenant blob would fail to decrypt.
    """
    if reveal.field not in REVEALABLE_FIELDS:
        raise HTTPException(status_code=422, detail="field is not revealable")

    lead = (
        await db.execute(select(Lead).where(Lead.id == lead_id))
    ).scalar_one_or_none()

    if lead is None:
        raise HTTPException(status_code=404, detail="lead not found")

    # Demo-session read-isolation: a foreign session's row is a 404, identical to the
    # cross-tenant not-found, so one visitor can neither reveal nor probe for another's
    # PII. `refuse_seed=False` — revealing shared seed PII is fine, so there is no 409
    # here (the gap this closes is cross-session reads, not seed reads).
    await _guard_loaded_lead_for_session(lead, request, db, refuse_seed=False)

    encrypted_blob = getattr(lead, REVEALABLE_FIELDS[reveal.field])
    value = (
        await decrypt_field(identity.tenant_id, encrypted_blob)
        if encrypted_blob is not None
        else None
    )

    await on_pii_revealed(db, identity, "lead", lead_id, reveal.field)

    return {"field": reveal.field, "value": value}
