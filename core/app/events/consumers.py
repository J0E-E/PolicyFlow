"""The terminal stub consumers — the two handlers that read off the broker queues.

Phase P1.5's event bus was assembled up to the broker but no further: a tenant
action writes its event into that tenant's ``outbox`` (Epic 3), the relay sweeps
and publishes each row to the topic exchange (Epic 5), and the topology fans every
event out to per-consumer durable queues with dead-letter plumbing (Epic 4).
Nothing yet **read** off those queues. This module is that reader — the two
terminal stub consumers, ``enrichment.stub`` and ``sync.logger``.

Each handler does the same four things, idempotently:

1. **Parse** the flat JSON broker body back into an `EventEnvelope`
   (`from_message_body`).
2. **Record** a tenant-scoped dedupe row in that tenant's ``processed_events``
   keyed on ``(consumer_name, event_id)``. A duplicate delivery hits the unique
   key and inserts nothing — that is the idempotency signal.
3. **Run a canned effect only when the row is fresh** — a recognizable, non-PII
   structured-metadata log. On a redelivery the effect is skipped, so the same
   event is never acted on twice.
4. **Ack** on success.

**Failure dead-letters, it never requeues.** If the body cannot be parsed or the
tenant cannot be routed, the handler logs the failure and **nacks without requeue**
(`message.nack(requeue=False)`), so the broker dead-letters the message into the
queue's DLQ (Epic 4's plumbing) rather than redelivering a message that will only
fail again. The handler does **not** re-raise: the message is terminally handled by
dead-lettering, and re-raising would confuse aio-pika's already-processed tracking.

**Own-session, separate from any request.** Like `app.audit.service` and
`app.events.relay`, this module holds a module-global `session_factory` (the engine
handed in by `app.db`, monkeypatchable in tests) and opens its **own** short-lived
session per recorded event as the dedicated `event_consumer` role — a role with
exactly INSERT + SELECT on each ``processed_events`` (Epic 2's grant), nothing more.
A consumer is **not** part of any web request.

**Tenant-isolation note (the project's cross-cutting axis).** The tenant schema is
resolved from the envelope's ``tenant_id`` by reading ``platform.tenants`` as the
login role (before any role switch, so it can see the shared schema) and is
whitelist-validated via `is_known_schema` before the name is ever interpolated — an
unknown tenant raises a loud `UnknownEventTenant`. The dedupe row is then written
under the `event_consumer` role into that tenant's own schema and nowhere else, and
the canned-effect log carries envelope **metadata only** — never a raw payload, so
no PII value can reach the logs.

**Stubs stay terminal (Decision 8).** A stub records, logs, and acks; it publishes
**no** completion event. The real enrichment/CRM outputs arrive in M3.
"""

import logging
import uuid

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from app.db import session_factory
from app.events.catalog import ENRICHMENT_STUB, SYNC_LOGGER
from app.events.envelope import EventEnvelope, from_message_body
from app.models.processed_event import ProcessedEvent
from app.tenancy.registry import EVENT_CONSUMER_ROLE, is_known_schema

__all__ = [
    "CONSUMER_HANDLERS",
    "UnknownEventTenant",
    "handle_enrichment",
    "handle_sync_logger",
]

logger = logging.getLogger(__name__)


class UnknownEventTenant(LookupError):
    """Raised when an event's `tenant_id` cannot be routed to a known schema.

    Fires when a `tenant_id` has **no row** in ``platform.tenants`` or its
    ``schema_name`` **fails `is_known_schema`** — the whitelist guard raises rather
    than interpolating an untrusted schema name into the ``SET LOCAL search_path``.
    Mirrors the loud-lookup `UnknownAuditTenant` precedent: a bad tenant is a
    misconfiguration, so the consumer fails loud and names the tenant id. The
    consume core catches this and dead-letters the message (nack without requeue)
    rather than crashing the consumer task.
    """

    def __init__(self, tenant_id: uuid.UUID) -> None:
        self.tenant_id = tenant_id
        super().__init__(
            f"cannot route an event for tenant {tenant_id}: no matching schema "
            "in platform.tenants / the registry whitelist"
        )


