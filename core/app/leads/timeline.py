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
another tenant or session can appear. The ``processed_events`` rows that drive the
reaction siblings are fetched by the same events' ids, so they inherit that same
isolation — ``processed_events`` carries no session of its own.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..events.catalog import consumers_for_event_type
from ..models.outbox_event import OutboxEvent
from ..models.processed_event import ProcessedEvent


def _derive_reaction_status(
    has_processed_row: bool, is_event_published: bool
) -> str:
    """Derive one reaction's status from real bus state (resolved decision D2).

    The status is never stored — it is read off the bus each time: a recorded
    ``processed_events`` row means the consumer has finished (``"done"``); with no
    such row, a *published* parent event means the relay has handed it off and the
    consumer is mid-flight (``"processing"``); an *unpublished* parent event means
    the relay has not even fanned it out yet (``"pending"``). ``"failed"`` lives in
    the vocabulary but is dormant — this derivation never emits it (M3 fills it).
    """
    if has_processed_row:
        return "done"
    if is_event_published:
        return "processing"
    return "pending"


async def get_lead_timeline_rows(db: AsyncSession, lead_id: uuid.UUID) -> list[dict]:
    """Return one lead's events and their reaction siblings as oldest-first rows.

    Selects every outbox row whose ``payload->>'entity_id'`` matches ``lead_id``
    (all lead events carry it), ordered ``occurred_at`` ascending with an ``id``
    tiebreak, then fetches the ``processed_events`` rows recorded against those
    events. Runs on the caller's tenant-scoped session, so it only ever reads this
    tenant's outbox and processed rows.

    The merged list is oldest-first: each event row is immediately followed by its
    own expected reaction rows. The expected reactions per event come from
    ``consumers_for_event_type`` (the single catalog binding source, in registry
    order), so a reaction appears the moment its parent event exists — before any
    ``processed_events`` row is written. Each reaction's status is derived from real
    bus state (``_derive_reaction_status``): ``pending`` → ``processing`` → ``done``.

    Each event row is ``kind="event"`` / ``status="occurred"`` (a domain event is a
    neutral fact, never a state signal). Each reaction row is ``kind="reaction"``,
    carrying the parent's ``event_type`` / ``event_id`` / ``correlation_id``, the
    consumer name, the derived status, and the ``processed_at`` as ``occurred_at``
    (or ``None`` while unprocessed). ``result_summary`` is passed through verbatim
    from the processed row (``None`` until Epic 3 computes and fills the column).
    """
    event_query = (
        select(OutboxEvent)
        .where(OutboxEvent.payload["entity_id"].astext == str(lead_id))
        .order_by(OutboxEvent.occurred_at.asc(), OutboxEvent.id)
    )
    events = (await db.execute(event_query)).scalars().all()

    event_ids = [event.event_id for event in events]
    processed_by_event_and_consumer: dict[tuple[uuid.UUID, str], ProcessedEvent] = {}
    if event_ids:
        processed_query = select(ProcessedEvent).where(
            ProcessedEvent.event_id.in_(event_ids)
        )
        processed_rows = (await db.execute(processed_query)).scalars().all()
        processed_by_event_and_consumer = {
            (row.event_id, row.consumer_name): row for row in processed_rows
        }

    rows: list[dict] = []
    for event in events:
        rows.append(
            {
                "kind": "event",
                "status": "occurred",
                "event_type": event.event_type,
                "occurred_at": event.occurred_at.isoformat(),
                "event_id": str(event.event_id),
                "correlation_id": str(event.correlation_id),
            }
        )
        for consumer_name in consumers_for_event_type(event.event_type):
            processed_row = processed_by_event_and_consumer.get(
                (event.event_id, consumer_name)
            )
            status = _derive_reaction_status(
                has_processed_row=processed_row is not None,
                is_event_published=event.published_at is not None,
            )
            rows.append(
                {
                    "kind": "reaction",
                    "status": status,
                    "consumer_name": consumer_name,
                    "event_type": event.event_type,
                    "event_id": str(event.event_id),
                    "correlation_id": str(event.correlation_id),
                    "result_summary": (
                        processed_row.result_summary
                        if processed_row is not None
                        else None
                    ),
                    "occurred_at": (
                        processed_row.processed_at.isoformat()
                        if processed_row is not None
                        else None
                    ),
                }
            )

    return rows
