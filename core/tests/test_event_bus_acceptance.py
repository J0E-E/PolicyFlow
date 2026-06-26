"""The named acceptance suite (Epic 11, P1.5) — the whole bus contract, end-to-end.

Epics 1–10 built every piece of the P1.5 event bus (the frozen envelope, the
per-tenant transactional ``outbox``, the polling relay, the RabbitMQ topology, the
two idempotent stub consumers, and the lifespan wiring) and the two real triggers
(``record.created`` on a pii-demo create, ``pii.revealed`` on a reveal). This file
is the single named proof that the whole contract holds end-to-end — the artifact
M3's real sidecars will bind to, so it directly de-risks Risk #4.

It adds **no production code.** It drives the already-assembled path on the real
Postgres + RabbitMQ testcontainers, in four append-only phases:

- **Phase 1 — headline end-to-end proof (fan-out + correlation).** A Sunshine Agent
  create enqueues a ``record.created`` outbox row; the relay publishes it; **both**
  stub consumers receive it (fan-out), the AMQP ``correlation_id`` / ``tenant_id``
  flow through unchanged, and each consumer writes exactly **one**
  ``processed_events`` row carrying that same ``correlation_id``.
- **Phase 2 — idempotency via the real at-least-once path.** Force the outbox row's
  ``published_at`` back to NULL (a simulated relay crash between publish and mark),
  let the relay re-publish the *same* event, redeliver to both handlers — still
  **one** ``processed_events`` row per consumer and the canned effect ran **once**.
- **Phase 3 — poison message dead-letters.** A malformed (non-JSON) body fails to
  parse, so ``handle_enrichment`` nacks without requeue and the broker dead-letters
  it into ``enrichment.stub.dlq``.
- **Phase 4 — per-tenant isolation of ``outbox`` + ``processed_events``.** Drive a
  create in **both** tenants; each tenant's outbox row and each consumer's
  ``processed_events`` row land in that tenant's own schema only — never the other's.

**Robustness against the never-reset substrate.** The container Postgres **and**
RabbitMQ are session-scoped and never reset between tests, and
``publish_pending_once`` drains **every** pending outbox row across **all** tenants.
So every assertion keys on this test's specific ``event_id`` / ``entity_id`` /
``(consumer_name, event_id)``, and a broker message is found by its ``message_id``
— never on "the table / queue is empty" or a global published count. Each test also
``purge``s its consumer queues right after ``declare_topology`` to start clean.

Because ``httpx.ASGITransport`` does not fire the app lifespan, this suite drives
the relay and the consumers **explicitly** — the established pattern from
``test_relay.py`` / ``test_consumers.py`` / ``test_lifespan.py``. The relay and the
consumers each open their **own** session through a module-global ``session_factory``
(as the ``outbox_relay`` / ``event_consumer`` role), so the per-file fixtures point
those globals at the container database, mirroring ``test_relay.py`` /
``test_consumers.py``. Every read-back uses the SELECT-capable superuser engine
connection, schema-qualified.

Requires the Docker daemon (no skip logic — the substrate's deliberate "fail always
when Docker is absent" choice). ``pytest.ini`` sets ``asyncio_mode = auto``; the
DB/broker substrate tests carry an explicit ``@pytest.mark.asyncio`` to match the
other substrate modules.
"""

import asyncio
import uuid

import aio_pika
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.events import consumers as consumers_module
from app.events import relay as relay_module
from app.events.broker import EVENT_EXCHANGE, declare_topology, publish_envelope
from app.events.catalog import ENRICHMENT_STUB, SCHEMA_VERSION, SYNC_LOGGER, EventType
from app.events.consumers import handle_enrichment, handle_sync_logger
from app.events.envelope import from_message_body
from app.events.relay import publish_pending_once
from app.models.user import Role
from app.seed import demo_users_for
from app.tenancy.registry import FLORIDA, SUNSHINE
from tests.conftest import build_amqp_url

from .test_endpoints_db import (  # noqa: F401 — `seeded` fixture is used by name
    login_as,
    seeded,
)

