"""Tests for the stub consumers (Epic 6) — idempotent consume + DLQ on poison.

Two phases, mirroring the consumers module:

- **Phase 1 (DB + broker substrate).** On the real Postgres + RabbitMQ
  testcontainers (`database_engine` + `rabbitmq_container`): that one consume
  writes exactly **one** ``processed_events`` row for ``(consumer_name, event_id)``
  in the tenant schema, and that redelivery of the same ``event_id`` is idempotent
  — still **one** row, and the canned effect ran **once**.
- **Phase 2 (DB + broker substrate).** That a poison message (malformed JSON body)
  is nacked without requeue and dead-letters into the queue's DLQ
  (``enrichment.stub.dlq``).

A consumer opens its **own** session through the module-global
`app.events.consumers.session_factory` as the `event_consumer` role, so the DB
substrate points that global at the container database with a per-file monkeypatch
fixture, mirroring `container_relay_session_factory` in `test_relay.py`. The
envelope carries a real seeded ``SUNSHINE`` tenant id so the dedupe row lands in a
real, migrated tenant schema; the read-back uses the SELECT-capable superuser
engine connection, schema-qualified (the `event_consumer` role is INSERT+SELECT
only, and the test reads outside any role switch).

Requires the Docker daemon (no skip logic — the substrate's deliberate "fail
always when Docker is absent" choice). `pytest.ini` sets `asyncio_mode = auto`; the
DB/broker tests carry an explicit `@pytest.mark.asyncio` to match the other
substrate modules.
"""

import asyncio
import uuid

import aio_pika
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.events import consumers as consumers_module
from app.events.broker import EVENT_EXCHANGE, declare_topology, publish_envelope
from app.events.catalog import ENRICHMENT_STUB, EventType
from app.events.consumers import handle_enrichment
from app.events.envelope import EventEnvelope, build_envelope
from app.seed import seed
from app.tenancy.registry import SUNSHINE
from tests.conftest import build_amqp_url

# The tenant used throughout — pulled from the registry so schema name and DB role
# stay the single source of truth.
TENANT = SUNSHINE

# The enrichment stub's main queue and its DLQ (the `<name>.dlq` topology shape).
ENRICHMENT_QUEUE = ENRICHMENT_STUB
ENRICHMENT_DEAD_LETTER_QUEUE = f"{ENRICHMENT_STUB}.dlq"


# --- Substrate: fixtures + helpers -------------------------------------------


