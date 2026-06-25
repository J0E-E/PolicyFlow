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
    consumers_for_event_type,
)

# Independent transcription of the TDD §5.3 event-type values, member name ->
# expected string. Hand-built here on purpose, separate from `EventType`.
EXPECTED_EVENT_TYPES: dict[str, str] = {
    "RECORD_CREATED": "record.created",
    "PII_REVEALED": "pii.revealed",
    "LEAD_CREATED": "lead.created",
    "LEAD_DUPLICATE_DETECTED": "lead.duplicate_detected",
    "LEAD_ASSIGNED": "lead.assigned",
    "LEAD_QUALIFIED": "lead.qualified",
    "LEAD_REJECTED": "lead.rejected",
    "LEAD_CONVERTED": "lead.converted",
    "CONTACT_CREATED": "contact.created",
    "HOUSEHOLD_CREATED": "household.created",
    "OPPORTUNITY_CREATED": "opportunity.created",
}

# Independent transcription of the TDD §5.3 / §5.4 consumer→binding registry,
# consumer name -> expected routing-key tuple. Hand-built here on purpose.
EXPECTED_CONSUMER_BINDINGS: dict[str, tuple[str, ...]] = {
    "enrichment.stub": ("record.created", "lead.created"),
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


def test_lead_created_fans_out_to_enrichment_then_sync_logger():
    """`lead.created` reacts via the enrichment stub (literal) *and* the sync logger (`#`).

    The order is registry order — enrichment before the logger — so the synthesized
    reaction rows are stable and the literal match and the `#` catch-all both fire.
    """
    assert consumers_for_event_type("lead.created") == (ENRICHMENT_STUB, SYNC_LOGGER)


def test_other_lead_events_fan_out_to_sync_logger_only_via_catch_all():
    """Lead events the enrichment stub does not bind reach the sync logger alone.

    `lead.assigned` / `qualified` / `rejected` match no enrichment routing key, so only
    the `#`-binding sync logger reacts — the faithful fan-out (one consumer per event).
    """
    for event_type in ("lead.assigned", "lead.qualified", "lead.rejected"):
        assert consumers_for_event_type(event_type) == (SYNC_LOGGER,), event_type


def test_conversion_events_fan_out_to_sync_logger_only():
    """The four P2.1 conversion events reach the sync logger alone (no enrichment bind).

    `enrichment.stub` binds only `record.created` / `lead.created`, so each conversion
    event matches the `#` catch-all only — the lead timeline shows `lead.converted`
    plus its single sync-logger reaction, never a stub enrichment reaction.
    """
    for event_type in (
        "lead.converted",
        "contact.created",
        "household.created",
        "opportunity.created",
    ):
        assert consumers_for_event_type(event_type) == (SYNC_LOGGER,), event_type


def test_unknown_event_type_still_reaches_the_catch_all_logger():
    """An event type bound by no literal still fans out to the `#` sync logger."""
    assert consumers_for_event_type("some.unmapped.event") == (SYNC_LOGGER,)