async def handle_enrichment(message) -> None:
    """Consume one message off ``enrichment.stub`` — dedupe, enrich-effect, ack.

    The frozen handler entrypoint Epic 7's lifespan wires to the
    ``enrichment.stub`` queue (TDD §5.3). A thin wrapper over the shared consume
    core with this consumer's name and its enrichment canned effect.
    """
    await _consume(message, ENRICHMENT_STUB, _run_enrichment_effect)


async def handle_sync_logger(message) -> None:
    """Consume one message off ``sync.logger`` — dedupe, sync-log-effect, ack.

    The frozen handler entrypoint Epic 7's lifespan wires to the ``sync.logger``
    queue (TDD §5.3). A thin wrapper over the shared consume core with this
    consumer's name and its sync-logger canned effect.
    """
    await _consume(message, SYNC_LOGGER, _run_sync_logger_effect)


# The consumer registry — each queue name paired with the handler that reads it.
# Epic 7's lifespan loops this to register one consumer per stub, so the set of
# consumers lives in **one** place next to the handlers rather than being
# hard-coded in the lifespan. This mirrors how `broker.TOPOLOGY` derives from
# `catalog.CONSUMER_BINDINGS`: a single source of truth means the lifespan's
# consumer list can never drift from the handlers defined here.
CONSUMER_HANDLERS = (
    (ENRICHMENT_STUB, handle_enrichment),
    (SYNC_LOGGER, handle_sync_logger),
)


async def _consume(message, consumer_name: str, run_effect) -> None:
    """Parse, record the dedupe row, run the effect if fresh, then ack — or DLQ.

    The shared consume core both handlers delegate to. On the happy path it parses
    the body into an `EventEnvelope`, records the tenant-scoped dedupe row, runs the
    canned `run_effect` **only when the row was freshly inserted** (a redelivery of
    the same event finds the row already there and skips the effect — idempotent),
    and acks.

    On **any** failure — an unparseable body or an `UnknownEventTenant` — it logs
    the failure and **nacks without requeue**, so the broker dead-letters the
    message into the queue's DLQ (Epic 4's plumbing). It does not re-raise: the
    message is terminally handled by dead-lettering, and re-raising would confuse
    aio-pika's already-processed tracking. The successful and idempotent-duplicate
    paths both ack.
    """
    try:
        envelope = from_message_body(message.body)
        is_fresh = await _record_processed_event(consumer_name, envelope)
        if is_fresh:
            run_effect(envelope)
        await message.ack()
    except Exception:
        logger.exception(
            "consumer %s failed to process a message; dead-lettering it",
            consumer_name,
        )
        await message.nack(requeue=False)


async def _record_processed_event(consumer_name: str, envelope: EventEnvelope) -> bool:
    """Record the dedupe row for `(consumer_name, event_id)`, return whether it is fresh.

    Resolves the envelope's `tenant_id` to its schema (raising `UnknownEventTenant`
    for an unknown tenant), then in one transaction on the consumer's **own**
    session: becomes the `event_consumer` role, points the ``search_path`` at the
    tenant's schema, and issues an ``INSERT … ON CONFLICT DO NOTHING`` on the
    ``(consumer_name, event_id)`` unique key. Returns ``True`` when a row was
    actually inserted (the event is **fresh** — process it) and ``False`` on a
    conflict (the event was **already processed** — skip the effect).

    The `id` is set client-side (`uuid.uuid4()`) and `processed_at` is omitted so
    the column's ``now()`` server default sets it. The Core ``insert`` construct
    emits no implicit ``RETURNING``, so it sidesteps Epic 3's INSERT-only-role
    ``RETURNING`` gotcha; the `event_consumer` role also holds SELECT, so it is
    double-safe.
    """
    schema_name = await _get_tenant_schema(envelope.tenant_id)
    async with session_factory() as session:
        await session.begin()
        # `EVENT_CONSUMER_ROLE` and `schema_name` are a fixed registry constant and
        # a whitelist-validated schema name (never user input), so this identifier
        # interpolation is safe — the `audit/service.py` / `relay.py` idiom.
        await session.execute(text(f"SET LOCAL ROLE {EVENT_CONSUMER_ROLE}"))
        await session.execute(text(f"SET LOCAL search_path TO {schema_name}"))

        insert_statement = (
            insert(ProcessedEvent)
            .values(
                id=uuid.uuid4(),
                consumer_name=consumer_name,
                event_id=envelope.event_id,
                tenant_id=envelope.tenant_id,
                event_type=envelope.event_type,
                correlation_id=envelope.correlation_id,
            )
            .on_conflict_do_nothing(index_elements=["consumer_name", "event_id"])
        )
        result = await session.execute(insert_statement)
        await session.commit()

    # `rowcount` is 1 when a row was inserted, 0 when the conflict skipped it.
    return result.rowcount == 1