# The two stub consumers' main queues and the enrichment DLQ (the `<name>.dlq`
# topology shape) — pulled from the catalog constants so the names stay the single
# source of truth.
ENRICHMENT_QUEUE = ENRICHMENT_STUB
SYNC_LOGGER_QUEUE = SYNC_LOGGER
ENRICHMENT_DEAD_LETTER_QUEUE = f"{ENRICHMENT_STUB}.dlq"

# The two consumers paired with their handler, looped wherever a test drives both
# sides of the fan-out — mirrors `consumers.CONSUMER_HANDLERS` but local to the test.
CONSUMER_HANDLERS = (
    (ENRICHMENT_QUEUE, handle_enrichment),
    (SYNC_LOGGER_QUEUE, handle_sync_logger),
)

# The full create body the headline test reuses. Its plaintext values never reach
# the bus by contract (the no-PII-snapshot rule, proven separately in the Epic 8/9
# trigger tests); here the body is just a recognizable, complete create.
FULL_RECORD_BODY = {
    "display_name": "Acceptance Demo",
    "email": "acceptance.demo@example.com",
    "date_of_birth": "1950-03-15",
    "phone": "+1 (415) 555-1234",
    "mock_medicare_id": "123-45-1234",
}


# --- Substrate: fixtures -----------------------------------------------------


@pytest.fixture
def container_relay_session_factory(database_engine, monkeypatch):
    """Point `app.events.relay.session_factory` at the migrated container database.

    The relay opens its **own** session through the module-global
    `app.events.relay.session_factory` (as the `outbox_relay` role) — separate from
    any request's `get_db`. The substrate must point that global at the container
    database, otherwise the relay's sweep would hit the unreachable eager default
    engine. `monkeypatch` restores the real factory after each test. A verbatim
    mirror of the same-named fixture in `test_relay.py`.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    monkeypatch.setattr(relay_module, "session_factory", session_factory)
    return session_factory


@pytest.fixture
def container_consumers_session_factory(database_engine, monkeypatch):
    """Point `app.events.consumers.session_factory` at the migrated container database.

    A consumer opens its **own** session through the module-global
    `app.events.consumers.session_factory` (as the `event_consumer` role) — separate
    from any request's `get_db`. The substrate must point that global at the
    container database, otherwise the consumer's dedupe write would hit the
    unreachable eager default engine. `monkeypatch` restores the real factory after
    each test. A verbatim mirror of the same-named fixture in `test_consumers.py`.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    monkeypatch.setattr(consumers_module, "session_factory", session_factory)
    return session_factory


@pytest_asyncio.fixture
async def broker_channel(rabbitmq_container):
    """Yield one aio-pika channel against the RabbitMQ container, closed after.

    Opens a single robust connection and one channel — the "one shared connection,
    one channel per task" lifecycle — and tears both down when the test finishes so
    no connection leaks across tests. A mirror of the `broker_channel` fixture in
    `test_relay.py` / `test_consumers.py`.
    """
    connection = await aio_pika.connect_robust(build_amqp_url(rabbitmq_container))
    channel = await connection.channel()
    try:
        yield channel
    finally:
        await channel.close()
        await connection.close()


# --- Substrate: helpers (entity- / event-pinned) -----------------------------


async def purge_consumer_queues(broker_channel) -> None:
    """Empty both stub consumers' main queues so a sweep starts from clean queues.

    The container RabbitMQ is session-scoped and never reset between tests, so a
    prior test's leftover deliveries could still sit on `enrichment.stub` /
    `sync.logger`. Purging right after `declare_topology` means a `drain_for_event_id`
    poll only ever has to walk *this* test's messages. (The DLQ is not purged — Phase
    3 finds its message by body, and dead-lettering is rare.)
    """
    for queue_name, _handler in CONSUMER_HANDLERS:
        queue = await broker_channel.get_queue(queue_name)
        await queue.purge()


