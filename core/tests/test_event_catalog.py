"""Exhaustive unit test for the event vocabulary.

Pure logic, no DB / no Docker / no async (sync functions, matching the suite's
style for non-async tests; see `test_audit_records.py`).

The expected values below are written **independently** from the production
`catalog.py` symbols — they hand-transcribe the same normative TDD §5.3
*Interfaces* block. That makes every assertion a genuine cross-check against the
spec rather than a tautology over the module under test.
"""

from app.events.catalog import (
    CONSUMER_BINDINGS,
    ENRICHMENT_STUB,
    SCHEMA_VERSION,
    SYNC_LOGGER,
    EventType,
)

# Independent transcription of the TDD §5.3 event-type values, member name ->
# expected string. Hand-built here on purpose, separate from `EventType`.
EXPECTED_EVENT_TYPES: dict[str, str] = {
    "RECORD_CREATED": "record.created",
    "PII_REVEALED": "pii.revealed",
}

# Independent transcription of the TDD §5.3 / §5.4 consumer→binding registry,
# consumer name -> expected routing-key tuple. Hand-built here on purpose.
EXPECTED_CONSUMER_BINDINGS: dict[str, tuple[str, ...]] = {
    "enrichment.stub": ("record.created",),
    "sync.logger": ("#",),
}


def test_every_event_type_has_the_expected_string_value():
    """Each `EventType` member's value matches the hand-written expectation."""
    for member_name, expected_value in EXPECTED_EVENT_TYPES.items():
        assert EventType[member_name].value == expected_value, member_name


def test_event_type_members_are_exactly_the_expected_set():
    """`EventType` has every expected member and no extra or missing ones."""
    assert {member.name for member in EventType} == set(EXPECTED_EVENT_TYPES)


def test_schema_version_is_one():
    """`SCHEMA_VERSION` is frozen at 1 (TDD §5.3, Decision 11)."""
    assert SCHEMA_VERSION == 1


def test_consumer_name_constants_match_the_expected_values():
    """The exported consumer-name constants match the hand-written expectation."""
    assert ENRICHMENT_STUB == "enrichment.stub"
    assert SYNC_LOGGER == "sync.logger"


def test_every_consumer_binds_its_expected_routing_keys():
    """Each consumer in the registry binds exactly its expected routing keys."""
    bindings_by_name = {binding.name: binding.routing_keys for binding in CONSUMER_BINDINGS}
    for consumer_name, expected_routing_keys in EXPECTED_CONSUMER_BINDINGS.items():
        assert bindings_by_name[consumer_name] == expected_routing_keys, consumer_name


def test_consumers_are_exactly_the_expected_set():
    """The registry lists every expected consumer and no extra or missing ones."""
    consumer_names = {binding.name for binding in CONSUMER_BINDINGS}
    assert consumer_names == set(EXPECTED_CONSUMER_BINDINGS)
