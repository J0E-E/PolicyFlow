"""Tests for the polling relay (Epic 5) — the outbox → broker carrier.

Two phases, mirroring the relay module:

- **Phase 1 (DB + broker substrate).** On the real Postgres + RabbitMQ
  testcontainers (`database_engine` + `rabbitmq_container`): that an enqueued
  `record.created` event is published by one sweep and its row marked
  `published_at`; that a second sweep right after publishes nothing (only
  unpublished rows are selected); and that a row whose `published_at` is forced
  back to NULL re-publishes on the next sweep (at-least-once — the relay keys
  purely on `published_at IS NULL`).
- **Phase 2 (pure unit, no DB/broker).** That `run_relay_loop` sweeps at least
  once, swallows a sweep that raises (surviving to the next iteration), and stops
  cleanly on cancellation.

The relay opens its **own** session through the module-global
`app.events.relay.session_factory` as the `outbox_relay` role, so Phase 1 points
that global at the container database with a per-file monkeypatch fixture,
mirroring `container_audit_session_factory` in `conftest.py`. Enqueue uses the real
INSERT-only tenant role; the relay reads/marks under the SELECT+UPDATE
`outbox_relay` role; every assertion read-back uses the SELECT-capable superuser
engine connection, schema-qualified.

Requires the Docker daemon for Phase 1 (no skip logic — the substrate's deliberate
"fail always when Docker is absent" choice). `pytest.ini` sets `asyncio_mode =
auto`; the DB/broker tests carry an explicit `@pytest.mark.asyncio` to match the
other substrate modules.
"""

import asyncio
import uuid

import aio_pika
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.events import relay as relay_module
from app.events.broker import declare_topology
from app.events.catalog import EventType
from app.events.envelope import EventEnvelope, build_envelope, from_message_body
from app.events.outbox import enqueue_event
from app.events.relay import publish_pending_once, run_relay_loop
from app.tenancy.registry import SUNSHINE, TenantConfig
from tests.conftest import build_amqp_url

# The tenant used throughout Phase 1. Pulled from the registry so schema name and
# DB role stay the single source of truth.
TENANT = SUNSHINE


# --- Phase 1 substrate: fixtures + helpers -----------------------------------


@pytest.fixture
def container_relay_session_factory(database_engine, monkeypatch):
    """Point `app.events.relay.session_factory` at the migrated container database.

    The relay opens its **own** session through the module-global
    `app.events.relay.session_factory` — separate from any request's `get_db`, the
    same own-session shape as `app.audit.service`. The DB substrate must point that
    global at the container database, otherwise the relay's sweep would hit the
    unreachable eager default engine. `monkeypatch` restores the real factory after
    each test. A mirror of `container_audit_session_factory` in `conftest.py`.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    monkeypatch.setattr(relay_module, "session_factory", session_factory)
    return session_factory


@pytest_asyncio.fixture
async def broker_channel(rabbitmq_container):
    """Yield one aio-pika channel against the RabbitMQ container, closed after.

    Opens a single robust connection and one channel — the "one shared connection,
    one channel per task" lifecycle — and tears both down when the test finishes so
    no connection leaks across tests. Mirrors the `broker_channel` fixture in
    `test_broker_publish.py`.
    """
    connection = await aio_pika.connect_robust(build_amqp_url(rabbitmq_container))
    channel = await connection.channel()
    try:
        yield channel
    finally:
        await channel.close()
        await connection.close()


def build_relay_envelope() -> EventEnvelope:
    """Build a fresh, recognisable non-PII `record.created` envelope to relay.

    `build_envelope` mints the identity/timestamp fields; the actor and payload are
    fixed test values. Minimal but complete enough to round-trip field-for-field.
    """
    return build_envelope(
        event_type=EventType.RECORD_CREATED.value,
        tenant_id=uuid.uuid4(),
        actor_user_id=uuid.uuid4(),
        actor_role="tenant_admin",
        payload={"entity_type": "pii_demo", "entity_id": str(uuid.uuid4())},
    )


async def enqueue_under_tenant_role(
    database_engine, tenant: TenantConfig, envelope: EventEnvelope
):
    """Enqueue and commit `envelope` on a session scoped to `tenant`.

    Opens a session, switches into the tenant exactly as `get_tenant_db` does
    (`SET LOCAL ROLE` + `SET LOCAL search_path`), calls the real `enqueue_event`,
    and commits — leaving one unpublished row in the tenant's outbox for the relay
    to find. The same enqueue-under-the-real-tenant-role shape as
    `test_outbox_enqueue.py`.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    async with session_factory() as session:
        await session.begin()
        await session.execute(text(f"SET LOCAL ROLE {tenant.db_role}"))
        await session.execute(text(f"SET LOCAL search_path TO {tenant.schema_name}"))
        await enqueue_event(session, envelope)
        await session.commit()