async def login_as_tenant_agent(db_client, tenant):
    """Log in as `tenant`'s first Agent persona by email; return the login response.

    Drives `POST /api/auth/login` with the per-tenant Agent's email (the
    `demo_users_for` persona idiom from `test_isolation_acceptance.py`), so a create
    can be driven in *each* tenant in turn for the Phase 4 isolation proof. The Agent
    holds `CREATE_EDIT_RECORDS`, the capability the create route gates on.
    """
    agent_email = next(
        email for email, role, _slug in demo_users_for(tenant.slug) if role is Role.AGENT
    )
    return await db_client.post(
        "/api/auth/login",
        json={"username": agent_email, "password": settings.seed_user_password},
    )


async def read_record_created_outbox_row(database_engine, schema_name, entity_id):
    """Return the one `record.created` outbox row for `entity_id` from `schema_name`.

    Keys on the payload's `entity_id` (the created record's id, which the test sees
    in the create response) rather than the `event_id` (minted inside the create
    handler, so the test never sees it) — the entity-pinned reader from
    `test_record_created_event.py`. Reads through the SELECT-capable superuser engine
    connection (the tenant role is INSERT-only on its own `outbox`), schema-qualified.
    Returns the single matching row, or raises if there is not exactly one.
    """
    async with database_engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    "SELECT event_id, event_type, schema_version, tenant_id, "
                    "occurred_at, correlation_id, causation_id, actor_user_id, "
                    "actor_role, demo_session_id, payload, published_at "
                    f"FROM {schema_name}.outbox "
                    "WHERE event_type = :event_type "
                    "AND payload->>'entity_id' = :entity_id"
                ),
                {
                    "event_type": str(EventType.RECORD_CREATED),
                    "entity_id": str(entity_id),
                },
            )
        ).all()
    assert len(rows) == 1, (
        f"expected exactly one record.created outbox row for entity {entity_id} "
        f"in {schema_name}, found {len(rows)}"
    )
    return rows[0]


async def read_published_at(database_engine, schema_name, event_id):
    """Read back one outbox row's `published_at` by `event_id` from `schema_name`.

    Uses the SELECT-capable superuser engine connection, schema-qualified — the
    faithful reader substrate from `test_relay.py`. Returns the `published_at` value
    (or `None` if NULL / no row).
    """
    async with database_engine.connect() as connection:
        return (
            await connection.execute(
                text(
                    f"SELECT published_at FROM {schema_name}.outbox "
                    "WHERE event_id = :event_id"
                ),
                {"event_id": event_id},
            )
        ).scalar_one_or_none()


async def reset_published_at_to_null(database_engine, schema_name, event_id):
    """Force one outbox row's `published_at` back to NULL via the superuser engine.

    Simulates a crash between publish and mark: the message was sent but the row was
    never stamped. Done through the superuser connection (not the relay role) because
    this is test setup, not relay behavior — the relay only ever *sets* `published_at`,
    never clears it. The `reset_published_at_to_null` idiom from `test_relay.py`.
    """
    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                f"UPDATE {schema_name}.outbox SET published_at = NULL "
                "WHERE event_id = :event_id"
            ),
            {"event_id": event_id},
        )


async def drain_for_event_id(
    broker_channel,
    queue_name,
    event_id,
    max_messages=5000,
    empty_polls=20,
    empty_poll_delay=0.1,
):
    """Get the message whose `message_id` equals `event_id` off `queue_name`.

    The container broker is never reset and `publish_pending_once` flushes **every**
    tenant's accumulated unpublished outbox rows — the whole suite's backlog — and
    `sync.logger` binds `#`, so this queue can hold a large backlog ahead of this
    test's event. This `get`s (and acks, via `no_ack=True`) up to `max_messages` from
    the queue, returning the first whose AMQP `message_id` is this test's `event_id`
    and discarding the rest. `max_messages` is deliberately high so a big backlog
    cannot exhaust the budget before the target is reached (the cause of the earlier
    "never arrived" flake under full-suite load). The entity-pinned reader idiom from
    `test_record_created_event.py`, extended to the broker side via `message_id`.

    An empty `get` does **not** end the drain: the relay publishes asynchronously, so
    the message can still be in flight. The drain waits out up to `empty_polls`
    **consecutive** empty reads (`empty_poll_delay` apart) before giving up; any
    delivery resets that counter. Returns `None` only if the matching message never
    arrives within the budget.
    """
    queue = await broker_channel.get_queue(queue_name)
    seen_messages = 0
    seen_empty = 0
    while seen_messages < max_messages and seen_empty < empty_polls:
        message = await queue.get(no_ack=True, fail=False)
        if message is None:
            seen_empty += 1
            await asyncio.sleep(empty_poll_delay)
            continue
        seen_empty = 0
        if message.message_id == str(event_id):
            return message
        seen_messages += 1
    return None


