"""The lead-conversion core — the one atomic transaction that converts a lead.

`convert_lead` turns a held `Qualified` lead into the converted-world entities — a
**Household**, a **Contact** mirroring the lead's person, one **Opportunity** per
confirmed product line, and (when the lead has notes) a note-**Task** — then freezes
the lead `Converted`. It is the P2.1 sibling of `create_lead`: it runs on the
caller's request session and **does not commit**, so every row it writes and every
event it enqueues land or roll back together (the transactional outbox), making the
whole conversion atomic via `get_tenant_db`.

It adds no crypto of its own; it composes the P1.3 PII seam. The Contact's sensitive
fields are **re-encrypted** from the lead — each blob is decrypted with
`decrypt_field` and re-encrypted with `encrypt_field`, so the Contact gets its own
independent ciphertext under the same tenant key — while the searchable plaintext
(`first_name` / `last_name` / `zip_code` / `age_band`) is carried across as-is. The
Contact has **no** blind-index columns (contact dedup is out of scope, D1).

Four events are emitted (D6), each a **non-PII** payload (entity references only —
never names or contact values) reusing the **lead's** `correlation_id` with
`causation_id=None`, so every entity of one conversion shares the lead's trace id:

- `household.created` → `{entity_id}`              (new-household path only)
- `contact.created`   → `{entity_id, household_id, source_lead_id}`
- `opportunity.created` ×N → `{entity_id, contact_id, household_id, product_line}`
- `lead.converted`    → `{entity_id, converted_contact_id, converted_opportunity_ids}`

No audit record is written (the audit enum has no conversion member); the conversion
is observed only through these outbox events. The endpoint owns the guards (capability
→ session-isolation → holder → `Qualified → Converted` transition) and the
product-line key check; this core assumes an already-guarded, already-loaded lead.

Epic 4 implements the **new-household** path only. The link-an-existing-household
branch (reuse a chosen household, no `household.created` event) is Epic 8.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from ..events.catalog import EventType as EventBusEventType
from ..events.envelope import build_envelope
from ..events.outbox import enqueue_event
from ..models.contact import Contact
from ..models.household import Household
from ..models.lead import Lead
from ..models.opportunity import Opportunity
from ..models.task import Task
from ..models.user import Role
from ..pii.service import decrypt_field, encrypt_field
from .state import LeadStatus

__all__ = ["convert_lead"]

# The literal opportunity stage and origin every conversion writes (D3): `stage`
# starts at `New` (no P2.2 state machine pulled forward) and `origin` records that
# the opportunity was born from a conversion.
_INITIAL_OPPORTUNITY_STAGE = "New"
_OPPORTUNITY_ORIGIN_CONVERSION = "conversion"

# The note-Task framing (D2): the converting agent's note hangs off the new contact.
_NOTE_TASK_RELATED_ENTITY_TYPE = "contact"
_NOTE_TASK_TYPE = "note"


async def _reencrypt_for_tenant(tenant_id: uuid.UUID, blob: bytes) -> bytes:
    """Decrypt one stored blob and re-encrypt it, returning a fresh ciphertext.

    The Contact mirrors the lead's PII, but with its **own** ciphertext rather than
    a byte-for-byte copy: the blob is decrypted with `decrypt_field` and re-encrypted
    with `encrypt_field` under the same tenant key (D1, "re-encrypt via P1.3"). Both
    use the tenant-id associated data, so this only ever runs within one tenant.
    """
    return await encrypt_field(tenant_id, await decrypt_field(tenant_id, blob))


async def convert_lead(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    lead: Lead,
    product_lines: list[str],
    actor_user_id: uuid.UUID | None,
    actor_username: str | None,
    actor_role: Role | None,
    demo_session_id: uuid.UUID | None,
) -> Lead:
    """Convert `lead` into a Household + Contact + opportunities (+ note-Task); freeze it.

    Runs the new-household conversion sequence on the caller's request session, in
    order (D5 / TDD §5.4), and **does not commit** — the row writes and the outbox
    events all land or all roll back together:

    1. **Household** — insert a new Household named ``"<last name> Household"``,
       stamped with the lead's `correlation_id` / `demo_session_id`; emit
       `household.created`.
    2. **Contact** — mirror the lead onto a new Contact (re-encrypted PII blobs,
       carried plaintext names / zip / age band), owned by the converting agent,
       linked to the household and the source lead; emit `contact.created`.
    3. **Opportunities** — one per confirmed product line (`stage='New'`,
       `origin='conversion'`), owned by the agent; emit `opportunity.created` each.
    4. **Note-Task** — only when the lead has notes, a `'note'` task carrying
       `lead.notes` onto the contact, assigned to the agent. **No** event.
    5. **Freeze** — set the lead `Converted` and record the converted-ref columns
       (`converted_contact_id`, `converted_opportunity_ids`); emit `lead.converted`.

    The caller (the endpoint) has already enforced every guard and loaded the lead.
    Returns the now-frozen `Lead`.
    """
    correlation_id = lead.correlation_id

    # 1. Household (new). The name is derived from the lead's (plaintext) last name.
    household = Household(
        name=f"{lead.last_name} Household",
        correlation_id=correlation_id,
        demo_session_id=demo_session_id,
    )
    db.add(household)
    await db.flush()
    await _emit(
        db,
        event_type=EventBusEventType.HOUSEHOLD_CREATED,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        payload={"entity_id": str(household.id)},
        correlation_id=correlation_id,
        demo_session_id=demo_session_id,
    )

    # 2. Contact — re-encrypt the lead's sensitive blobs, carry the plaintext fields.
    street_address_encrypted = None
    if lead.street_address_encrypted is not None:
        street_address_encrypted = await _reencrypt_for_tenant(
            tenant_id, lead.street_address_encrypted
        )
    contact = Contact(
        household_id=household.id,
        first_name=lead.first_name,
        last_name=lead.last_name,
        zip_code=lead.zip_code,
        age_band=lead.age_band,
        email_encrypted=await _reencrypt_for_tenant(tenant_id, lead.email_encrypted),
        phone_encrypted=await _reencrypt_for_tenant(tenant_id, lead.phone_encrypted),
        date_of_birth_encrypted=await _reencrypt_for_tenant(
            tenant_id, lead.date_of_birth_encrypted
        ),
        street_address_encrypted=street_address_encrypted,
        lead_source=lead.lead_source,
        owner_user_id=actor_user_id,
        owner_username=actor_username,
        source_lead_id=lead.id,
        correlation_id=correlation_id,
        demo_session_id=demo_session_id,
    )
    db.add(contact)
    await db.flush()
    await _emit(
        db,
        event_type=EventBusEventType.CONTACT_CREATED,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        payload={
            "entity_id": str(contact.id),
            "household_id": str(household.id),
            "source_lead_id": str(lead.id),
        },
        correlation_id=correlation_id,
        demo_session_id=demo_session_id,
    )

    # 3. Opportunities — one per confirmed product line, all rolled up to the household.
    opportunities: list[Opportunity] = []
    for product_line in product_lines:
        opportunity = Opportunity(
            contact_id=contact.id,
            household_id=household.id,
            product_line=product_line,
            stage=_INITIAL_OPPORTUNITY_STAGE,
            origin=_OPPORTUNITY_ORIGIN_CONVERSION,
            owner_user_id=actor_user_id,
            owner_username=actor_username,
            source_lead_id=lead.id,
            correlation_id=correlation_id,
            demo_session_id=demo_session_id,
        )
        db.add(opportunity)
        opportunities.append(opportunity)
    await db.flush()
    for opportunity in opportunities:
        await _emit(
            db,
            event_type=EventBusEventType.OPPORTUNITY_CREATED,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            payload={
                "entity_id": str(opportunity.id),
                "contact_id": str(contact.id),
                "household_id": str(household.id),
                "product_line": opportunity.product_line,
            },
            correlation_id=correlation_id,
            demo_session_id=demo_session_id,
        )

    # 4. Note-Task — only when the lead carries notes. No event (D2).
    if lead.notes:
        db.add(
            Task(
                related_entity_type=_NOTE_TASK_RELATED_ENTITY_TYPE,
                related_entity_id=contact.id,
                task_type=_NOTE_TASK_TYPE,
                body=lead.notes,
                assignee_user_id=actor_user_id,
                assignee_username=actor_username,
                correlation_id=correlation_id,
                demo_session_id=demo_session_id,
            )
        )
        await db.flush()

    # 5. Freeze the lead and record what it became, then emit `lead.converted`.
    lead.status = LeadStatus.CONVERTED.value
    lead.converted_contact_id = contact.id
    lead.converted_opportunity_ids = [opportunity.id for opportunity in opportunities]
    await db.flush()
    await _emit(
        db,
        event_type=EventBusEventType.LEAD_CONVERTED,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        payload={
            "entity_id": str(lead.id),
            "converted_contact_id": str(contact.id),
            "converted_opportunity_ids": [
                str(opportunity.id) for opportunity in opportunities
            ],
        },
        correlation_id=correlation_id,
        demo_session_id=demo_session_id,
    )

    return lead


async def _emit(
    db: AsyncSession,
    *,
    event_type: EventBusEventType,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    actor_role: Role | None,
    payload: dict,
    correlation_id: uuid.UUID,
    demo_session_id: uuid.UUID | None,
) -> None:
    """Enqueue one conversion event onto this tenant's outbox on the request session.

    A thin wrapper over `build_envelope` + `enqueue_event` that pins the conversion
    invariants in one place: every conversion event reuses the lead's
    `correlation_id` and carries `causation_id=None` (D6), and rides the caller's
    request transaction so it lands or rolls back with the row writes.
    """
    await enqueue_event(
        db,
        build_envelope(
            event_type=event_type,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            payload=payload,
            correlation_id=correlation_id,
            causation_id=None,
            demo_session_id=demo_session_id,
        ),
    )
