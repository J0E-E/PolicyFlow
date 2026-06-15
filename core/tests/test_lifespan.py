"""Tests for the runtime wiring (Epic 7) — the event-bus FastAPI lifespan.

Two phases, mirroring the runtime module:

- **Phase 1 (DB + broker substrate).** On the real Postgres + RabbitMQ
  testcontainers (`database_engine` + `rabbitmq_container`): that entering and
  exiting `event_bus_lifespan` wires the whole bus without error — startup connects
  the broker, declares the topology, starts the relay task, and registers one
  consumer per stub; shutdown cancels the relay and closes the connection cleanly.
  This is the "wire without error" smoke test the epic asks for.
- **Phase 2 (pure unit, no broker).** That `connect_to_broker_with_retry` retries a
  flaky connect (fails K times, then succeeds → returns the connection) and re-raises
  after the final attempt when the connect always fails — the bounded-retry contract
  that lets a Compose boot-order race self-heal but a genuinely-down broker fail boot
  loudly. `asyncio.sleep` is patched so the test never actually waits.

The relay and the consumers each open their **own** session through the
module-global `relay.session_factory` / `consumers.session_factory`, so the Phase 1
smoke test points those globals at the container database with the
`container_relay_session_factory` / `container_consumers_session_factory` monkeypatch
idiom from `test_relay.py` / `test_consumers.py`, and points `settings.rabbitmq_url`
at the broker container so the lifespan connects to it.

Requires the Docker daemon for Phase 1 (no skip logic — the substrate's deliberate
"fail always when Docker is absent" choice). `pytest.ini` sets `asyncio_mode =
auto`; the DB/broker test carries an explicit `@pytest.mark.asyncio` to match the
other substrate modules.
"""

import asyncio

import aio_pika
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.events import consumers as consumers_module
from app.events import relay as relay_module
from app.events import runtime as runtime_module
from app.events.runtime import (
    BROKER_CONNECT_MAX_ATTEMPTS,
    connect_to_broker_with_retry,
    event_bus_lifespan,
)
from tests.conftest import build_amqp_url


# --- Phase 1 substrate: fixtures ---------------------------------------------


@pytest.fixture
def container_relay_session_factory(database_engine, monkeypatch):
    """Point `app.events.relay.session_factory` at the migrated container database.

    The relay opens its **own** session through the module-global
    `app.events.relay.session_factory`; the lifespan starts the relay task, so that
    global must point at the container database or the relay's first sweep would hit
    the unreachable eager default engine. A mirror of the same-named fixture in
    `test_relay.py`. `monkeypatch` restores the real factory after each test.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    monkeypatch.setattr(relay_module, "session_factory", session_factory)
    return session_factory


@pytest.fixture
def container_consumers_session_factory(database_engine, monkeypatch):
    """Point `app.events.consumers.session_factory` at the migrated container database.

    Each consumer opens its **own** session through the module-global
    `app.events.consumers.session_factory`; the lifespan registers the consumers, so
    that global must point at the container database. A mirror of the same-named
    fixture in `test_consumers.py`. `monkeypatch` restores the real factory after
    each test.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    monkeypatch.setattr(consumers_module, "session_factory", session_factory)
    return session_factory


# --- Phase 1: the lifespan wires without error -------------------------------


@pytest.mark.asyncio
async def test_event_bus_lifespan_starts_and_stops_cleanly(
    database_engine,
    container_relay_session_factory,
    container_consumers_session_factory,
    rabbitmq_container,
    monkeypatch,
):
    """Entering and exiting the lifespan wires the whole bus without error.

    Point `settings.rabbitmq_url` at the broker container so the lifespan connects to
    it, then enter and exit `event_bus_lifespan` as an async context manager. Startup
    must connect, declare the topology, start the relay task, and register one
    consumer per stub; shutdown must cancel the relay and close the connection — all
    without raising. Inside the lifespan, yield the event loop a few times so the
    relay runs at least one sweep over the empty outbox (0 published), proving the
    started task is live and healthy.
    """
    monkeypatch.setattr(
        settings, "rabbitmq_url", build_amqp_url(rabbitmq_container)
    )

    async with event_bus_lifespan(app=None):
        # Let the started relay task run a few sweeps over the (empty) outbox so we
        # exercise the live task, not just its creation.
        for _ in range(5):
            await asyncio.sleep(0)

    # Reaching here means both startup and shutdown completed without raising.


# --- Phase 2: bounded connect retry (pure unit, no broker) -------------------


# --- Phase 1b: a partway startup failure tears the bus down (pure unit) ------


class _FakeQueue:
    """A stand-in queue whose `consume` records the registered handler."""

    def __init__(self):
        self.consumed_handler = None

    async def consume(self, handler):
        self.consumed_handler = handler


class _FakeChannel:
    """A stand-in channel whose `get_queue` can be told to raise.

    The relay channel (declared on first) succeeds; a consumer channel can be made to
    raise from `get_queue` to simulate a consumer registration failing partway through
    startup.
    """

    def __init__(self, get_queue_error=None):
        self.get_queue_error = get_queue_error

    async def get_queue(self, _queue_name):
        if self.get_queue_error is not None:
            raise self.get_queue_error
        return _FakeQueue()


