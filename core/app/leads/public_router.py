"""The unauthenticated public lead-intake HTTP surface: `POST /api/public/intake`.

This is the public self-service intake route (TDD §5.4) — the front door a shopper
on the open internet posts to. It composes the **same** shared `create_lead` core
(`app.leads.intake`) the authenticated agent route uses, so the two can never drift
on how a lead is encrypted, fingerprinted, matched, or published. It adds **no** new
crypto, masking, or matching; it owns only the public-surface concerns the agent
route never needs:

- **Abuse controls.** A per-IP fixed-window rate limiter (`app.leads.rate_limit`)
  and a honeypot field (`website`) — the two brakes on an unauthenticated route.
- **Tenant from a slug.** With no session to scope by, the target tenant arrives as
  a slug in the request body; `get_public_tenant_db` (`app.tenancy.scoping`) resolves
  it to that tenant's schema + role (unknown slug → 404) and owns the request
  transaction the core rides.
- **A sanitized response.** Every success returns a flat `{"ok": True}` — never the
  masked lead, never any matched-lead data — so the public surface leaks nothing
  about who is (or already was) in the system.

The handler order is deliberate and load-bearing: rate-limit first (cheapest, before
any work), then the honeypot (before any DB touch), then resolve the tenant, then
scope + create. Validation (`PublicIntakeRequest`) has already run as a 422 before
any of this. The route takes `db` from `get_db` directly — not a scoping dependency —
because the slug it scopes by comes from the body, which the route reads and hands to
`get_public_tenant_db` by hand.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models.tenant import Tenant
from ..tenancy.registry import tenant_by_slug
from ..tenancy.scoping import get_public_tenant_db
from .intake import create_lead
from .rate_limit import client_ip_from_forwarded_for, public_intake_rate_limiter
from .schemas import PublicIntakeRequest
from .state import LeadSource, LeadStatus

router = APIRouter(prefix="/api/public")


@router.post("/intake")
async def public_intake_endpoint(
    body: PublicIntakeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create one public-form lead for the named tenant; return the sanitized body.

    The unauthenticated intake route. `PublicIntakeRequest` has already enforced the
    strict caps and formats as a 422 before this runs. In order:

    1. **Rate-limit (first).** The caller's IP is the first `X-Forwarded-For` hop;
       if it is over its allowance the request is rejected with a 429. A missing
       header (no IP to key on) **fails open** — the request proceeds unlimited,
       since dropping every header-less request would block legitimate callers behind
       a proxy that does not set the header.
    2. **Honeypot.** A non-empty `website` (a hidden field a human leaves blank but a
       bot fills) drops the submission with the same success-shaped `{"ok": True}`
       body the real path returns — **before** any database work, persisting and
       publishing nothing, so a bot learns nothing from the response.
    3. **Resolve the tenant + check its keys.** The slug is mapped to its
       `TenantConfig` via the registry (unknown → 404), every submitted product-line
       key is checked against that tenant's offered set (unknown key → 422), and the
       tenant's UUID is read from `platform.tenants` on the login-role session
       **before** scoping (the tenant role cannot see `platform`); a missing row → 404.
    4. **Scope + create.** `get_public_tenant_db` scopes the session to the tenant's
       schema and owns the request transaction; the shared `create_lead` core runs
       inside it, born `New` / unowned / `public_form` / system-actor. The core does
       not commit — the seam's commit on normal exit lands the lead and its outbox
       events together (the transactional outbox).
    5. **Return** the sanitized `{"ok": True}` — **identical** to the honeypot drop,
       never the masked lead or any matched-lead data, even on a duplicate hit.
    """
    client_ip = client_ip_from_forwarded_for(request.headers.get("x-forwarded-for"))
    if client_ip is not None and not public_intake_rate_limiter.is_allowed(client_ip):
        raise HTTPException(status_code=429, detail="rate limit exceeded")

    # The honeypot drop is success-shaped on purpose: a bot that filled `website`
    # must not be able to tell its submission was discarded. Nothing is persisted or
    # published — this returns before any database work begins.
    if body.website is not None and body.website.strip():
        return {"ok": True}

    # Resolve the tenant from the trusted registry first (the lookup is the
    # whitelist) and re-check the submitted product-line keys against its offered
    # set, exactly as the agent route does — key membership needs the tenant context,
    # so neither schema can enforce it.
    try:
        tenant_config = tenant_by_slug(body.tenant_slug)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown tenant")

    allowed_keys = {product_line.key for product_line in tenant_config.product_lines}
    unknown_keys = [
        key
        for key in body.product_lines_of_interest
        if key not in allowed_keys
    ]
    if unknown_keys:
        raise HTTPException(
            status_code=422,
            detail=f"unknown product line(s): {', '.join(unknown_keys)}",
        )

    # Read the tenant UUID on the login-role session, *before* scoping: the per-tenant
    # role set by `get_public_tenant_db` cannot see the `platform` schema, so the
    # `platform.tenants` read must happen first. A registry-known slug with no row is
    # a 404, mirroring the demo router's precedent.
    tenant_id = (
        await db.execute(
            select(Tenant.id).where(Tenant.slug == body.tenant_slug)
        )
    ).scalar_one_or_none()
    if tenant_id is None:
        raise HTTPException(status_code=404, detail="unknown tenant")

    # Scope to the tenant's schema and let the seam own the request transaction; the
    # shared create core runs inside it, born `New` / unowned / `public_form`, with no
    # actor (a system actor — there is no logged-in caller on this path). `tenant_id`
    # is read as a scalar UUID *before* this block: `get_public_tenant_db` rolls back
    # the login-role read transaction it opens, which would expire a loaded `Tenant`
    # ORM row and trigger a lazy reload (and a `MissingGreenlet`) on later access.
    async with get_public_tenant_db(body.tenant_slug, db) as scoped:
        await create_lead(
            scoped,
            tenant_id,
            first_name=body.first_name,
            last_name=body.last_name,
            email=body.email,
            phone=body.phone,
            date_of_birth=body.date_of_birth,
            zip_code=body.zip_code,
            product_lines_of_interest=body.product_lines_of_interest,
            street_address=body.street_address,
            preferred_contact_method=body.preferred_contact_method,
            notes=body.notes,
            lead_source=LeadSource.PUBLIC_FORM,
            status=LeadStatus.NEW,
            owner_user_id=None,
            owner_username=None,
            actor_user_id=None,
            actor_role=None,
        )

    # The sanitized success body — identical to the honeypot drop above. The masked
    # lead and any matched-lead data never reach the public wire.
    return {"ok": True}