@pytest.fixture
def container_consumers_session_factory(database_engine, monkeypatch):
    """Point `app.events.consumers.session_factory` at the migrated container database.

    A consumer opens its **own** session through the module-global
    `app.events.consumers.session_factory` — separate from any request's `get_db`,
    the same own-session shape as `app.audit.service` / `app.events.relay`. The DB
    substrate must point that global at the container database, otherwise the
    consumer's dedupe write would hit the unreachable eager default engine.
    `monkeypatch` restores the real factory after each test. A mirror of
    `container_relay_session_factory` in `test_relay.py`.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    monkeypatch.setattr(consumers_module, "session_factory", session_factory)
    return session_factory


@pytest_asyncio.fixture
async def broker_channel(rabbitmq_container):
    """Yield one aio-pika channel against the RabbitMQ container, closed after.

    Opens a single robust connection and one channel — the "one shared connection,
    one channel per task" lifecycle — and tears both down when the test finishes so
    no connection leaks across tests. Mirrors the `broker_channel` fixture in
    `test_relay.py` / `test_broker_publish.py`.
    """
    connection = await aio_pika.connect_robust(build_amqp_url(rabbitmq_container))
    channel = await connection.channel()
    try:
        yield channel
    finally:
        await channel.close()
        await connection.close()


async def seed_and_get_tenant_id(session_factory, slug: str) -> uuid.UUID:
    """Seed the demo data, then return the `platform.tenants` id for `slug`.

    The same seed-then-read idiom as `test_audit_service.py`, so the envelope's
    `tenant_id` is a real id whose schema the consumer can route to.
    """
    async with session_factory() as session:
        await seed(session)
    async with session_factory() as session:
        tenant_id_row = await session.execute(
            text("SELECT id FROM platform.tenants WHERE slug = :slug"),
            {"slug": slug},
        )
        return tenant_id_row.scalar_one()


def build_consumer_envelope(tenant_id: uuid.UUID) -> EventEnvelope:
    """Build a fresh, recognisable non-PII `record.created` envelope for `tenant_id`.

    `build_envelope` mints the identity/timestamp fields; the actor and payload are
    fixed test values carrying only an entity reference (never a PII snapshot).
    """
    return build_envelope(
        event_type=EventType.RECORD_CREATED.value,
        tenant_id=tenant_id,
        actor_user_id=uuid.uuid4(),
        actor_role="tenant_admin",
        payload={"entity_type": "pii_demo", "entity_id": str(uuid.uuid4())},
    )


async def deliver_one(broker_channel, queue_name: str):
    """Get one message (with ack outstanding) off `queue_name`, or `None` if empty.

    `no_ack=False` so the message is delivered with its ack still pending — the
    handler under test is what acks or nacks it. `fail=False` returns `None` rather
    than raising when nothing is waiting.
    """
    queue = await broker_channel.get_queue(queue_name)
    return await queue.get(no_ack=False, fail=False)


async def count_processed_events(
    database_engine,
    schema_name: str,
    consumer_name: str,
    event_id: uuid.UUID,
) -> int:
    """Count `processed_events` rows for `(consumer_name, event_id)` in `schema_name`.

    Uses the SELECT-capable superuser engine connection (the test reads outside any
    role switch), schema-qualified — the faithful reader substrate from
    `test_relay.py`. The dedupe unique means this is 0 or 1.
    """
    async with database_engine.connect() as connection:
        return (
            await connection.execute(
                text(
                    f"SELECT count(*) FROM {schema_name}.processed_events "
                    "WHERE consumer_name = :consumer_name AND event_id = :event_id"
                ),
                {"consumer_name": consumer_name, "event_id": event_id},
            )
        ).scalar_one()


async def get_dead_lettered_message(broker_channel, dead_letter_queue: str):
    """Poll the DLQ for a dead-lettered message in a short bounded retry loop.

    Dead-lettering is broker-side and asynchronous — a publisher confirm does not
    cover the nack→DLX→DLQ hop — so a single immediate `get` can race ahead of the
    broker. This polls `dlq.get(no_ack=True, fail=False)` a bounded number of times
    with a tiny sleep between attempts, returning the first message that appears (or
    `None` if none arrives within the budget).
    """
    queue = await broker_channel.get_queue(dead_letter_queue)
    for _ in range(50):
        message = await queue.get(no_ack=True, fail=False)
        if message is not None:
            return message
        await asyncio.sleep(0.1)
    return None


# --- Phase 1: idempotent consume + canned effect -----------------------------


@pytest.mark.asyncio
async def test_consume_writes_exactly_one_processed_event_row(
    database_engine,
    container_consumers_session_factory,
    container_keys_session_factory,
    broker_channel,
):
    """One consume writes exactly one `processed_events` row for the consumer+event.

    Declare the topology, publish a `record.created` envelope (carrying a real
    SUNSHINE tenant id), deliver the message off `enrichment.stub`, and call
    `handle_enrichment`. Exactly one `processed_events` row must exist for
    `(enrichment.stub, event_id)` in the tenant schema.

    Also requests `container_keys_session_factory` because `seed()` encrypts the
    demo PII rows and so resolves per-tenant keys through
    `app.pii.keys.session_factory`, which must likewise point at the container —
    the same wiring `test_audit_service.py` needs.
    """
    tenant_id = await seed_and_get_tenant_id(
        container_consumers_session_factory, TENANT.slug
    )
    await declare_topology(broker_channel)
    envelope = build_consumer_envelope(tenant_id)

    await publish_envelope(broker_channel, envelope)
    message = await deliver_one(broker_channel, ENRICHMENT_QUEUE)
    assert message is not None
    await handle_enrichment(message)

    row_count = await count_processed_events(
        database_engine, TENANT.schema_name, ENRICHMENT_STUB, envelope.event_id
    )
    assert row_count == 1


@pytest.mark.asyncio
async def test_redelivery_is_idempotent_one_row_one_effect(
    database_engine,
    container_consumers_session_factory,
    container_keys_session_factory,
    broker_channel,
    monkeypatch,
):
    """Redelivering the same `event_id` stays one row and runs the effect once.

    Deliver the *same* envelope twice through `handle_enrichment`. The dedupe unique
    means still exactly one `processed_events` row, and — because the canned effect
    runs only when the row is freshly inserted — the effect (spied via monkeypatch)
    must have run exactly once across the two deliveries.

    Also requests `container_keys_session_factory` so `seed()`'s key resolution
    reads the container store (see the row-count test).
    """
    tenant_id = await seed_and_get_tenant_id(
        container_consumers_session_factory, TENANT.slug
    )
    await declare_topology(broker_channel)
    envelope = build_consumer_envelope(tenant_id)

    effect_call_count = 0

    def counting_effect(_envelope) -> None:
        nonlocal effect_call_count
        effect_call_count += 1

    monkeypatch.setattr(consumers_module, "_run_enrichment_effect", counting_effect)

    # Two separate deliveries of the same event id (publish, then deliver + handle).
    for _ in range(2):
        await publish_envelope(broker_channel, envelope)
        message = await deliver_one(broker_channel, ENRICHMENT_QUEUE)
        assert message is not None
        await handle_enrichment(message)

    row_count = await count_processed_events(
        database_engine, TENANT.schema_name, ENRICHMENT_STUB, envelope.event_id
    )
    assert row_count == 1
    assert effect_call_count == 1


# --- Phase 2: failure path — nack-without-requeue → DLQ -----------------------


@pytest.mark.asyncio
async def test_poison_message_dead_letters(
    container_consumers_session_factory, broker_channel
):
    """A poison message is nacked without requeue and dead-letters into the DLQ.

    Declare the topology, publish a malformed (non-JSON) body straight to the events
    exchange on `record.created`, deliver it off `enrichment.stub`, and call
    `handle_enrichment` — the body fails to parse, so the handler nacks without
    requeue. The message must then land in `enrichment.stub.dlq` (Epic 4's
    dead-letter plumbing), polled for because dead-lettering is broker-side async.
    """
    await declare_topology(broker_channel)
    poison_body = b"this is not valid json {"

    events_exchange = await broker_channel.get_exchange(EVENT_EXCHANGE)
    await events_exchange.publish(
        aio_pika.Message(body=poison_body),
        routing_key=EventType.RECORD_CREATED.value,
    )

    message = await deliver_one(broker_channel, ENRICHMENT_QUEUE)
    assert message is not None
    await handle_enrichment(message)

    dead_lettered = await get_dead_lettered_message(
        broker_channel, ENRICHMENT_DEAD_LETTER_QUEUE
    )
    assert dead_lettered is not None
    assert dead_lettered.body == poison_body
