"""The shared lead-create core — the one sequence both intake routes reuse.

The agent route (Epic 7) and the public route (Epic 10) create a lead through the
**same** steps; only the framing differs (who calls, the born status/source/owner,
and the response shape). This module holds that shared sequence as one function so
the two routes can never drift on how a lead is encrypted, fingerprinted, matched,
or published — exactly the single-source-of-truth move `pii_demo`'s `create_record`
makes for its one route.

It adds no crypto, masking, or matching of its own; it **composes** the earlier
P1.3–P1.7 seams:

- `encrypt_field` encrypts `email` / `phone` / `date_of_birth` (and `street_address`
  when present); `compute_blind_index` over `normalize_email` / `normalize_phone`
  computes the two searchable fingerprints; `age_band_for` derives the plaintext
  band from the date of birth (never client-supplied).
- The row is built with a freshly minted `correlation_id` and `demo_session_id =
  None` (P1.8 owns the session lifecycle), added, flushed, and refreshed so the
  server-default timestamps are populated.
- `find_duplicate_lead` runs **after** the INSERT (passing the new lead's id as
  `exclude_lead_id` so it can never match itself); on a hit `duplicate_of_lead_id`
  is set and re-flushed.
- One `lead.created` event is enqueued via `enqueue_event` (a non-PII payload), and
  on a duplicate hit one `lead.duplicate_detected` event too — both reusing the
  row's `correlation_id`, so every later event for this lead shares one trace id.

Three deliberate boundaries, all locked at the gate:

- **No commit.** The whole sequence rides the caller's request session; `get_tenant_db`
  (agent) / `get_public_tenant_db` (public) owns the request transaction, so the row
  and its outbox events all land or all roll back together (the transactional outbox).
- **No audit record on create.** The audit `EventType` enum has no lead member; a
  lead create is observed only through the two outbox events, never the audit store.
- **No state-machine call.** Creation is a *birth*, not a transition, so it sets the
  born `status` literal directly and never calls `assert_transition` (which guards
  only moves *between* statuses).
"""

import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from ..events.catalog import EventType as EventBusEventType
from ..events.envelope import build_envelope
from ..events.outbox import enqueue_event
from ..models.lead import Lead
from ..models.user import Role
from ..pii.crypto import normalize_email, normalize_phone
from ..pii.masking import age_band_for
from ..pii.service import compute_blind_index, encrypt_field
from .matching import find_duplicate_lead
from .state import LeadSource, LeadStatus

__all__ = ["create_lead"]


