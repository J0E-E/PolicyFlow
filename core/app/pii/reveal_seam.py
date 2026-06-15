"""The named reveal seam — `on_pii_revealed`, now filled through P1.5.

Every guarded reveal of a PII field (Epic 12's reveal endpoint) is a privileged
action that later phases observe: P1.4 (audit) and P1.5 (the `pii.revealed`
event) both now land here. This module is the single, named place both of those
effects live. Epic 12 already `await`s `on_pii_revealed` on the reveal path, so
P1.4/P1.5 fill this one body — with zero call-site churn beyond threading the
request session in (P1.5 needs it for the transactional outbox enqueue).

It does two things on every successful reveal, in this order:

1. **Enqueue one `pii.revealed` event** into the caller's tenant `outbox` via
   `enqueue_event`, on the **request** session/transaction (so the event rides
   the same transaction as the reveal and never orphans). The payload carries the
   entity reference plus the field **name** only — never the revealed value.
2. **Write one tenant-store `pii.revealed` audit record** carrying the field
   **name** only (never the revealed value), on the audit service's own
   immediately-committing session.

The enqueue runs **before** the audit write: the audit is its own session that
commits at once, so the two cannot share one transaction; ordering the
request-transaction enqueue before the own-session audit gives the cleanest
no-orphan behavior (a failing audit write rolls the request transaction back,
undoing the not-yet-committed outbox row — no orphan event). This mirrors the
Epic 8 `record.created` ordering in `app.pii_demo.router.create_record`.

It mirrors the established `record_platform_read_for_audit` seam in
`app.tenancy.scoping`, filled in P1.4 Epic 6.

Tenant isolation: both effects route to the caller's own tenant schema via
`identity.tenant_id` (the reveal endpoint rides `get_tenant_db` and requires
`REVEAL_PII`, so the caller is always a real tenant) — neither the outbox row nor
the audit row can cross a tenant boundary, and both store the field name only, so
the trail itself never leaks PII.

`Identity` is reused from its single source of truth (`app.auth.provider`) rather
than redeclared, exactly as `app.tenancy.scoping` does.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from ..audit.records import EventType, Outcome
from ..audit.service import record_audit_event
from ..auth.provider import Identity
from ..events.catalog import EventType as EventBusEventType
from ..events.envelope import build_envelope
from ..events.outbox import enqueue_event


async def on_pii_revealed(
    db: AsyncSession,
    identity: Identity,
    entity_type: str,
    entity_id: uuid.UUID,
    field_name: str,
) -> None:
    """The reveal seam for a guarded PII field reveal — filled through P1.5.

    Epic 12's reveal endpoint already `await`s this on every successful reveal, so
    P1.4 (audit) and P1.5 (the `pii.revealed` event) only fill this body — no call
    site changes beyond passing the request session in.

    It does two things, in this order:

    1. **Enqueues one `pii.revealed` event** into this tenant's `outbox` via
       `enqueue_event`, on the **request** session `db` and its transaction (the
       transactional outbox — the event lands or rolls back with the reveal). The
       payload carries the entity reference (`entity_type` / `entity_id`) plus the
       field **name** only — never the revealed value, so the event itself never
       leaks PII. `entity_id` is serialized as `str(...)` because the payload is
       JSON/JSONB and a raw UUID is not JSON-serializable.
    2. **Writes one record to the tenant store**: `identity.tenant_id` routes the
       row to that tenant's ``audit_records``, with `event_type` `pii.revealed`,
       the `entity_type`/`entity_id` of the revealed record, and
       `field_names=[field_name]` — the field **name** only.

    The enqueue runs **before** the audit write: the audit write is its own
    session that commits immediately, so the two cannot share one transaction;
    ordering the request-transaction enqueue first means a failing audit write
    rolls the request transaction back, undoing the not-yet-committed outbox row
    (no orphan event) — the Epic 8 ordering. `identity.role` is a `Role` (a
    `StrEnum`/`str`), so both the envelope and the audit service bind it as-is.
    The audit write propagates on failure (strict), so a reveal can never proceed
    unaudited.
    """
    await enqueue_event(
        db,
        build_envelope(
            event_type=EventBusEventType.PII_REVEALED,
            tenant_id=identity.tenant_id,
            actor_user_id=identity.user_id,
            actor_role=identity.role,
            payload={
                "entity_type": entity_type,
                "entity_id": str(entity_id),
                "field": field_name,
            },
        ),
    )

    await record_audit_event(
        tenant_id=identity.tenant_id,
        actor_user_id=identity.user_id,
        actor_role=identity.role,
        event_type=EventType.PII_REVEALED,
        outcome=Outcome.SUCCESS,
        entity_type=entity_type,
        entity_id=entity_id,
        field_names=[field_name],
    )
