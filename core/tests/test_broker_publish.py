"""Live-broker test for declare + publish over a real RabbitMQ testcontainer.

Boots a throwaway RabbitMQ in Docker (the `rabbitmq_container` substrate fixture)
and exercises the real declare → publish → land path: that a published envelope
lands in every queue its routing key binds (fan-out), that it carries the AMQP
properties the contract specifies and round-trips back to an equal envelope, and
that a second event type routes by topic to only its bound queue.

Requires the Docker daemon — there is no skip logic (the substrate's deliberate
"fail always when Docker is absent" choice). The publish channel uses publisher
confirms by default, so each `publish_envelope` await resolves only once the broker
has routed the message; the assertions need no sleeps.
"""

import uuid

import aio_pika
import pytest
import pytest_asyncio

from app.events.broker import declare_topology, publish_envelope
from app.events.catalog import EventType
from app.events.envelope import build_envelope, from_message_body
from tests.conftest import build_amqp_url

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def broker_channel(rabbitmq_container):
    """Yield one aio-pika channel against the RabbitMQ container, closed after.

    Opens a single robust connection and one channel — the "one shared connection,
    one channel per task" lifecycle this epic settled — and tears both down when the
    test finishes so no connection leaks across tests.
    """
    connection = await aio_pika.connect_robust(build_amqp_url(rabbitmq_container))
    channel = await connection.channel()
    try:
        yield channel
    finally:
        await channel.close()
        await connection.close()


def make_record_created_envelope():
    """Build a fresh `record.created` envelope with a known tenant and payload."""
    return build_envelope(
        event_type=EventType.RECORD_CREATED.value,
        tenant_id=uuid.uuid4(),
        actor_user_id=uuid.uuid4(),
        actor_role="agent",
        payload={"record_id": str(uuid.uuid4())},
    )


async def test_published_record_created_lands_in_both_bound_queues(broker_channel):
    """A `record.created` envelope fans out to both bound queues with its properties.

    `record.created` matches the enrichment stub's literal binding and the sync
    logger's `#` binding, so it must land in both. The retrieved message must carry
    the contract's AMQP properties and round-trip back to an equal envelope.
    """
    await declare_topology(broker_channel)
    envelope = make_record_created_envelope()

    await publish_envelope(broker_channel, envelope)

    enrichment_queue = await broker_channel.get_queue("enrichment.stub")
    sync_logger_queue = await broker_channel.get_queue("sync.logger")
    enrichment_message = await enrichment_queue.get(no_ack=True)
    sync_logger_message = await sync_logger_queue.get(no_ack=True)

    for message in (enrichment_message, sync_logger_message):
        assert message.message_id == str(envelope.event_id)
        assert message.correlation_id == str(envelope.correlation_id)
        assert message.headers["tenant_id"] == str(envelope.tenant_id)
        assert message.delivery_mode == aio_pika.DeliveryMode.PERSISTENT.value
        assert from_message_body(message.body) == envelope


async def test_published_pii_revealed_reaches_only_the_wildcard_queue(broker_channel):
    """A `pii.revealed` envelope reaches only `sync.logger` (proves topic routing).

    `pii.revealed` matches only the sync logger's `#` binding, not the enrichment
    stub's literal `record.created` binding, so it must land in `sync.logger` alone —
    nothing dropped, nothing mis-routed.
    """
    await declare_topology(broker_channel)
    envelope = build_envelope(
        event_type=EventType.PII_REVEALED.value,
        tenant_id=uuid.uuid4(),
        actor_user_id=uuid.uuid4(),
        actor_role="agent",
        payload={"field_name": "ssn"},
    )

    await publish_envelope(broker_channel, envelope)

    sync_logger_queue = await broker_channel.get_queue("sync.logger")
    sync_logger_message = await sync_logger_queue.get(no_ack=True)
    assert from_message_body(sync_logger_message.body) == envelope

    enrichment_queue = await broker_channel.get_queue("enrichment.stub")
    assert await enrichment_queue.get(no_ack=True, fail=False) is None
