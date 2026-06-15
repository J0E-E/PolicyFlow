"""Pure unit test for the broker topology as data.

Pure logic, no DB / no Docker / no async (sync functions, matching the suite's
style for non-async tests; see `test_event_catalog.py`).

The expected values below are written **independently** from the production
`broker.py` symbols — they hand-transcribe the same normative TDD §5.4 topology
(exchange names, the per-consumer queue/routing-key/DLQ shape). That makes every
assertion a genuine cross-check against the spec rather than a tautology over the
module under test.
"""

from app.events.broker import (
    DEAD_LETTER_EXCHANGE,
    EVENT_EXCHANGE,
    TOPOLOGY,
)

# Independent transcription of the TDD §5.4 exchange names, hand-built here on
# purpose, separate from the constants in `broker.py`.
EXPECTED_EVENT_EXCHANGE = "policyflow.events"
EXPECTED_DEAD_LETTER_EXCHANGE = "policyflow.events.dlx"

# Independent transcription of the TDD §5.4 queue topology, queue name ->
# (expected routing keys, expected dead-letter queue). Hand-built here on purpose.
EXPECTED_TOPOLOGY: dict[str, tuple[tuple[str, ...], str]] = {
    "enrichment.stub": (("record.created",), "enrichment.stub.dlq"),
    "sync.logger": (("#",), "sync.logger.dlq"),
}


def test_exchange_names_match_the_expected_values():
    """The exchange-name constants match the hand-written TDD §5.4 expectation."""
    assert EVENT_EXCHANGE == EXPECTED_EVENT_EXCHANGE
    assert DEAD_LETTER_EXCHANGE == EXPECTED_DEAD_LETTER_EXCHANGE


def test_each_queue_has_its_expected_routing_keys_and_dead_letter_queue():
    """Each queue in the topology binds its expected keys and DLQ."""
    topology_by_queue = {
        queue_topology.queue: (
            queue_topology.routing_keys,
            queue_topology.dead_letter_queue,
        )
        for queue_topology in TOPOLOGY
    }
    for queue_name, expected_routing_keys_and_dlq in EXPECTED_TOPOLOGY.items():
        assert topology_by_queue[queue_name] == expected_routing_keys_and_dlq, queue_name


def test_topology_queues_are_exactly_the_expected_set():
    """The topology lists every expected queue and no extra or missing ones."""
    queue_names = {queue_topology.queue for queue_topology in TOPOLOGY}
    assert queue_names == set(EXPECTED_TOPOLOGY)
