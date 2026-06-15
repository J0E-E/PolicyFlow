"""The runtime wiring — the FastAPI lifespan that actually *runs* the event bus.

Phase P1.5 built the event bus as disconnected halves: the transactional outbox
(Epic 3), the broker topology + publish (Epic 4), the polling relay (Epic 5), and
the two idempotent stub consumers (Epic 6). Each half was written anticipating this
module — nothing yet **started** the relay sweeping or **registered** a consumer to
read off a queue. This module is that missing wiring.

A FastAPI **lifespan** is code that runs once when the app boots and once when it
shuts down. On startup this lifespan opens one shared broker connection, declares
the topology, starts the relay as a background task, and registers one consumer per
stub; on shutdown it cancels the relay and closes the connection (which tears down
every channel and consumer). `main.py` only imports `event_bus_lifespan` and passes
it to `FastAPI(lifespan=...)`, so `main.py` stays a pure wiring file and this
orchestration is independently testable — the focused-module style of `relay.py`,
`consumers.py`, and `audit/service.py`.

**Production path only.** The test client's `ASGITransport` does *not* fire lifespan
events, so the existing relay/consumer tests keep driving those pieces explicitly.
This lifespan is the wiring a real `uvicorn` boot runs; the smoke test enters and
exits it directly against the testcontainers to prove it wires without error.

**Connection/channel lifecycle (Epic 4's frozen contract).** One shared connection,
one channel per task: the topology is declared on the relay's channel before the
relay task starts (so the first sweep's `publish_envelope` can look the exchange up
rather than declare it), and each consumer gets its **own** channel. We use
`aio_pika.connect_robust` (auto-reconnecting) because this connection is long-lived
— a transient broker blip restores its channels and consumers automatically. The
health probe's one-shot `connect` is a different job.

**Tenant-isolation note (the project's cross-cutting axis).** The lifespan adds no
new tenant-data path — it only starts the existing relay and consumers, which
already enforce isolation (the relay sweeps per-tenant as `outbox_relay`; the
consumers route by `tenant_id` and write as `event_consumer`, whitelist-validated).
No PII touches the lifespan.
"""

import asyncio
import contextlib
import logging

import aio_pika

from app.config import settings
from app.events.broker import declare_topology
from app.events.consumers import CONSUMER_HANDLERS
from app.events.relay import run_relay_loop

__all__ = [
    "BROKER_CONNECT_MAX_ATTEMPTS",
    "BROKER_CONNECT_BASE_DELAY_SECONDS",
    "BROKER_CONNECT_MAX_DELAY_SECONDS",
    "connect_to_broker_with_retry",
    "event_bus_lifespan",
]

logger = logging.getLogger(__name__)


# Bounded-retry parameters for the **initial** broker connect (confirmed with the
# stakeholder at plan time): a capped exponential backoff. The delay before the
# n-th retry is `min(BASE * 2**(attempt-1), MAX)` seconds — 1, 2, 4, 8, 8, 8, 8 —
# for a ~45s total budget across the 8 attempts. This self-heals a normal Compose
# boot-order race (core boots before RabbitMQ is ready) without an unbounded wait,
# and fails boot **loudly** if the broker is genuinely down past the budget.
BROKER_CONNECT_MAX_ATTEMPTS = 8
BROKER_CONNECT_BASE_DELAY_SECONDS = 1.0
BROKER_CONNECT_MAX_DELAY_SECONDS = 8.0


async def connect_to_broker_with_retry(rabbitmq_url: str):
    """Connect to the broker, retrying a capped-exponential number of times.

    Wraps the **initial** `aio_pika.connect_robust` so a boot-order race — core up
    before RabbitMQ is accepting connections — does not crash core. On each attempt
    it tries to connect; on a connection-time error it logs a warning, sleeps
    `min(BASE * 2**(attempt-1), MAX)` seconds, and retries, up to
    `BROKER_CONNECT_MAX_ATTEMPTS` attempts. After the final attempt fails it
    **re-raises** the last error, so a genuinely-down broker fails the boot loudly
    rather than hanging forever. Returns the live connection on the first success.

    The caught error type is `(AMQPConnectionError, OSError)`. `AMQPConnectionError`
    covers an AMQP-level refusal; `OSError` is the broad socket-level base that covers
    a not-yet-resolvable Compose hostname (`socket.gaierror`), a connection refused,
    and a bare connect `TimeoutError` — every form a not-yet-ready broker takes at
    boot. (`ConnectionError` alone would miss `gaierror`/`TimeoutError`, which are
    `OSError` but not `ConnectionError`, so they could escape the retry.)

    Only the connect is retried here; once connected, `connect_robust` itself
    auto-recovers later transient blips, so the retry is exactly the one gap it does
    not cover (it cannot recover a connection that was never established).
    """
    last_error: Exception | None = None
    for attempt in range(1, BROKER_CONNECT_MAX_ATTEMPTS + 1):
        try:
            return await aio_pika.connect_robust(rabbitmq_url)
        except (aio_pika.exceptions.AMQPConnectionError, OSError) as error:
            last_error = error
            is_final_attempt = attempt == BROKER_CONNECT_MAX_ATTEMPTS
            if is_final_attempt:
                break
            delay_seconds = min(
                BROKER_CONNECT_BASE_DELAY_SECONDS * 2 ** (attempt - 1),
                BROKER_CONNECT_MAX_DELAY_SECONDS,
            )
            logger.warning(
                "broker connect attempt %d/%d failed (%s); retrying in %.1fs",
                attempt,
                BROKER_CONNECT_MAX_ATTEMPTS,
                error,
                delay_seconds,
            )
            await asyncio.sleep(delay_seconds)

    logger.error(
        "broker connect failed after %d attempts; giving up",
        BROKER_CONNECT_MAX_ATTEMPTS,
    )
    # The loop only reaches here after at least one caught failure, so `last_error` is
    # always set; assert it to satisfy a strict type checker (declared `… | None`).
    assert last_error is not None
    raise last_error


