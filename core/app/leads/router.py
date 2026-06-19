"""The authenticated agent lead-intake HTTP surface: create one lead, masked.

This is the thin route layer for the first end-to-end intake slice (TDD §5.4,
`POST /api/leads`). Like `pii_demo/router.py`, it adds **no** new crypto, masking,
matching, or event logic of its own — it composes the shared `create_lead` core
(`app.leads.intake`) and the masked read builder (`app.leads.masking`), and owns
only the two things that are agent-route-specific:

- **The product-line key check.** Each submitted `product_lines_of_interest` key
  must be one the caller's tenant actually offers. The schema is resolved from the
  scoped session (`SELECT current_schema()`), mapped to its `TenantConfig` via the
  registry, and any key outside that tenant's key set is rejected with a `422`. (The
  ≥1-key structural rule is enforced earlier, by `CreateLeadRequest`.)
- **The born framing.** An agent-entered lead is born `Working`, owned by the
  entering agent (`agent_entered`); the core handles everything downstream.

It rides `get_tenant_db`, so isolation is automatic — there is **no tenant
parameter** — and the inherited 401 (no session) / 403 (lacking
`CREATE_EDIT_RECORDS`) / 400 (tenantless Platform Admin) come for free. The
response uses the named-envelope style the other routers use: `{"lead": …}`, built
once through `build_masked_lead` so the masked-by-default contract lives in one
place. No audit record is written on create — the audit enum has no lead member;
the create is observed only through the `lead.created` (+ `lead.duplicate_detected`)
outbox events the core enqueues.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import require_capability
from ..auth.provider import Identity
from ..auth.rbac import Capability
from ..tenancy.registry import tenant_by_schema
from ..tenancy.scoping import get_tenant_db
from .intake import create_lead
from .masking import build_masked_lead
from .schemas import CreateLeadRequest
from .state import LeadSource, LeadStatus

router = APIRouter(prefix="/api/leads")


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
