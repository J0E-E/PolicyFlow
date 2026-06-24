"""The event vocabulary — the single source of truth for event-bus values.

Phase P1.5 stands up the real event bus. Before any storage, publish, or consumer
epic can be written, the whole phase needs one agreed set of *event types*
(`record.created`, `pii.revealed`), the *schema version*, and the
*consumer→binding registry* (which consumer binds to which routing key) pinned
down in one place. Centralising them means the `0008` migration, the publish side,
the bus topology, and the stub consumers can never disagree on a spelling — the
same single-source-of-truth move already used for the audit `EventType` enum.

This module is **pure data — no database, no I/O**. The enum and registry are
transcribed verbatim from the TDD §5.3 *Interfaces*, so the values are frozen by
the spec, not invented. `tests/test_event_catalog.py` asserts every member and
binding against an independent hand-written expectation so the vocabulary can never
silently drift out from under M3.
"""

from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "EventType",
    "SCHEMA_VERSION",
    "ENRICHMENT_STUB",
    "SYNC_LOGGER",
    "ConsumerBinding",
    "CONSUMER_BINDINGS",
    "consumers_for_event_type",
]


class EventType(StrEnum):
    """One member per kind of event published on the bus.

    Each string value is the dotted name that doubles as the message's routing
    key on the topic exchange. The `record.*` / `pii.*` pair is transcribed
    verbatim from the TDD §5.3 *Interfaces*; the `lead.*` members are the P1.7
    lead-lifecycle events from the TDD §5.4 *Interfaces*.
    """

    RECORD_CREATED = "record.created"
    PII_REVEALED = "pii.revealed"
    LEAD_CREATED = "lead.created"
    LEAD_DUPLICATE_DETECTED = "lead.duplicate_detected"
    LEAD_ASSIGNED = "lead.assigned"
    LEAD_QUALIFIED = "lead.qualified"
    LEAD_REJECTED = "lead.rejected"


# The contract's schema version, stamped onto every envelope (TDD §5.3,
# Decision 11). Bumped only when the envelope shape changes incompatibly.
SCHEMA_VERSION = 1


# Consumer names — the durable identity each stub consumer dedupes and binds
# under (TDD §5.3). Exposed as constants so callers reference a name, not a
# bare string literal.
ENRICHMENT_STUB = "enrichment.stub"
SYNC_LOGGER = "sync.logger"


@dataclass(frozen=True)
class ConsumerBinding:
    """One consumer's identity and the routing keys it binds on the exchange.

    `routing_keys` are topic-exchange patterns: a literal event type
    (`record.created`) binds just that type, while `#` binds every event. Pure
    data — the broker-topology epic reads this registry to declare the bindings.
    """

    name: str
    routing_keys: tuple[str, ...]


# The consumer→binding registry as pure data (TDD §5.3 / §5.4): the enrichment
# stub binds `record.created` and `lead.created`; the sync logger binds `#`, so
# every published event has at least one consumer.
CONSUMER_BINDINGS: tuple[ConsumerBinding, ...] = (
    ConsumerBinding(
        name=ENRICHMENT_STUB,
        routing_keys=(EventType.RECORD_CREATED.value, EventType.LEAD_CREATED.value),
    ),
    ConsumerBinding(name=SYNC_LOGGER, routing_keys=("#",)),
)


def consumers_for_event_type(event_type: str) -> tuple[str, ...]:
    """Return the consumer names that react to ``event_type``, in registry order.

    The single source of truth for the bus fan-out, kept next to the
    ``CONSUMER_BINDINGS`` data it reads. A consumer reacts when one of its
    ``routing_keys`` matches the event type: either a literal equality (e.g.
    ``lead.created``) or the catch-all ``#`` (the sync logger binds every event).
    The result preserves ``CONSUMER_BINDINGS`` order, so callers synthesising the
    expected reactions per event get a stable, registry-ordered fan-out — the same
    binding source the timeline read, the seed, and the isolation test all ride,
    never re-deriving the routing rule.
    """
    return tuple(
        binding.name
        for binding in CONSUMER_BINDINGS
        if event_type in binding.routing_keys or "#" in binding.routing_keys
    )
