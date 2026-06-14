"""Exhaustive unit test for the audit vocabulary enums.

Pure logic, no DB / no Docker / no async (sync functions, matching the suite's
style for non-async tests; see `test_rbac.py`).

The expected values below are written **independently** from the production
`EventType` / `Outcome` enums — they hand-transcribe the same normative TDD §5
*Interfaces* block. That makes every assertion a genuine cross-check against the
spec rather than a tautology over the enum under test.
"""

from app.audit.records import EventType, Outcome

# Independent transcription of the TDD §5 event-type values, member name ->
# expected string. Hand-built here on purpose, separate from `EventType`.
EXPECTED_EVENT_TYPES: dict[str, str] = {
    "AUTH_LOGIN": "auth.login",
    "AUTH_LOGOUT": "auth.logout",
    "PII_REVEALED": "pii.revealed",
    "RECORD_CREATED": "record.created",
    "PLATFORM_CROSS_TENANT_READ": "platform.cross_tenant_read",
    "AUDIT_VIEWED": "audit.viewed",
}

# Independent transcription of the TDD §5 outcome values. `denied` is reserved
# (RBAC-denial auditing deferred) and deliberately absent here.
EXPECTED_OUTCOMES: dict[str, str] = {
    "SUCCESS": "success",
    "FAILURE": "failure",
}


def test_every_event_type_has_the_expected_string_value():
    """Each `EventType` member's value matches the hand-written expectation."""
    for member_name, expected_value in EXPECTED_EVENT_TYPES.items():
        assert EventType[member_name].value == expected_value, member_name


def test_event_type_members_are_exactly_the_expected_set():
    """`EventType` has every expected member and no extra or missing ones."""
    assert {member.name for member in EventType} == set(EXPECTED_EVENT_TYPES)


def test_every_outcome_has_the_expected_string_value():
    """Each `Outcome` member's value matches the hand-written expectation."""
    for member_name, expected_value in EXPECTED_OUTCOMES.items():
        assert Outcome[member_name].value == expected_value, member_name


def test_outcome_members_are_exactly_the_expected_set():
    """`Outcome` has every expected member and no extra or missing ones."""
    assert {member.name for member in Outcome} == set(EXPECTED_OUTCOMES)


def test_denied_is_not_an_outcome_member():
    """`denied` stays a reserved comment, not a defined `Outcome` (Decision 6)."""
    member_names = {member.name for member in Outcome}
    member_values = {member.value for member in Outcome}
    assert "DENIED" not in member_names
    assert "denied" not in member_values