async def create_lead(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    first_name: str,
    last_name: str,
    email: str,
    phone: str,
    date_of_birth: date,
    zip_code: str,
    product_lines_of_interest: list[str],
    street_address: str | None,
    preferred_contact_method: str | None,
    notes: str | None,
    lead_source: LeadSource,
    status: LeadStatus,
    owner_user_id: uuid.UUID | None,
    owner_username: str | None,
    actor_user_id: uuid.UUID | None,
    actor_role: Role | None,
    demo_session_id: uuid.UUID | None = None,
) -> Lead:
    """Create one lead for `tenant_id`, run the matcher, publish the events; return it.

    The shared create sequence both intake routes call. In order:

    1. **Encrypt the PII** — `email`, `phone`, and the ISO `date_of_birth` are
       encrypted with `encrypt_field`; `street_address` too when present (an absent
       optional stays `None`). The plaintext never lands in a column.
    2. **Fingerprint** — the email and phone blind indexes are computed with
       `compute_blind_index` over the normalized value, the searchable columns the
       matcher equality-queries without decryption.
    3. **Derive `age_band`** — from the required `date_of_birth` with `age_band_for`;
       it is never accepted from the caller.
    4. **Build + insert the row** — a fresh `correlation_id` is minted (every later
       event for this lead reuses it) and `demo_session_id` (the caller's demo-visit
       session, or `None` outside the demo) tags the row. The born `status` /
       `lead_source` are set directly from
       the passed enum values — creation is a birth, **not** a transition, so
       `assert_transition` is deliberately not called. The row is added, flushed, and
       refreshed so the server-default timestamps are populated.
    5. **Match for a duplicate** — `find_duplicate_lead` runs *after* the INSERT,
       passing the new lead's id as `exclude_lead_id` so it can never match itself.
       On a hit, `duplicate_of_lead_id` is set to the prior lead's id and re-flushed.
    6. **Publish** — one `lead.created` event is enqueued onto this tenant's outbox
       (a non-PII payload: the entity reference plus `lead_source`, `status`, the
       product-line keys, and the coarse `age_band`). On a duplicate hit, one
       `lead.duplicate_detected` event too (`entity_id` + `duplicate_of_lead_id`).
       Both reuse the row's `correlation_id`.

    The function **does not commit**: it rides the caller's request session, so the
    row and its outbox events all land or all roll back together (the transactional
    outbox). It writes **no** audit record — the audit enum has no lead member, so a
    lead create is observed only through the two outbox events. Returns the `Lead`.
    """
    email_encrypted = await encrypt_field(tenant_id, email)
    email_blind_index = await compute_blind_index(
        tenant_id, normalize_email(email)
    )
    phone_encrypted = await encrypt_field(tenant_id, phone)
    phone_blind_index = await compute_blind_index(
        tenant_id, normalize_phone(phone)
    )
    date_of_birth_encrypted = await encrypt_field(
        tenant_id, date_of_birth.isoformat()
    )
    age_band = age_band_for(date_of_birth)

    street_address_encrypted = None
    if street_address is not None:
        street_address_encrypted = await encrypt_field(tenant_id, street_address)

    correlation_id = uuid.uuid4()
    lead = Lead(
        first_name=first_name,
        last_name=last_name,
        email_encrypted=email_encrypted,
        email_blind_index=email_blind_index,
        phone_encrypted=phone_encrypted,
        phone_blind_index=phone_blind_index,
        date_of_birth_encrypted=date_of_birth_encrypted,
        age_band=age_band,
        zip_code=zip_code,
        street_address_encrypted=street_address_encrypted,
        product_lines_of_interest=product_lines_of_interest,
        preferred_contact_method=preferred_contact_method,
        notes=notes,
        lead_source=lead_source.value,
        status=status.value,
        owner_user_id=owner_user_id,
        owner_username=owner_username,
        correlation_id=correlation_id,
        demo_session_id=demo_session_id,
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead)

    # Run the duplicate matcher *after* the INSERT, excluding the new lead's own id
    # so it can never match itself. On a hit, record the linkage on the row and
    # re-flush so the column is durable within this same request transaction.
    duplicate = await find_duplicate_lead(
        db, tenant_id, email, phone, exclude_lead_id=lead.id
    )
    if duplicate is not None:
        lead.duplicate_of_lead_id = duplicate.id
        await db.flush()

    # Publish `lead.created` onto this tenant's outbox on the **same** request
    # session and transaction as the insert (the transactional outbox: the lead and
    # its event both land or both roll back). The payload carries the entity
    # reference plus the coarse `age_band` and the non-PII descriptors — **never** a
    # PII value (`notes`, names, contact details never appear). The row's
    # `correlation_id` is passed through so every later event for this lead shares it.
    await enqueue_event(
        db,
        build_envelope(
            event_type=EventBusEventType.LEAD_CREATED,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            payload={
                "entity_type": "lead",
                "entity_id": str(lead.id),
                "lead_source": lead_source.value,
                "status": status.value,
                "product_lines_of_interest": product_lines_of_interest,
                "age_band": age_band,
            },
            correlation_id=correlation_id,
            demo_session_id=demo_session_id,
        ),
    )

    # On a duplicate hit, also publish `lead.duplicate_detected` — the entity
    # reference plus the matched prior lead's id, sharing the same `correlation_id`,
    # again on this request transaction so it lands or rolls back with the rest.
    if duplicate is not None:
        await enqueue_event(
            db,
            build_envelope(
                event_type=EventBusEventType.LEAD_DUPLICATE_DETECTED,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                actor_role=actor_role,
                payload={
                    "entity_id": str(lead.id),
                    "duplicate_of_lead_id": str(duplicate.id),
                },
                correlation_id=correlation_id,
                demo_session_id=demo_session_id,
            ),
        )

    return lead