async def deliver_for_event_id(
    broker_channel,
    queue_name,
    event_id,
    max_messages=5000,
    empty_polls=20,
    empty_poll_delay=0.1,
):
    """Get the message for `event_id` off `queue_name` with its ack still pending.

    Like `drain_for_event_id` but `no_ack=False`, so the returned message's ack is
    outstanding and the handler under test is what acks or nacks it. Non-matching
    messages walked past are acked (`no_ack=True` would lose them; here they are
    explicitly acked) so they do not block the queue for a later poll. The high
    `max_messages` budget absorbs the suite's backlog, and up to `empty_polls`
    **consecutive** empty reads are waited out (any delivery resets the counter) for
    the asynchronously-published message to arrive — the same backlog + race guards
    `drain_for_event_id` uses.
    """
    queue = await broker_channel.get_queue(queue_name)
    seen_messages = 0
    seen_empty = 0
    while seen_messages < max_messages and seen_empty < empty_polls:
        message = await queue.get(no_ack=False, fail=False)
        if message is None:
            seen_empty += 1
            await asyncio.sleep(empty_poll_delay)
            continue
        seen_empty = 0
        if message.message_id == str(event_id):
            return message
        await message.ack()
        seen_messages += 1
    return None


async def read_processed_event(database_engine, schema_name, consumer_name, event_id):
    """Return the one `processed_events` row for `(consumer_name, event_id)`, or None.

    Reads `correlation_id` (and the dedupe keys) back through the SELECT-capable
    superuser engine connection, schema-qualified — the `test_consumers.py` reader,
    so a test can assert the row's `correlation_id` flowed through end-to-end. The
    dedupe unique means at most one row matches.
    """
    async with database_engine.connect() as connection:
        return (
            await connection.execute(
                text(
                    "SELECT consumer_name, event_id, tenant_id, correlation_id "
                    f"FROM {schema_name}.processed_events "
                    "WHERE consumer_name = :consumer_name AND event_id = :event_id"
                ),
                {"consumer_name": consumer_name, "event_id": event_id},
            )
        ).one_or_none()


