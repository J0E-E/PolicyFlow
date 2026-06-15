"""Unit tests for the event envelope — builder, JSON round-trip, and wire shape.

Pure logic, no DB / no Docker / no async (sync functions, matching the suite's
style for non-async tests; see `test_audit_records.py`).

The builder section asserts the fields `build_envelope` mints/stamps; the
round-trip section proves `from_message_body(to_message_body(env)) == env` for
both an actor-present and a system-actor envelope, and asserts the decoded body's
shape independently — flat keys, string UUIDs, an ISO `occurred_at` carrying the
`+00:00` offset, and JSON `null` for absent optionals.
"""

import dataclasses
import json
import uuid
from datetime import datetime, timezone

import pytest

from app.events.catalog import SCHEMA_VERSION
from app.events.envelope import (
    EventEnvelope,
    build_envelope,
    from_message_body,
    to_message_body,
)


def _build_actor_envelope() -> EventEnvelope:
    """An envelope with a human actor and a supplied correlation id."""
    return build_envelope(
        event_type="record.created",
        tenant_id=uuid.uuid4(),
        actor_user_id=uuid.uuid4(),
        actor_role="agent",
        payload={"record_id": str(uuid.uuid4()), "age_band": "30-39"},
        correlation_id=uuid.uuid4(),
    )


def _build_system_actor_envelope() -> EventEnvelope:
    """An envelope with no human actor (both actor fields `None`)."""
    return build_envelope(
        event_type="pii.revealed",
        tenant_id=uuid.uuid4(),
        actor_user_id=None,
        actor_role=None,
        payload={"field_name": "email"},
    )


# --- Builder section -------------------------------------------------------


def test_build_envelope_mints_a_uuid_event_id():
    """`event_id` is a freshly minted UUID."""
    envelope = _build_actor_envelope()
    assert isinstance(envelope.event_id, uuid.UUID)


def test_build_envelope_gives_two_calls_distinct_event_ids():
    """Each build mints its own `event_id` — two builds never collide."""
    assert _build_actor_envelope().event_id != _build_actor_envelope().event_id


def test_build_envelope_stamps_the_frozen_schema_version():
    """`schema_version` is stamped from the contract constant."""
    assert _build_actor_envelope().schema_version == SCHEMA_VERSION == 1


def test_build_envelope_stamps_a_timezone_aware_utc_occurred_at():
    """`occurred_at` is a timezone-aware datetime at UTC offset."""
    occurred_at = _build_actor_envelope().occurred_at
    assert isinstance(occurred_at, datetime)
    assert occurred_at.tzinfo is not None
    assert occurred_at.utcoffset() == timezone.utc.utcoffset(None)


def test_build_envelope_defaults_demo_session_id_to_none():
    """`demo_session_id` is always `None` in P1.5 (P1.8 owns it)."""
    assert _build_actor_envelope().demo_session_id is None


def test_build_envelope_defaults_causation_id_to_none():
    """`causation_id` defaults to `None` when not supplied."""
    assert _build_system_actor_envelope().causation_id is None


def test_build_envelope_mints_a_fresh_correlation_id_when_omitted():
    """A new flow gets a freshly minted `correlation_id`."""
    envelope = _build_system_actor_envelope()
    assert isinstance(envelope.correlation_id, uuid.UUID)


def test_build_envelope_preserves_a_supplied_correlation_id():
    """A supplied `correlation_id` is carried through unchanged."""
    correlation_id = uuid.uuid4()
    envelope = build_envelope(
        event_type="record.created",
        tenant_id=uuid.uuid4(),
        actor_user_id=uuid.uuid4(),
        actor_role="agent",
        payload={},
        correlation_id=correlation_id,
    )
    assert envelope.correlation_id == correlation_id


def test_envelope_is_frozen():
    """The dataclass is frozen — assigning a field raises."""
    envelope = _build_actor_envelope()
    with pytest.raises(dataclasses.FrozenInstanceError):
        envelope.event_type = "pii.revealed"


# --- Round-trip + wire-shape section ---------------------------------------


def test_round_trip_preserves_an_actor_envelope():
    """An actor-present envelope survives serialize → parse unchanged."""
    envelope = _build_actor_envelope()
    assert from_message_body(to_message_body(envelope)) == envelope


def test_round_trip_preserves_a_system_actor_envelope():
    """A system-actor (all-null) envelope survives serialize → parse unchanged."""
    envelope = _build_system_actor_envelope()
    assert from_message_body(to_message_body(envelope)) == envelope


def test_to_message_body_returns_utf8_bytes():
    """The serialized body is UTF-8 bytes (the broker body type)."""
    assert isinstance(to_message_body(_build_actor_envelope()), bytes)


def test_wire_body_keys_are_flat_with_no_nested_actor():
    """The decoded body's keys mirror the dataclass 1:1 — flat, no nested actor."""
    envelope = _build_actor_envelope()
    body = json.loads(to_message_body(envelope))
    expected_keys = {field.name for field in dataclasses.fields(EventEnvelope)}
    assert set(body) == expected_keys
    assert "actor_user_id" in body
    assert "actor_role" in body
    assert "actor" not in body


def test_wire_body_serializes_uuids_as_strings():
    """UUID fields serialize as canonical hyphenated strings."""
    envelope = _build_actor_envelope()
    body = json.loads(to_message_body(envelope))
    assert body["event_id"] == str(envelope.event_id)
    assert body["tenant_id"] == str(envelope.tenant_id)
    assert body["correlation_id"] == str(envelope.correlation_id)
    assert body["actor_user_id"] == str(envelope.actor_user_id)


def test_wire_body_serializes_occurred_at_as_iso_with_utc_offset():
    """`occurred_at` serializes as an ISO-8601 string carrying the `+00:00` offset."""
    body = json.loads(to_message_body(_build_actor_envelope()))
    assert isinstance(body["occurred_at"], str)
    assert body["occurred_at"].endswith("+00:00")


def test_wire_body_serializes_absent_optionals_as_null():
    """Absent optionals decode to JSON `null` (`None` in Python)."""
    body = json.loads(to_message_body(_build_system_actor_envelope()))
    assert body["actor_user_id"] is None
    assert body["actor_role"] is None
    assert body["causation_id"] is None
    assert body["demo_session_id"] is None
