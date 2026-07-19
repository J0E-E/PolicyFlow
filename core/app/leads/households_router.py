"""The household search HTTP surface — backs the convert link picker (P2.1 Epic 8).

One route: ``GET /api/households?q=`` — a tenant-scoped, session-visible name search
the conversion screen's "link an existing household" picker reads. It is a thin read
layer composing the schema-less `Household` / `Contact` twins; it adds no crypto and
returns **only** display fields (the household name and its contacts' plaintext
names), never any encrypted PII.

Like the leads reads it rides `get_tenant_db`, so isolation is automatic (no tenant
parameter) and the 401 / 400 come for free; any authenticated tenant user may search.
The match is a case-insensitive substring on the household name, scoped to the seed
baseline plus the caller's own demo session (the same visibility rule the leads read
applies, expressed here on `Household`), capped and ordered for a tight picker
(`HOUSEHOLD_SEARCH_LIMIT`, name-ascending). Members are the household's contacts'
plaintext names, resolved in **one** follow-up query over the matched ids (no N+1).
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
from ..events.catalog import EventType
from ..events.envelope import build_envelope
from ..events.outbox import enqueue_event
from ..models.contact import Contact
from ..models.household import Household
from ..models.opportunity import Opportunity
from ..models.policy import Policy
from ..models.user import Role
from ..policies.read import serialize_policy
from ..renewals.overlay import renewal_due_policy_ids
from ..tenancy.registry import ProductLine, TenantConfig, tenant_by_schema
from ..tenancy.scoping import get_tenant_db

router = APIRouter(prefix="/api/households")

# The household search is a type-to-search picker, not a browse list, so it caps at a
# tight number and orders alphabetically by name (a name search reads best in name
# order) — reusing the leads list's named-constant idiom, not its 200/newest-first.
HOUSEHOLD_SEARCH_LIMIT = 20

# A policy counts toward coverage (and shows on the detail page) only while it is
# active — an issued policy that is `Active` or (overlay/stored) `Renewal Due`. Any
# other status (e.g. a future lapsed/cancelled value) neither covers a line nor lists.
ACTIVE_POLICY_STATUSES = ("Active", "Renewal Due")


def _visible_to_session(demo_session_column, demo_session_id: uuid.UUID | None):
    """A filter: rows in the seed baseline ∪ the caller's own demo session.

    Mirrors `search_households`'s inline visibility rule (and the leads reads'): a
    session-less caller sees only baseline (`demo_session_id IS NULL`) rows; a caller
    with a session also sees their own. Reused across `households` / `policies` here so
    the household, its policies, and its coverage all read through one visibility lens.
    """
    if demo_session_id is None:
        return demo_session_column.is_(None)
    return demo_session_column.is_(None) | (demo_session_column == demo_session_id)


async def _active_tenant_config(db: AsyncSession) -> TenantConfig:
    """Resolve the caller's tenant config from the scoped session's schema.

    Reads `current_schema()` (the opportunities router's pattern) and maps it to the
    frozen `TenantConfig`, whose `product_lines` are the source of truth for the
    cross-sell coverage check. `get_tenant_db` only admits a known schema, so it hits.
    """
    active_schema = (await db.execute(text("SELECT current_schema()"))).scalar_one()
    return tenant_by_schema(active_schema)


def _product_line_or_none(
    tenant_config: TenantConfig, key: str
) -> ProductLine | None:
    """Return the tenant's `ProductLine` for `key`, or `None` if it offers no such line."""
    return next(
        (line for line in tenant_config.product_lines if line.key == key), None
    )


@router.get("")
async def search_households(
    request: Request,
    q: str = "",
    identity=Depends(require_authenticated),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Return households whose name matches `q`, with their members' plaintext names.

    A case-insensitive substring match on the household name, scoped to the caller's
    tenant (via `get_tenant_db`'s search_path) and visibility (the seed baseline plus
    the caller's own demo session — a session-less caller sees only seed households),
    capped at `HOUSEHOLD_SEARCH_LIMIT` and ordered by name. An empty `q` matches every
    visible household (still capped). Members are each matched household's contacts,
    returned as plaintext `first_name` / `last_name` only (no encrypted PII). The
    shape is `{"households": [{id, name, members: [{first_name, last_name}, …]}, …]}`.
    """
    demo_session = await current_demo_session(request, db)
    demo_session_id = demo_session.id if demo_session is not None else None

    household_query = select(Household).where(Household.name.ilike(f"%{q}%"))
    if demo_session_id is None:
        household_query = household_query.where(Household.demo_session_id.is_(None))
    else:
        household_query = household_query.where(
            Household.demo_session_id.is_(None)
            | (Household.demo_session_id == demo_session_id)
        )
    household_query = household_query.order_by(
        Household.name.asc(), Household.id.asc()
    ).limit(HOUSEHOLD_SEARCH_LIMIT)

    households = (await db.execute(household_query)).scalars().all()
    household_ids = [household.id for household in households]

    members_by_household: dict[uuid.UUID, list[dict]] = {}
    if household_ids:
        contacts = (
            (
                await db.execute(
                    select(Contact)
                    .where(Contact.household_id.in_(household_ids))
                    .order_by(Contact.last_name, Contact.first_name)
                )
            )
            .scalars()
            .all()
        )
        for contact in contacts:
            members_by_household.setdefault(contact.household_id, []).append(
                {"first_name": contact.first_name, "last_name": contact.last_name}
            )

    return {
        "households": [
            {
                "id": household.id,
                "name": household.name,
                "members": members_by_household.get(household.id, []),
            }
            for household in households
        ]
    }


@router.get("/{household_id}")
async def get_household_detail(
    household_id: uuid.UUID,
    request: Request,
    identity=Depends(require_authenticated),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Return one household's contacts, active policies, and cross-sell suggestions.

    The read backing the household detail page (P2.4 Epic 13). Any authenticated tenant
    user may read; `get_tenant_db` scopes to the caller's schema and the visibility rule
    scopes to the seed baseline ∪ the caller's demo session — a household not visible to
    the caller is a `404` (indistinguishable from not-found).

    Shape: `{household:{id,name}, contacts:[{id,first_name,last_name}],
    policies:[<serialize_policy>, active only, overlay-aware], cross_sell:[{product_line,
    product_line_label}]}`. Policies are the household's **active** policies (status in
    `ACTIVE_POLICY_STATUSES`), each read through the derive-at-read *Renewal Due* overlay
    (a baseline policy lifts when the caller's session holds a renewal for it). Coverage
    (ADR 0002): a tenant product line is covered when ≥1 active policy's originating
    opportunity is on that line; `cross_sell` lists every uncovered line's `{key,label}`.
    """
    demo_session = await current_demo_session(request, db)
    demo_session_id = demo_session.id if demo_session is not None else None

    household = (
        await db.execute(
            select(Household).where(
                Household.id == household_id,
                _visible_to_session(Household.demo_session_id, demo_session_id),
            )
        )
    ).scalar_one_or_none()
    if household is None:
        raise HTTPException(status_code=404, detail="household not found")

    contacts = (
        (
            await db.execute(
                select(Contact)
                .where(Contact.household_id == household_id)
                .order_by(Contact.last_name, Contact.first_name)
            )
        )
        .scalars()
        .all()
    )

    # The household's active policies, joined to their originating opportunity for the
    # product line coverage keys on. Newest-issued first (the accept endpoint copies the
    # most-recently-issued active policy forward, Phase 4). Session-visible on the policy.
    policy_rows = (
        await db.execute(
            select(Policy, Opportunity.product_line)
            .join(Opportunity, Opportunity.id == Policy.opportunity_id)
            .where(
                Opportunity.household_id == household_id,
                Policy.status.in_(ACTIVE_POLICY_STATUSES),
                _visible_to_session(Policy.demo_session_id, demo_session_id),
            )
            .order_by(Policy.issued_at.desc(), Policy.id.asc())
        )
    ).all()
    policies = [policy for (policy, _product_line) in policy_rows]

    # Overlay: only a baseline policy is ever lifted (a session-owned one carries its
    # real status). One batch query over every active policy's own id — renewals point
    # `source_policy_id` at the baseline policy, so the policy's id is the overlay key.
    overlay_ids = await renewal_due_policy_ids(
        db, [policy.id for policy in policies], demo_session_id
    )

    # Cross-sell is suppressed entirely when the household has **no active policy** —
    # there is nothing to cross-sell against (ADR 0002), and the accept endpoint copies
    # a source policy forward, so an open line here would be a dead prompt. A fully
    # covered household falls out naturally (every line covered → empty list).
    tenant_config = await _active_tenant_config(db)
    covered_lines = {product_line for (_policy, product_line) in policy_rows}
    cross_sell = (
        [
            {"product_line": line.key, "product_line_label": line.label}
            for line in tenant_config.product_lines
            if line.key not in covered_lines
        ]
        if policies
        else []
    )

    return {
        "household": {"id": str(household.id), "name": household.name},
        "contacts": [
            {
                "id": str(contact.id),
                "first_name": contact.first_name,
                "last_name": contact.last_name,
            }
            for contact in contacts
        ],
        "policies": [
            serialize_policy(policy, overlay_renewal_due=policy.id in overlay_ids)
            for policy in policies
        ],
        "cross_sell": cross_sell,
    }


class CrossSellRequest(BaseModel):
    """The accept-cross-sell body: the tenant product line to open an opportunity on."""

    product_line: str


def _cross_sell_row(opportunity: Opportunity, product_line_label: str) -> dict:
    """Serialize the newly created cross-sell opportunity for the accept response.

    A minimal, non-PII shape (not the board's stage-machine row, which a brand-new
    cross-sell opportunity has no meaningful stage fields for yet): the ids, the line
    and its label, the `New` stage, the `cross_sell` origin, and the source policy it
    was copied from.
    """
    return {
        "id": str(opportunity.id),
        "household_id": str(opportunity.household_id),
        "contact_id": str(opportunity.contact_id),
        "product_line": opportunity.product_line,
        "product_line_label": product_line_label,
        "stage": opportunity.stage,
        "origin": opportunity.origin,
        "source_policy_id": (
            str(opportunity.source_policy_id)
            if opportunity.source_policy_id is not None
            else None
        ),
        "owner_username": opportunity.owner_username,
    }


@router.post("/{household_id}/cross-sell")
async def accept_cross_sell(
    household_id: uuid.UUID,
    body: CrossSellRequest,
    request: Request,
    identity: Identity = Depends(require_capability(Capability.CREATE_EDIT_RECORDS)),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Accept a cross-sell suggestion: open a `cross_sell` opportunity for `product_line`.

    Creates an `origin='cross_sell'`, `stage='New'` opportunity on the posted line,
    copying `owner_*` / `contact_id` / `source_policy_id` from the household's **most-
    recently-issued active policy** (its owner comes from that policy's originating
    opportunity). Session-tagged to the caller, a fresh `correlation_id`. Emits
    `opportunity.created` (real actor, new correlation, `causation_id=None`) on the
    request transaction — `get_tenant_db` commits on exit, so this never commits itself.
    Returns `{"opportunity": <row>}`.
    """
    demo_session = await current_demo_session(request, db)
    demo_session_id = demo_session.id if demo_session is not None else None

    household = (
        await db.execute(
            select(Household).where(
                Household.id == household_id,
                _visible_to_session(Household.demo_session_id, demo_session_id),
            )
        )
    ).scalar_one_or_none()
    if household is None:
        raise HTTPException(status_code=404, detail="household not found")

    # A cross-sell opportunity is always session-tagged (its whole point is a live-demo
    # suggestion) — a session-less caller has nothing to tag it to, and a NULL-session
    # cross-sell would pollute every session's baseline coverage. So refuse (409).
    if demo_session_id is None:
        raise HTTPException(
            status_code=409, detail="no active demo session"
        )

    # An unknown line is corrupt input; a 409 naming the key (the `_product_line_for`
    # precedent), not a create against a line the tenant does not sell.
    tenant_config = await _active_tenant_config(db)
    product_line = _product_line_or_none(tenant_config, body.product_line)
    if product_line is None:
        raise HTTPException(
            status_code=409, detail=f"unknown product line: {body.product_line}"
        )

    # The household's active policies, newest-issued first, each with its originating
    # opportunity (the owner is copied from there). The first is the source policy.
    active_rows = (
        await db.execute(
            select(Policy, Opportunity)
            .join(Opportunity, Opportunity.id == Policy.opportunity_id)
            .where(
                Opportunity.household_id == household_id,
                Policy.status.in_(ACTIVE_POLICY_STATUSES),
                _visible_to_session(Policy.demo_session_id, demo_session_id),
            )
            .order_by(Policy.issued_at.desc(), Policy.id.asc())
        )
    ).all()
    # Defensive: the suppression-gated UI never offers a prompt for a household with no
    # active policy, but there is no source policy to copy from, so refuse (409).
    if not active_rows:
        raise HTTPException(
            status_code=409, detail="household has no active policy to cross-sell from"
        )

    source_policy, source_opportunity = active_rows[0]

    # Holder: only the source policy's owning agent or any Tenant Admin may accept (the
    # stage-change holder rule) — else 403.
    is_owner = source_opportunity.owner_user_id == identity.user_id
    is_tenant_admin = identity.role == Role.TENANT_ADMIN
    if not (is_owner or is_tenant_admin):
        raise HTTPException(
            status_code=403,
            detail="only the source policy's owner or a tenant admin can cross-sell",
        )

    # Re-validate coverage against live data (the UI's suggestion may be stale): a line
    # already covered by an active policy is not cross-sellable → 409.
    covered_lines = {opportunity.product_line for (_policy, opportunity) in active_rows}
    if body.product_line in covered_lines:
        raise HTTPException(
            status_code=409,
            detail=f"product line already covered: {body.product_line}",
        )

    opportunity = Opportunity(
        contact_id=source_policy.contact_id,
        household_id=household_id,
        product_line=body.product_line,
        stage="New",
        origin="cross_sell",
        owner_user_id=source_opportunity.owner_user_id,
        owner_username=source_opportunity.owner_username,
        source_lead_id=None,
        source_policy_id=source_policy.id,
        renewal_cycle=None,
        correlation_id=uuid.uuid4(),
        demo_session_id=demo_session_id,
    )
    db.add(opportunity)
    await db.flush()

    await enqueue_event(
        db,
        build_envelope(
            event_type=EventType.OPPORTUNITY_CREATED,
            tenant_id=identity.tenant_id,
            actor_user_id=identity.user_id,
            actor_role=identity.role,
            payload={
                "entity_id": str(opportunity.id),
                "contact_id": str(opportunity.contact_id),
                "household_id": str(household_id),
                "origin": "cross_sell",
                "source_policy_id": str(source_policy.id),
            },
            correlation_id=opportunity.correlation_id,
            causation_id=None,
            demo_session_id=demo_session_id,
        ),
    )

    label = product_line.label if product_line is not None else body.product_line
    return {"opportunity": _cross_sell_row(opportunity, label)}