async def read_published_at(database_engine, schema_name: str, event_id: uuid.UUID):
    """Read back one outbox row's `published_at` by `event_id` from `schema_name`.

    Uses the SELECT-capable superuser engine connection (the relay role and the
    tenant role each lack a free SELECT for tests), schema-qualified — the faithful
    reader substrate from `test_outbox_enqueue.py`. Returns the `published_at`
    value (or `None` if NULL / no row).
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


async def reset_published_at_to_null(
    database_engine, schema_name: str, event_id: uuid.UUID
):
    """Force one outbox row's `published_at` back to NULL via the superuser engine.

    Simulates a crash between publish and mark: the message was sent but the row
    was never stamped. Done through the superuser connection (not the relay role)
    because this is test setup, not relay behavior — the relay only ever sets
    `published_at`, never clears it.
    """
    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                f"UPDATE {schema_name}.outbox SET published_at = NULL "
                "WHERE event_id = :event_id"
            ),
            {"event_id": event_id},
        )


async def drain_queue_message(broker_channel, queue_name: str):
    """Get one message from `queue_name` without ack, or `None` if the queue is empty.

    A thin read-back helper: fetches and removes a single message so a later sweep's
    assertions start from an empty queue. `fail=False` returns `None` rather than
    raising when nothing is waiting.
    """
    queue = await broker_channel.get_queue(queue_name)
    return await queue.get(no_ack=True, fail=False)


# --- Phase 1: the single sweep -----------------------------------------------


@pytest.mark.asyncio
async def test_sweep_publishes_pending_event_and_marks_the_row(
    database_engine, container_relay_session_factory, broker_channel
):
    """One sweep publishes the pending event to both bound queues and marks the row.

    Enqueue a `record.created` envelope into the tenant outbox, declare the topology
    on the broker channel, then run `publish_pending_once`. It must report one
    published event, the message must arrive in **both** bound queues
    (`enrichment.stub` + `sync.logger`, the fan-out) and round-trip back to the same
    envelope, and the outbox row's `published_at` must now be set.
    """
    await declare_topology(broker_channel)
    envelope = build_relay_envelope()
    await enqueue_under_tenant_role(database_engine, TENANT, envelope)

    published_count = await publish_pending_once(broker_channel)

    assert published_count == 1

    enrichment_message = await drain_queue_message(broker_channel, "enrichment.stub")
    sync_logger_message = await drain_queue_message(broker_channel, "sync.logger")
    for message in (enrichment_message, sync_logger_message):
        assert message is not None
        assert from_message_body(message.body) == envelope

    published_at = await read_published_at(
        database_engine, TENANT.schema_name, envelope.event_id
    )
    assert published_at is not None


@pytest.mark.asyncio
async def test_second_sweep_skips_already_published_rows(
    database_engine, container_relay_session_factory, broker_channel
):
    """A second sweep right after the first publishes nothing — published rows skip.

    After one sweep marks the row, a second `publish_pending_once` must report zero
    published events and put no new message on either queue — the relay selects only
    rows whose `published_at IS NULL`.
    """
    await declare_topology(broker_channel)
    envelope = build_relay_envelope()
    await enqueue_under_tenant_role(database_engine, TENANT, envelope)

    await publish_pending_once(broker_channel)
    # Drain the first sweep's fan-out so the queues start empty for the assertion.
    await drain_queue_message(broker_channel, "enrichment.stub")
    await drain_queue_message(broker_channel, "sync.logger")

    second_published_count = await publish_pending_once(broker_channel)

    assert second_published_count == 0
    assert await drain_queue_message(broker_channel, "enrichment.stub") is None
    assert await drain_queue_message(broker_channel, "sync.logger") is None


@pytest.mark.asyncio
async def test_unmarked_row_republishes_for_at_least_once(
    database_engine, container_relay_session_factory, broker_channel
):
    """A row forced back to `published_at = NULL` re-publishes on the next sweep.

    Simulates a crash between publish and mark: after a clean sweep, reset the row's
    `published_at` to NULL and sweep again. The relay must re-publish the event
    (report one, land it on the queues again) — proving it keys purely on
    `published_at IS NULL`, the at-least-once guarantee.
    """
    await declare_topology(broker_channel)
    envelope = build_relay_envelope()
    await enqueue_under_tenant_role(database_engine, TENANT, envelope)

    await publish_pending_once(broker_channel)
    await drain_queue_message(broker_channel, "enrichment.stub")
    await drain_queue_message(broker_channel, "sync.logger")

    await reset_published_at_to_null(database_engine, TENANT.schema_name, envelope.event_id)
    republished_count = await publish_pending_once(broker_channel)

    assert republished_count == 1
    enrichment_message = await drain_queue_message(broker_channel, "enrichment.stub")
    sync_logger_message = await drain_queue_message(broker_channel, "sync.logger")
    for message in (enrichment_message, sync_logger_message):
        assert message is not None
        assert from_message_body(message.body) == envelope


# --- Phase 2: the poll loop (pure unit, no DB/broker) ------------------------


@pytest.mark.asyncio
async def test_run_relay_loop_sweeps_repeatedly_until_cancelled(monkeypatch):
    """The loop sweeps at least once and cancellation stops it cleanly.

    Monkeypatch `publish_pending_once` with a counting stub, run `run_relay_loop` as
    a task with a tiny interval, let it iterate, then cancel it. The stub must have
    been called at least once, and the cancellation must surface as a clean
    `asyncio.CancelledError`.
    """
    sweep_count = 0

    async def counting_sweep(_broker_channel) -> int:
        nonlocal sweep_count
        sweep_count += 1
        return 0

    monkeypatch.setattr(relay_module, "publish_pending_once", counting_sweep)

    task = asyncio.create_task(
        run_relay_loop(broker_channel=None, poll_interval_seconds=0.001)
    )
    # Yield the event loop enough times for several sweep iterations to run.
    for _ in range(20):
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert sweep_count >= 1


@pytest.mark.asyncio
async def test_run_relay_loop_survives_a_sweep_that_raises(monkeypatch):
    """A sweep that raises is swallowed; the loop survives to the next iteration.

    The first sweep raises (a simulated broker hiccup); later sweeps succeed. The
    loop must not die on the raise — it must keep iterating, so the success stub
    runs on a subsequent iteration. Proves the try/except keeps the relay alive
    across a transient failure.
    """
    sweep_count = 0

    async def flaky_sweep(_broker_channel) -> int:
        nonlocal sweep_count
        sweep_count += 1
        if sweep_count == 1:
            raise RuntimeError("simulated broker hiccup")
        return 0

    monkeypatch.setattr(relay_module, "publish_pending_once", flaky_sweep)

    task = asyncio.create_task(
        run_relay_loop(broker_channel=None, poll_interval_seconds=0.001)
    )
    for _ in range(20):
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # More than one sweep ran, so the loop survived the first sweep's raise.
    assert sweep_count >= 2
