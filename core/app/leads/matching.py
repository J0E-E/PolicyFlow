"""The duplicate matcher — find a prior lead by blind index, without decrypting.

When a lead arrives, the intake epics (7/10) need to know whether the same person
already exists in this tenant — and they need to know it **blindly**, without ever
decrypting anyone's contact details. This module is that one check: given a new
lead's email and phone, it looks for a prior lead in the tenant whose stored
*blind index* (the searchable one-way HMAC fingerprint, never the value itself)
matches either field, and returns that prior lead so the caller can flag the new
one as a possible duplicate and set `duplicate_of_lead_id`.

It adds no crypto of its own. It composes the earlier P1.3 pieces exactly as the
`pii_demo` lookup route does (`app.pii_demo.router.lookup_records`): the pure
normalizers (`normalize_email` / `normalize_phone`) fold each value to its
canonical form, `compute_blind_index` turns each normalized value into the
per-tenant fingerprint, and a single equality query over the `*_blind_index`
columns finds the match. **Nothing is decrypted on this path** — the match is made
on the fingerprint alone, and the query rides the caller's already-scoped session,
so it can only ever see this one tenant's leads.

The match semantics are locked at the gate and are a cross-epic contract:

- **OR match** — the same email *or* the same phone flags a duplicate.
- **Oldest wins** — when several prior leads match, the earliest-created one is the
  recorded match; `id` breaks ties so the choice is fully deterministic.
- **Self-exclusion** — the intake sequence INSERTs the new lead *before* matching,
  so the caller passes the new lead's id as `exclude_lead_id` to stop it matching
  itself. It defaults to `None` for any match-before-insert caller, and only filters
  a row out when an id is actually given.
- **Skip dead leads** — a `Rejected` lead is excluded as a match target;
  `New` / `Working` / `Qualified` stay eligible (a returning qualified lead is the
  strongest signal of a duplicate).
"""

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.lead import Lead
from ..pii.crypto import normalize_email, normalize_phone
from ..pii.service import compute_blind_index
from .state import LeadStatus

__all__ = ["find_duplicate_lead"]


async def find_duplicate_lead(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    email: str,
    phone: str,
    exclude_lead_id: uuid.UUID | None = None,
) -> Lead | None:
    """Return the oldest prior lead matching this email or phone, or `None`.

    Normalizes the email and phone, fingerprints each with `compute_blind_index`
    (once per field), and runs **one** tenant-scoped equality query for a lead
    whose stored `email_blind_index` or `phone_blind_index` equals either
    fingerprint. `Rejected` leads are excluded as match targets; when
    `exclude_lead_id` is given (the intake sequence INSERTs the new lead before
    matching, so it passes the new lead's id) that row is filtered out so a lead
    can never match itself. The result is ordered by `created_at` then `id`, so
    the **oldest** match wins deterministically, and limited to one row.

    Returns that prior `Lead` on a hit or `None` on a miss. **Nothing is decrypted
    here** — the match is made on the blind-index fingerprint alone — and the query
    rides the caller's already-scoped session, so it only ever sees this one
    tenant's leads (the tenant-isolation contract).
    """
    email_blind_index = await compute_blind_index(tenant_id, normalize_email(email))
    phone_blind_index = await compute_blind_index(tenant_id, normalize_phone(phone))

    query = (
        select(Lead)
        .where(
            or_(
                Lead.email_blind_index == email_blind_index,
                Lead.phone_blind_index == phone_blind_index,
            )
        )
        .where(Lead.status != LeadStatus.REJECTED)
    )
    if exclude_lead_id is not None:
        query = query.where(Lead.id != exclude_lead_id)
    query = query.order_by(Lead.created_at, Lead.id).limit(1)

    return (await db.execute(query)).scalars().first()
