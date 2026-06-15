"""The polling relay — the carrier that moves outbox rows onto the broker.

Phase P1.5's event bus had two disconnected halves until now. Epic 3 gave us the
**transactional outbox**: a tenant action writes its event into that tenant's
``outbox`` table in the *same* transaction as the state change, so the event can
never be lost relative to the committed state. Epic 4 gave us the **broker side**:
`publish_envelope` puts one event onto RabbitMQ. Nothing yet **carried** a row from
the outbox to the broker. This module is that carrier.

The relay, every poll, walks each tenant's outbox, takes every row that has not
been published yet (``published_at IS NULL``), publishes it to the events exchange,
and stamps it ``published_at``. The one guarantee that shapes the whole design is
**at-least-once delivery**: a row is only marked *after* the broker has accepted
its message, so a crash between publish and mark simply re-publishes that row next
sweep — a duplicate (Epic 6's consumers dedupe), never a lost event. The order is
therefore always **publish first, mark second**, and that order is safe because
`publish_envelope` awaits publisher confirms — its await resolves only once
RabbitMQ has routed the message.

**Own-session, separate from any request.** Like `app.audit.service`, the relay
holds a module-global `session_factory` (the engine handed in by `app.db`,
monkeypatchable in tests) and opens its **own** short-lived session per tenant
sweep as the dedicated `outbox_relay` role — a role with exactly SELECT + UPDATE
on each ``outbox`` (Epic 2's grant), nothing more. The relay is **not** part of any
web request.

**Lifecycle caveat (Epic 7).** `publish_envelope` looks the exchange up with
`get_exchange`, it does not declare it, so the relay's channel must have had
`declare_topology` called on it (or on another channel of the same connection)
before the first sweep publishes. Epic 7's lifespan owns that ordering — declare
the topology on startup before starting the relay task.
"""

import asyncio
import logging

from sqlalchemy import func, select, text, update

from app.db import session_factory
from app.events.broker import publish_envelope
from app.events.envelope import EventEnvelope
from app.models.outbox_event import OutboxEvent
from app.tenancy.registry import OUTBOX_RELAY_ROLE, TENANTS, TenantConfig

__all__ = [
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "publish_pending_once",
    "run_relay_loop",
]

logger = logging.getLogger(__name__)

# The default poll interval, in seconds (the TDD's ~1s suggestion as a named
# constant). Sub-second demo latency is fine, and draining fully each sweep keeps
# the design simple while volumes are tiny. The runtime now sources the real value
# from config (`OUTBOX_POLL_INTERVAL_SECONDS`) and passes it in; this constant stays
# the signature default for direct callers and tests.
DEFAULT_POLL_INTERVAL_SECONDS = 1.0


async def publish_pending_once(broker_channel) -> int:
    """Publish every pending outbox row across all tenants once, return the count.

    Loops over every tenant in `registry.TENANTS`, sweeps each tenant's outbox on
    its own session, and returns the total number of rows published across all
    tenants (handy for the loop's logging and for tests). Each tenant is swept in
    its own transaction, so one tenant's failure does not roll back another's
    already-published marks.
    """
    total_published = 0
    for tenant in TENANTS:
        total_published += await _sweep_tenant_outbox(broker_channel, tenant)
    return total_published


async def _sweep_tenant_outbox(broker_channel, tenant: TenantConfig) -> int:
    """Publish-and-mark every pending row in one tenant's outbox, return the count.

    Opens the relay's **own** session and, in one transaction: becomes the
    `outbox_relay` role, points the `search_path` at the tenant's schema (both are
    fixed registry constants, never user input, so interpolating them is safe — the
    `audit/service.py` idiom), selects the unpublished rows oldest-first, and for
    **each** row **publishes first, then marks** ``published_at`` with the
    server-side `func.now()`. Commits once at the end.

    Publish-before-mark is the at-least-once guarantee: because `publish_envelope`
    awaits publisher confirms, a row is only marked after the broker has accepted
    its message. If the relay crashes mid-sweep, the unmarked rows simply re-publish
    next sweep. The `outbox_relay` role's SELECT + UPDATE grant is exactly what this
    needs and nothing more (no INSERT, no DELETE).
    """
    published_count = 0
    async with session_factory() as session:
        await session.begin()
        # `OUTBOX_RELAY_ROLE` and `tenant.schema_name` are fixed registry
        # constants, not user input, so this identifier interpolation is safe (the
        # `audit/service.py` `SET LOCAL ROLE` idiom).
        await session.execute(text(f"SET LOCAL ROLE {OUTBOX_RELAY_ROLE}"))
        await session.execute(
            text(f"SET LOCAL search_path TO {tenant.schema_name}")
        )

        pending_rows = (
            await session.execute(
                select(OutboxEvent)
                .where(OutboxEvent.published_at.is_(None))
                .order_by(OutboxEvent.occurred_at)
            )
        ).scalars().all()

        for row in pending_rows:
            await publish_envelope(broker_channel, _row_to_envelope(row))
            await session.execute(
                update(OutboxEvent)
                .where(OutboxEvent.id == row.id)
                .values(published_at=func.now())
            )
            published_count += 1

        await session.commit()
    return published_count


def _row_to_envelope(row: OutboxEvent) -> EventEnvelope:
    """Rebuild an `EventEnvelope` from one outbox row — the reverse of `enqueue_event`.

    The exact mirror image of `app.events.outbox.enqueue_event`'s envelope→row
    mapping: every envelope field maps 1:1 from the matching outbox column. (The
    relay-only `published_at` marker is not an envelope field, so it is dropped
    here.) Keeps wire == dataclass == outbox columns holding in both directions.
    """
    return EventEnvelope(
        event_id=row.event_id,
        event_type=row.event_type,
        schema_version=row.schema_version,
        tenant_id=row.tenant_id,
        occurred_at=row.occurred_at,
        correlation_id=row.correlation_id,
        causation_id=row.causation_id,
        actor_user_id=row.actor_user_id,
        actor_role=row.actor_role,
        demo_session_id=row.demo_session_id,
        payload=row.payload,
    )


async def run_relay_loop(
    broker_channel, poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS
) -> None:
    """Run the relay forever — sweep, sleep the poll interval, repeat.

    The thin production wrapper Epic 7's lifespan runs as a background task. Each
    iteration runs one `publish_pending_once` sweep, then sleeps `poll_interval_
    seconds`. Each sweep is wrapped in a try/except that logs and continues, so a
    single transient failure (a broker hiccup, a momentary DB blip) never kills the
    relay permanently — the next iteration tries again. The loop ends only when the
    task is cancelled (Epic 7's shutdown), which propagates cleanly out of the
    `asyncio.sleep`.
    """
    while True:
        try:
            published_count = await publish_pending_once(broker_channel)
            if published_count:
                logger.info("relay sweep published %d event(s)", published_count)
        except Exception:
            logger.exception("relay sweep failed; continuing to the next poll")
        await asyncio.sleep(poll_interval_seconds)