class _FakeConnection:
    """A stand-in broker connection that hands out a scripted list of channels.

    Records whether it was closed so a test can assert a partway startup failure still
    closed the connection. The first `channel()` call is the relay channel; each later
    call is a consumer channel.
    """

    def __init__(self, channels):
        self._channels = list(channels)
        self.is_closed = False

    async def channel(self):
        # Yield to the event loop like a real async channel open does, so a relay task
        # created just before the consumer loop gets a turn to actually start running
        # (and so its cancellation later lands inside its loop body, as in production).
        await asyncio.sleep(0)
        return self._channels.pop(0)

    async def close(self):
        self.is_closed = True


@pytest.mark.asyncio
async def test_event_bus_lifespan_startup_failure_tears_down_relay_and_connection(
    monkeypatch,
):
    """A consumer registration that raises tears down the relay task and connection.

    Drives `event_bus_lifespan` with fakes (no real broker): the connect returns a
    fake connection, `declare_topology` is a no-op, the relay loop is a real awaitable
    task we can inspect, and the **first consumer's** channel raises from `get_queue`
    so startup fails partway — after the relay task was created but before all
    consumers were registered. The lifespan must re-raise the failure **and**, on the
    way out, cancel the started relay task and close the connection, leaving no leaked
    task or open connection (the "no resource leak if startup fails partway" goal).
    """
    registration_error = RuntimeError("consumer registration blew up")

    relay_channel = _FakeChannel()
    failing_consumer_channel = _FakeChannel(get_queue_error=registration_error)
    fake_connection = _FakeConnection([relay_channel, failing_consumer_channel])

    async def fake_connect(_url):
        return fake_connection

    async def fake_declare_topology(_channel):
        return None

    # A relay loop that runs until cancelled, so the test can assert the lifespan
    # actually started it and then cancelled it during teardown rather than leaving it
    # running.
    relay_was_started = False
    relay_was_cancelled = False

    async def fake_run_relay_loop(_channel):
        nonlocal relay_was_started, relay_was_cancelled
        relay_was_started = True
        try:
            while True:
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            relay_was_cancelled = True
            raise

    monkeypatch.setattr(runtime_module, "connect_to_broker_with_retry", fake_connect)
    monkeypatch.setattr(runtime_module, "declare_topology", fake_declare_topology)
    monkeypatch.setattr(runtime_module, "run_relay_loop", fake_run_relay_loop)
    # At least one consumer so the failing consumer channel is reached.
    monkeypatch.setattr(
        runtime_module, "CONSUMER_HANDLERS", (("enrichment.stub", object()),)
    )

    with pytest.raises(RuntimeError, match="consumer registration blew up"):
        async with event_bus_lifespan(app=None):
            pass  # pragma: no cover — startup raises before the body runs.

    assert relay_was_started, "the relay task must have actually started before teardown"
    assert relay_was_cancelled, "the started relay task must be cancelled on teardown"
    assert fake_connection.is_closed, "the opened connection must be closed on teardown"


@pytest.mark.asyncio
async def test_connect_to_broker_with_retry_succeeds_after_transient_failures(
    monkeypatch,
):
    """A connect that fails K times then succeeds is retried until it returns.

    Replace the underlying connect with a stub that raises `AMQPConnectionError` the
    first few attempts and then returns a sentinel connection. The helper must keep
    retrying and ultimately return that sentinel, and it must have slept between the
    failed attempts (`asyncio.sleep` is patched to count calls without waiting).
    """
    failures_before_success = 3
    attempt_count = 0
    sentinel_connection = object()

    async def flaky_connect(_url):
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count <= failures_before_success:
            raise aio_pika.exceptions.AMQPConnectionError("broker not ready yet")
        return sentinel_connection

    sleep_call_count = 0

    async def fake_sleep(_seconds):
        nonlocal sleep_call_count
        sleep_call_count += 1

    monkeypatch.setattr(runtime_module.aio_pika, "connect_robust", flaky_connect)
    monkeypatch.setattr(runtime_module.asyncio, "sleep", fake_sleep)

    connection = await connect_to_broker_with_retry("amqp://unused/")

    assert connection is sentinel_connection
    assert attempt_count == failures_before_success + 1
    # One sleep before each retry — exactly one per failed attempt.
    assert sleep_call_count == failures_before_success


@pytest.mark.asyncio
async def test_connect_to_broker_with_retry_reraises_after_final_attempt(monkeypatch):
    """A connect that always fails re-raises after the bounded attempt budget.

    Replace the underlying connect with a stub that always raises
    `AMQPConnectionError`. The helper must try exactly `BROKER_CONNECT_MAX_ATTEMPTS`
    times and then re-raise the last error (fail boot loudly), having slept once
    fewer than the attempt count (no sleep after the final, fatal attempt).
    """
    attempt_count = 0

    async def always_failing_connect(_url):
        nonlocal attempt_count
        attempt_count += 1
        raise aio_pika.exceptions.AMQPConnectionError("broker is down")

    sleep_call_count = 0

    async def fake_sleep(_seconds):
        nonlocal sleep_call_count
        sleep_call_count += 1

    monkeypatch.setattr(
        runtime_module.aio_pika, "connect_robust", always_failing_connect
    )
    monkeypatch.setattr(runtime_module.asyncio, "sleep", fake_sleep)

    with pytest.raises(aio_pika.exceptions.AMQPConnectionError):
        await connect_to_broker_with_retry("amqp://unused/")

    assert attempt_count == BROKER_CONNECT_MAX_ATTEMPTS
    # Slept before every retry but not after the final, fatal attempt.
    assert sleep_call_count == BROKER_CONNECT_MAX_ATTEMPTS - 1