@contextlib.asynccontextmanager
async def event_bus_lifespan(app):
    """Start the relay + consumers on app startup, stop them cleanly on shutdown.

    The FastAPI lifespan that wires the whole event bus. The `app` argument is the
    FastAPI application FastAPI passes in; this lifespan does not read it (the bus
    is global, not per-app), but the lifespan protocol requires the parameter.

    **Startup** (everything before the ``yield``):

    1. Open one shared connection to the broker via `connect_to_broker_with_retry`
       (a bounded retry so a Compose boot-order race can't crash core).
    2. On the relay's channel, `declare_topology` — so the durable exchange, queues,
       and dead-letter plumbing exist before anything publishes or consumes.
    3. Start the relay as a real `asyncio.Task` (it is a polling loop), keeping the
       task reference so shutdown can cancel it.
    4. For each ``(queue_name, handler)`` in `CONSUMER_HANDLERS`, open the consumer's
       **own** channel, get its queue **passively** (`get_queue` — the durable queue
       was already declared by `declare_topology` with its dead-letter arguments, so
       we must **not** re-declare it with mismatched arguments), and register the
       handler with `queue.consume`. Keep each channel reference alive for the app's
       lifetime so the consumer stays registered.

    **Shutdown** (everything after the ``yield``): cancel the relay task and await it,
    swallowing the expected `asyncio.CancelledError`; then close the connection, which
    tears down every channel and so stops all consumers. Closing the connection is the
    idiomatic aio-pika way to stop `queue.consume` consumers — only the relay (a
    hand-rolled loop) needs an explicit cancel.

    **No resource leak if startup fails partway.** The startup steps after the connect
    (declare topology, start the relay task, register the consumers) run inside their
    own `try`; if any of them raises, the `except` tears down whatever was already
    built — it cancels the relay task if it was created and closes the connection if it
    was opened — before re-raising, so a half-finished startup never leaves the relay
    task running or the connection open. The same `_tear_down_bus` teardown runs on
    normal shutdown, so startup-failure cleanup and shutdown cleanup share one path.
    """
    logger.info("event bus lifespan starting: connecting to the broker")
    connection = await connect_to_broker_with_retry(settings.rabbitmq_url)

    # Track what startup has built so a partway failure can tear down exactly what
    # exists: the relay task stays None until it is created, and the connection is
    # already open by this point so it always needs closing on failure.
    relay_task: asyncio.Task | None = None
    try:
        relay_channel = await connection.channel()
        await declare_topology(relay_channel)
        relay_task = asyncio.create_task(run_relay_loop(relay_channel))

        # Hold each consumer's channel for the app's lifetime so its `queue.consume`
        # registration stays active; closing the connection on shutdown stops them all.
        consumer_channels = []
        for queue_name, handler in CONSUMER_HANDLERS:
            consumer_channel = await connection.channel()
            queue = await consumer_channel.get_queue(queue_name)
            await queue.consume(handler)
            consumer_channels.append(consumer_channel)
    except BaseException:
        # Startup failed partway: tear down whatever was already built (the relay
        # task if it was started, the connection that was already opened) and re-raise
        # so the boot fails loudly rather than leaking a running task or open socket.
        logger.exception("event bus lifespan startup failed; tearing down partial state")
        await _tear_down_bus(relay_task, connection)
        raise

    logger.info(
        "event bus lifespan started: relay running, %d consumer(s) registered",
        len(consumer_channels),
    )

    try:
        yield
    finally:
        logger.info("event bus lifespan stopping: cancelling relay and closing connection")
        await _tear_down_bus(relay_task, connection)
        logger.info("event bus lifespan stopped")


async def _tear_down_bus(relay_task, connection):
    """Cancel the relay task (if any) and close the connection (which stops consumers).

    The single teardown path shared by both a partway-startup failure and a normal
    shutdown. It cancels the relay task and awaits it, swallowing the expected
    `asyncio.CancelledError`, then closes the broker connection — which tears down
    every channel and so stops all `queue.consume` consumers (the idiomatic aio-pika
    way to stop them; only the hand-rolled relay loop needs an explicit cancel).

    `relay_task` is ``None`` when startup failed before the relay task was created, so
    the cancel is skipped in that case; the connection is always already open by the
    time any teardown runs, so it is always closed.
    """
    if relay_task is not None:
        relay_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await relay_task
    await connection.close()