async def _get_tenant_schema(tenant_id: uuid.UUID) -> str:
    """Return the schema name the event's `tenant_id` routes to, or raise.

    Opens the module-global `session_factory`'s own session as the default login
    role (no role switch), reads the tenant's ``schema_name`` from
    ``platform.tenants``, and whitelist-validates it. Raises `UnknownEventTenant`
    when no row exists or the schema fails `is_known_schema` — the guard that makes
    the later interpolation safe. Reading as the login role (before any ``SET LOCAL
    ROLE``) is what lets this see the shared ``platform`` schema, mirroring
    `audit/service.py`'s pre-switch read.
    """
    async with session_factory() as session:
        schema_name = (
            await session.execute(
                text(
                    "SELECT schema_name FROM platform.tenants WHERE id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            )
        ).scalar_one_or_none()

    if schema_name is None or not is_known_schema(schema_name):
        raise UnknownEventTenant(tenant_id)
    return schema_name


def _run_enrichment_effect(envelope: EventEnvelope) -> None:
    """The enrichment stub's canned effect — one structured, non-PII INFO log.

    Logs a fixed ``enrichment.stub`` effect label plus envelope **metadata only**
    (`consumer_name`, `event_id`, `event_type`, `tenant_id`, `correlation_id`) and
    the payload's entity reference (`entity_type` / `entity_id`) — never the raw
    payload, so no PII value reaches the logs. The `correlation_id` is logged so the
    future trace view (P1.9) can stitch a flow together. This is the recognizable
    placeholder for the real enrichment output M3 swaps in (Decision 8 — terminal,
    no completion event).
    """
    logger.info(
        "enrichment.stub effect: consumer=%s event_id=%s event_type=%s "
        "tenant_id=%s correlation_id=%s entity_type=%s entity_id=%s",
        ENRICHMENT_STUB,
        envelope.event_id,
        envelope.event_type,
        envelope.tenant_id,
        envelope.correlation_id,
        envelope.payload.get("entity_type"),
        envelope.payload.get("entity_id"),
    )


def _run_sync_logger_effect(envelope: EventEnvelope) -> None:
    """The sync logger's canned effect — one structured, non-PII INFO log.

    Logs a fixed ``sync.logger`` effect label plus envelope **metadata only**
    (`consumer_name`, `event_id`, `event_type`, `tenant_id`, `correlation_id`) —
    never the raw payload, so no PII value reaches the logs. The `correlation_id` is
    logged so the future trace view (P1.9) can stitch a flow together. This is the
    recognizable placeholder for the real downstream sync M3 swaps in (Decision 8 —
    terminal, no completion event).
    """
    logger.info(
        "sync.logger effect: consumer=%s event_id=%s event_type=%s "
        "tenant_id=%s correlation_id=%s",
        SYNC_LOGGER,
        envelope.event_id,
        envelope.event_type,
        envelope.tenant_id,
        envelope.correlation_id,
    )
