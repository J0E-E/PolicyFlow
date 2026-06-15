"""The broker side of the publish path — RabbitMQ topology + one-envelope publish.

Phase P1.5's storage side writes events to the per-tenant outbox; this module is
the broker side that moves one envelope onto RabbitMQ. It holds two things: the
**topology** (the durable topic exchange, the per-consumer durable queues, and the
per-queue dead-letter plumbing the relay and consumers need) expressed as pure
data, and the two functions that **declare** that topology on a channel and
**publish** a single envelope onto the exchange with the AMQP message properties
the contract specifies.

The topology is **derived from `app.events.catalog.CONSUMER_BINDINGS`** rather than
re-listed here, so the queue names and routing keys can never drift from the
catalog — the same single-source-of-truth move the catalog itself makes against the
TDD. The exchange names are transcribed verbatim from TDD §5.4.

**Connection/channel lifecycle (settled this epic):** one shared connection, one
channel per task (each of the relay and each consumer gets its own channel; Epics
5–7 honor this). This module stays lifecycle-agnostic — both functions take a
`channel` argument and open no connections of their own, so the lifecycle lives in
the runtime wiring (Epic 7), not here.

Every published message is tenant-stamped (`tenant_id` rides both as an AMQP header
and inside the flat JSON body) so Epic 6's consumers route by tenant. The broker is
tenant-agnostic transport, but the payload is **non-PII by contract** (frozen in
Epic 1's envelope) — the broker path never sees a PII snapshot or a revealed value.
"""

from dataclasses import dataclass

import aio_pika

from app.events.catalog import CONSUMER_BINDINGS
from app.events.envelope import EventEnvelope, to_message_body

__all__ = [
    "EVENT_EXCHANGE",
    "DEAD_LETTER_EXCHANGE",
    "QueueTopology",
    "TOPOLOGY",
    "declare_topology",
    "publish_envelope",
]


# Exchange names, transcribed verbatim from TDD §5.4. The events exchange is the
# durable topic exchange every envelope is published to; the dead-letter exchange
# is the durable topic exchange a rejected message is routed to so it lands in the
# matching DLQ.
EVENT_EXCHANGE = "policyflow.events"
DEAD_LETTER_EXCHANGE = "policyflow.events.dlx"


@dataclass(frozen=True)
class QueueTopology:
    """One consumer queue's place in the topology — its name, keys, and DLQ.

    Frozen pure data: `queue` is the durable main queue a consumer reads,
    `routing_keys` are the topic-exchange patterns it binds on, and
    `dead_letter_queue` is the durable DLQ a rejected message dead-letters to.
    `declare_topology` reads these to declare and bind the broker objects.
    """

    queue: str
    routing_keys: tuple[str, ...]
    dead_letter_queue: str


# The full queue topology as pure data, **derived** from the catalog's
# `CONSUMER_BINDINGS` so names and keys can never drift from the registry: each
# consumer binding becomes one main queue (`binding.name`) on its routing keys plus
# a matching `<name>.dlq`. Yields exactly `enrichment.stub` ← `record.created` (DLQ
# `enrichment.stub.dlq`) and `sync.logger` ← `#` (DLQ `sync.logger.dlq`).
TOPOLOGY: tuple[QueueTopology, ...] = tuple(
    QueueTopology(
        queue=binding.name,
        routing_keys=binding.routing_keys,
        dead_letter_queue=f"{binding.name}.dlq",
    )
    for binding in CONSUMER_BINDINGS
)


async def declare_topology(channel) -> None:
    """Declare the whole topology on `channel` — exchange, DLX, queues, bindings.

    Declares the durable topic events exchange and the durable topic dead-letter
    exchange, then for every `QueueTopology` in `TOPOLOGY`: declares the durable
    DLQ; declares the durable main queue dead-lettering to `DEAD_LETTER_EXCHANGE`;
    binds the main queue to the events exchange and the DLQ to the dead-letter
    exchange on each of the queue's routing keys. Every declare and bind is
    idempotent, so this is safe to call on every startup.
    """
    event_exchange = await channel.declare_exchange(
        EVENT_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
    )
    dead_letter_exchange = await channel.declare_exchange(
        DEAD_LETTER_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
    )

    for queue_topology in TOPOLOGY:
        dead_letter_queue = await channel.declare_queue(
            queue_topology.dead_letter_queue, durable=True
        )
        main_queue = await channel.declare_queue(
            queue_topology.queue,
            durable=True,
            arguments={"x-dead-letter-exchange": DEAD_LETTER_EXCHANGE},
        )
        for routing_key in queue_topology.routing_keys:
            await main_queue.bind(event_exchange, routing_key=routing_key)
            await dead_letter_queue.bind(dead_letter_exchange, routing_key=routing_key)


async def publish_envelope(channel, envelope: EventEnvelope) -> None:
    """Publish one envelope onto the events exchange with the contract properties.

    Looks the events exchange up on `channel`, builds the AMQP message from the
    envelope's flat JSON body (`to_message_body`) with the contract's properties —
    persistent delivery, `message_id` = the event id, `correlation_id` = the flow's
    correlation id, a `tenant_id` header, and `application/json` content type — and
    publishes it under the envelope's event type as the routing key. The channel
    uses publisher confirms by default, so the await resolves only once the broker
    has routed the message.
    """
    event_exchange = await channel.get_exchange(EVENT_EXCHANGE)
    message = aio_pika.Message(
        body=to_message_body(envelope),
        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        message_id=str(envelope.event_id),
        correlation_id=str(envelope.correlation_id),
        headers={"tenant_id": str(envelope.tenant_id)},
        content_type="application/json",
    )
    await event_exchange.publish(message, routing_key=envelope.event_type)
