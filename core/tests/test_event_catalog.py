"""Exhaustive unit test for the event vocabulary.

Pure logic, no DB / no Docker / no async (sync functions, matching the suite's
style for non-async tests; see `test_audit_records.py`).

The expected values below are written **independently** from the production
`catalog.py` symbols — they hand-transcribe the same normative TDD §5.3
*Interfaces* block. That makes every assertion a genuine cross-check against the
spec rather than a tautology over the module under test.
"""

from app.events.catalog import (
    CARRIER_QUOTE,
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
    "OPPORTUNITY_STAGE_CHANGED": "opportunity.stage_changed",
    "OPPORTUNITY_LOST": "opportunity.lost",
    "QUOTE_REQUESTED": "quote.requested",
    "QUOTE_COMPLETED": "quote.completed",
    "APPLICATION_STARTED": "application.started",
    "APPLICATION_SUBMITTED": "application.submitted",
    "APPLICATION_APPROVED": "application.approved",
    "APPLICATION_DECLINED": "application.declined",
    "POLICY_CREATED": "policy.created",
    "POLICY_RENEWAL_DUE": "policy.renewal_due",
}

# Independent transcription of the TDD §5.3 / §5.4 consumer→binding registry,
# consumer name -> expected routing-key tuple. Hand-built here on purpose.
EXPECTED_CONSUMER_BINDINGS: dict[str, tuple[str, ...]] = {
    "enrichment.stub": ("record.created", "lead.created"),
    "carrier.quote": ("quote.requested",),
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
    assert CARRIER_QUOTE == "carrier.quote"


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


def test_pipeline_events_fan_out_to_sync_logger_only():
    """The two P2.2 pipeline events reach the sync logger alone (no enrichment bind).

    `enrichment.stub` binds only `record.created` / `lead.created`, so each pipeline
    event matches the `#` catch-all only — `opportunity.stage_changed` and
    `opportunity.lost` fan out to the sync logger, no stub reaction.
    """
    for event_type in ("opportunity.stage_changed", "opportunity.lost"):
        assert consumers_for_event_type(event_type) == (SYNC_LOGGER,), event_type


def test_quote_requested_fans_out_to_carrier_quote_then_sync_logger():
    """`quote.requested` reacts via the carrier-quote stub (literal) *and* the sync logger (`#`).

    Registry order puts the `carrier.quote` stub before the `#` logger, so the
    money-path round-trip has its non-terminal stub plus the catch-all reaction.
    """
    assert consumers_for_event_type("quote.requested") == (CARRIER_QUOTE, SYNC_LOGGER)


def test_other_money_path_events_fan_out_to_sync_logger_only():
    """The six non-`quote.requested` P2.3 events reach the sync logger alone (no stub bind).

    `carrier.quote` binds only `quote.requested`, so every other money-path event
    matches the `#` catch-all only — `quote.completed` and the application/policy
    members fan out to the sync logger, no stub reaction.
    """
    for event_type in (
        "quote.completed",
        "application.started",
        "application.submitted",
        "application.approved",
        "application.declined",
        "policy.created",
    ):
        assert consumers_for_event_type(event_type) == (SYNC_LOGGER,), event_type


def test_policy_renewal_due_fans_out_to_sync_logger_only():
    """The P2.4 renewal event reaches the sync logger alone (no dedicated bind).

    `policy.renewal_due` carries no literal binding — it rides the `#` catch-all
    only (TDD §5.3 / Decision 6), so a renewal sweep's event fans out to the
    sync logger and the binding registry stays unchanged.
    """
    assert consumers_for_event_type("policy.renewal_due") == (SYNC_LOGGER,)


def test_unknown_event_type_still_reaches_the_catch_all_logger():
    """An event type bound by no literal still fans out to the `#` sync logger."""
    assert consumers_for_event_type("some.unmapped.event") == (SYNC_LOGGER,)
