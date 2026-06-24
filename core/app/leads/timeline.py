"""The per-lead event-timeline read — select one lead's own domain events.

The P1.9 tracer slice (Epic 1): read the lead's own outbox rows and shape them into
oldest-first timeline event rows. This is the query + row-build half of
``GET /api/leads/{lead_id}/timeline``; the route (`app/leads/router.py`) owns the
lead-load + isolation guard and wraps these rows in the response envelope.

**What it selects.** Every outbox row whose ``payload->>'entity_id'`` equals the
lead's id. *All* of a lead's domain events carry ``entity_id`` (``lead.created``,
``lead.assigned``, ``lead.qualified``, ``lead.rejected``, ``lead.duplicate_detected``)
— only ``lead.created`` additionally carries ``entity_type``, so the filter keys on
``entity_id`` **alone** (resolved decision, TDD §5/§9): keying on ``entity_type`` too
would silently drop every event after creation. ``entity_id`` is a UUID string, so
there is no cross-entity collision, and the query already runs under the caller's
tenant schema (``get_tenant_db``) so it can only ever see this tenant's outbox.

**Ordering.** Oldest-first by ``occurred_at`` ascending, tie-broken by ``id`` for a
stable order when two events share a timestamp (the newest-first list read's
``created_at DESC, id`` tiebreak, inverted).

**Isolation.** The route's lead-guard is the primary gate (the caller must already be
able to see the lead); this query is defense-in-depth — per-tenant schema-scoped, and
a lead's events only ever carry that lead's own ``demo_session_id``, so no row from
another tenant or session can appear. Later epics LEFT JOIN ``processed_events`` onto
these rows to add reaction siblings; this slice returns the event rows only.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.outbox_event import OutboxEvent


async def get_lead_timeline_rows(db: AsyncSession, lead_id: uuid.UUID) -> list[dict]:
    """Return one lead's own domain events as oldest-first timeline rows.

    Selects every outbox row whose ``payload->>'entity_id'`` matches ``lead_id``
    (all lead events carry it), ordered ``occurred_at`` ascending with an ``id``
    tiebreak, and shapes each into an event-row dict. Runs on the caller's
    tenant-scoped session, so it only ever reads this tenant's outbox.

    Each row is ``kind="event"`` / ``status="occurred"`` (a domain event is a
    neutral fact, never a state signal) carrying the raw dotted ``event_type``
    verbatim, the ISO ``occurred_at``, and the ``event_id`` / ``correlation_id``.
    Reaction sibling rows are a later epic's job; this tracer returns events only.
    """
    query = (
        select(OutboxEvent)
        .where(OutboxEvent.payload["entity_id"].astext == str(lead_id))
        .order_by(OutboxEvent.occurred_at.asc(), OutboxEvent.id)
    )
    events = (await db.execute(query)).scalars().all()

    return [
        {
            "kind": "event",
            "status": "occurred",
            "event_type": event.event_type,
            "occurred_at": event.occurred_at.isoformat(),
            "event_id": str(event.event_id),
            "correlation_id": str(event.correlation_id),
        }
        for event in events
    ]