async def count_processed_events(database_engine, schema_name, consumer_name, event_id):
    """Count `processed_events` rows for `(consumer_name, event_id)` in `schema_name`.

    The session-scoped container DB is never reset, so the proof keys on the specific
    `(consumer_name, event_id)` — the count is 0 or 1 (the dedupe unique). The
    `test_consumers.py` count reader.
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


async def get_dead_lettered_message(broker_channel, dead_letter_queue):
    """Poll the DLQ for a dead-lettered message in a short bounded retry loop.

    Dead-lettering is broker-side and asynchronous — a publisher confirm does not
    cover the nack→DLX→DLQ hop — so a single immediate `get` can race ahead of the
    broker. This polls `dlq.get(no_ack=True, fail=False)` a bounded number of times
    with a tiny sleep between attempts, returning the first message that appears (or
    `None` if none arrives within the budget). The `get_dead_lettered_message` idiom
    from `test_consumers.py`.
    """
    queue = await broker_channel.get_queue(dead_letter_queue)
    for _ in range(50):
        message = await queue.get(no_ack=True, fail=False)
        if message is not None:
            return message
        await asyncio.sleep(0.1)
    return None


# --- Phase 1: headline end-to-end proof (fan-out + correlation) --------------


@pytest.mark.asyncio
async def test_create_fans_out_to_both_consumers_with_correlation(
    seeded,
    db_client,
    container_audit_session_factory,
    database_engine,
    container_relay_session_factory,
    container_consumers_session_factory,
    broker_channel,
):
    """A create flows create → relay → BOTH stubs once, correlation_id end-to-end.

    The headline proof. As the Sunshine Agent, `POST /api/pii-demo/` enqueues a
    `record.created` outbox row (read back by the created record id; capture its
    `event_id` + `correlation_id`, assert `published_at` is still NULL). Declare the
    topology, purge the consumer queues, then `publish_pending_once` — the relay
    publishes the row and marks `published_at`. For **both** `enrichment.stub` and
    `sync.logger`: the message arrives keyed by `message_id` (fan-out), its AMQP
    `correlation_id` equals the captured one and its `tenant_id` header equals the
    event's tenant id, and the JSON body round-trips to an envelope with that same
    `correlation_id`. Calling each handler writes exactly **one** `processed_events`
    row carrying the captured `correlation_id`.
    """
    login_response = await login_as(db_client, Role.AGENT)
    assert login_response.status_code == 200

    create_response = await db_client.post("/api/pii-demo/", json=FULL_RECORD_BODY)
    assert create_response.status_code == 201
    created_id = uuid.UUID(create_response.json()["record"]["id"])

    enqueued = await read_record_created_outbox_row(
        database_engine, SUNSHINE.schema_name, created_id
    )
    event_id = enqueued.event_id
    correlation_id = enqueued.correlation_id
    tenant_id = enqueued.tenant_id
    assert enqueued.published_at is None

    await declare_topology(broker_channel)
    await purge_consumer_queues(broker_channel)

    published_count = await publish_pending_once(broker_channel)
    assert published_count >= 1

    published_at = await read_published_at(
        database_engine, SUNSHINE.schema_name, event_id
    )
    assert published_at is not None

    # Fan-out: the same event arrives on BOTH consumer queues, correlation + tenant
    # flow through unchanged, and the body round-trips to an envelope with that id.
    for queue_name, handler in CONSUMER_HANDLERS:
        message = await deliver_for_event_id(broker_channel, queue_name, event_id)
        assert message is not None, f"event {event_id} never arrived on {queue_name}"
        assert message.correlation_id == str(correlation_id)
        assert message.headers["tenant_id"] == str(tenant_id)
        round_tripped = from_message_body(message.body)
        assert round_tripped.event_id == event_id
        assert round_tripped.correlation_id == correlation_id

        await handler(message)

    # Exactly one processed_events row per consumer, each carrying the correlation id.
    for consumer_name in (ENRICHMENT_STUB, SYNC_LOGGER):
        row_count = await count_processed_events(
            database_engine, SUNSHINE.schema_name, consumer_name, event_id
        )
        assert row_count == 1
        processed = await read_processed_event(
            database_engine, SUNSHINE.schema_name, consumer_name, event_id
        )
        assert processed is not None
        assert processed.correlation_id == correlation_id


# --- Phase 2: idempotency via the real at-least-once path --------------------


@pytest.mark.asyncio
async def test_relay_redelivery_stays_idempotent_one_row_one_effect(
    seeded,
    db_client,
    container_audit_session_factory,
    database_engine,
    container_relay_session_factory,
    container_consumers_session_factory,
    broker_channel,
    monkeypatch,
):
    """A relay re-publish (crash between publish and mark) is consumed only once.

    After a first full consume, force the outbox row's `published_at` back to NULL —
    the simulated relay crash between publish and mark — and `publish_pending_once`
    again, so the relay re-publishes the **same** `event_id` (the real at-least-once
    path). Redeliver to both handlers. Each consumer must STILL have exactly one
    `processed_events` row, and the canned effect (spied via monkeypatch, the
    `test_consumers.py` idiom) must have run exactly **once** across the two
    deliveries — the dedupe on `(consumer_name, event_id)` absorbs the redelivery.
    """
    login_response = await login_as(db_client, Role.AGENT)
    assert login_response.status_code == 200
    create_response = await db_client.post("/api/pii-demo/", json=FULL_RECORD_BODY)
    assert create_response.status_code == 201
    created_id = uuid.UUID(create_response.json()["record"]["id"])

    enqueued = await read_record_created_outbox_row(
        database_engine, SUNSHINE.schema_name, created_id
    )
    event_id = enqueued.event_id

    # Spy each canned effect so we can prove it ran exactly once across both rounds.
    enrichment_effect_calls = 0
    sync_logger_effect_calls = 0

    def counting_enrichment_effect(_envelope) -> None:
        nonlocal enrichment_effect_calls
        enrichment_effect_calls += 1

    def counting_sync_logger_effect(_envelope) -> None:
        nonlocal sync_logger_effect_calls
        sync_logger_effect_calls += 1

    monkeypatch.setattr(
        consumers_module, "_run_enrichment_effect", counting_enrichment_effect
    )
    monkeypatch.setattr(
        consumers_module, "_run_sync_logger_effect", counting_sync_logger_effect
    )

    await declare_topology(broker_channel)
    await purge_consumer_queues(broker_channel)

    # Round 1: publish, deliver to both handlers, consume once each.
    await publish_pending_once(broker_channel)
    for queue_name, handler in CONSUMER_HANDLERS:
        message = await deliver_for_event_id(broker_channel, queue_name, event_id)
        assert message is not None
        await handler(message)

    # Round 2: the relay crashed between publish and mark — re-publish the same event.
    await reset_published_at_to_null(database_engine, SUNSHINE.schema_name, event_id)
    republished_count = await publish_pending_once(broker_channel)
    assert republished_count >= 1
    for queue_name, handler in CONSUMER_HANDLERS:
        message = await deliver_for_event_id(broker_channel, queue_name, event_id)
        assert message is not None
        await handler(message)

    # Still one row per consumer, and each effect ran exactly once despite two deliveries.
    for consumer_name in (ENRICHMENT_STUB, SYNC_LOGGER):
        row_count = await count_processed_events(
            database_engine, SUNSHINE.schema_name, consumer_name, event_id
        )
        assert row_count == 1
    assert enrichment_effect_calls == 1
    assert sync_logger_effect_calls == 1


# --- Phase 3: poison message dead-letters -------------------------------------


@pytest.mark.asyncio
async def test_poison_message_dead_letters(
    container_consumers_session_factory, broker_channel
):
    """A malformed body is nacked without requeue and dead-letters into the DLQ.

    Publish a malformed (non-JSON) body straight to `EVENT_EXCHANGE` on
    `record.created`, deliver it off `enrichment.stub`, and call `handle_enrichment`
    — the body fails to parse, so the handler nacks without requeue. The message must
    then land in `enrichment.stub.dlq` (Epic 4's dead-letter plumbing), polled for
    because dead-lettering is broker-side async. Mirrors the Epic 6 DLQ proof; the
    body is unique to this run so the DLQ assertion finds *this* test's message.
    """
    await declare_topology(broker_channel)
    poison_body = f"this is not valid json {uuid.uuid4()} {{".encode("utf-8")

    events_exchange = await broker_channel.get_exchange(EVENT_EXCHANGE)
    await events_exchange.publish(
        aio_pika.Message(body=poison_body),
        routing_key=EventType.RECORD_CREATED.value,
    )

    # The poison body carries no `message_id`, so take the next delivery off the queue.
    queue = await broker_channel.get_queue(ENRICHMENT_QUEUE)
    message = None
    for _ in range(50):
        message = await queue.get(no_ack=False, fail=False)
        if message is not None and message.body == poison_body:
            break
        if message is not None:
            # An unrelated leftover delivery — ack it so it does not block the poll.
            await message.ack()
            message = None
    assert message is not None, "the poison message never arrived on enrichment.stub"
    await handle_enrichment(message)

    dead_lettered = await get_dead_lettered_message(
        broker_channel, ENRICHMENT_DEAD_LETTER_QUEUE
    )
    assert dead_lettered is not None
    assert dead_lettered.body == poison_body


# --- Phase 4: per-tenant isolation of outbox + processed_events ---------------


@pytest.mark.asyncio
async def test_outbox_and_processed_events_stay_tenant_isolated(
    seeded,
    db_client,
    container_audit_session_factory,
    database_engine,
    container_relay_session_factory,
    container_consumers_session_factory,
    broker_channel,
):
    """Each tenant's outbox row and processed_events row land in its own schema only.

    The positive routing proof the acceptance suite adds (the DB-role physical-denial
    proof is already owned by `test_outbox_enqueue.py` / `test_isolation_acceptance.py`).
    Create a record as a Sunshine Agent AND a Florida Agent (log in per-tenant by
    email). `publish_pending_once` publishes both tenants' rows in one sweep; drain
    and handle **every** delivered message on both queues (the handlers self-route by
    `tenant_id`). Then assert each tenant's `record.created` outbox row exists only in
    its own schema, and each tenant's `processed_events` holds ONLY its own event:
    Sunshine's `event_id` is present in `sunshine.processed_events` for both consumers
    and ABSENT from `florida.processed_events`, and vice versa.
    """
    await declare_topology(broker_channel)
    await purge_consumer_queues(broker_channel)

    # Create one record in each tenant, capturing each event's id from its outbox row.
    event_id_by_tenant: dict[str, uuid.UUID] = {}
    for tenant in (SUNSHINE, FLORIDA):
        login_response = await login_as_tenant_agent(db_client, tenant)
        assert login_response.status_code == 200
        create_response = await db_client.post("/api/pii-demo/", json=FULL_RECORD_BODY)
        assert create_response.status_code == 201
        created_id = uuid.UUID(create_response.json()["record"]["id"])
        enqueued = await read_record_created_outbox_row(
            database_engine, tenant.schema_name, created_id
        )
        event_id_by_tenant[tenant.schema_name] = enqueued.event_id
        await db_client.post("/api/auth/logout")

    # One sweep publishes BOTH tenants' rows; drain and handle every delivery on both
    # queues — the handlers self-route by the envelope's tenant_id.
    await publish_pending_once(broker_channel)
    for queue_name, handler in CONSUMER_HANDLERS:
        queue = await broker_channel.get_queue(queue_name)
        while True:
            message = await queue.get(no_ack=False, fail=False)
            if message is None:
                break
            await handler(message)

    sunshine_event_id = event_id_by_tenant[SUNSHINE.schema_name]
    florida_event_id = event_id_by_tenant[FLORIDA.schema_name]

    # Each tenant's record.created outbox row exists in its own schema and not the other's.
    assert (
        await read_published_at(database_engine, SUNSHINE.schema_name, sunshine_event_id)
        is not None
    )
    assert (
        await read_published_at(database_engine, FLORIDA.schema_name, florida_event_id)
        is not None
    )
    assert (
        await read_published_at(database_engine, FLORIDA.schema_name, sunshine_event_id)
        is None
    ), "Sunshine's event leaked into the Florida outbox"
    assert (
        await read_published_at(database_engine, SUNSHINE.schema_name, florida_event_id)
        is None
    ), "Florida's event leaked into the Sunshine outbox"

    # Each tenant's processed_events holds ONLY its own event, for BOTH consumers.
    for consumer_name in (ENRICHMENT_STUB, SYNC_LOGGER):
        # Sunshine's event: present in sunshine, absent from florida.
        assert (
            await count_processed_events(
                database_engine, SUNSHINE.schema_name, consumer_name, sunshine_event_id
            )
            == 1
        )
        assert (
            await count_processed_events(
                database_engine, FLORIDA.schema_name, consumer_name, sunshine_event_id
            )
            == 0
        ), f"Sunshine's event leaked into florida.processed_events for {consumer_name}"

        # Florida's event: present in florida, absent from sunshine.
        assert (
            await count_processed_events(
                database_engine, FLORIDA.schema_name, consumer_name, florida_event_id
            )
            == 1
        )
        assert (
            await count_processed_events(
                database_engine, SUNSHINE.schema_name, consumer_name, florida_event_id
            )
            == 0
        ), f"Florida's event leaked into sunshine.processed_events for {consumer_name}"
