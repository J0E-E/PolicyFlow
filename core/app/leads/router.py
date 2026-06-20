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

All three ride `get_tenant_db`, so isolation is automatic — there is **no tenant
parameter** — and the inherited 401 (no session) / 400 (tenantless Platform Admin)
come for free; `POST` additionally requires `CREATE_EDIT_RECORDS` (else 403) while
the two reads only require an authenticated tenant user (Read-Only included). Every
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
from ..models.lead import Lead
from ..tenancy.registry import tenant_by_schema
from ..tenancy.scoping import get_tenant_db
from .intake import create_lead
from .masking import build_masked_lead
from .schemas import CreateLeadRequest
from .state import LeadSource, LeadStatus

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
