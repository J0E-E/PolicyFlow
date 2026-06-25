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

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import require_authenticated
from ..auth.provider import Identity  # noqa: F401 — documents the resolved identity
from ..demo.session import current_demo_session
from ..models.contact import Contact
from ..models.household import Household
from ..tenancy.scoping import get_tenant_db

router = APIRouter(prefix="/api/households")

# The household search is a type-to-search picker, not a browse list, so it caps at a
# tight number and orders alphabetically by name (a name search reads best in name
# order) — reusing the leads list's named-constant idiom, not its 200/newest-first.
HOUSEHOLD_SEARCH_LIMIT = 20


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
