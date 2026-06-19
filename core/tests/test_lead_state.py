"""Exhaustive unit test for the lead state machine.

Pure logic, no DB / no Docker / no async (sync functions, matching the suite's
style for non-async tests; see `test_event_catalog.py`).

The expected values below are written **independently** from the production
`state.py` symbols — they hand-transcribe the same normative TDD §5.2 data-model
table and §5.3 state machine. That makes every assertion a genuine cross-check
against the spec rather than a tautology over the module under test.
"""

import pytest

from app.leads.state import (
    ALLOWED_TRANSITIONS,
    InvalidLeadTransition,
    LeadSource,
    LeadStatus,
    assert_transition,
)

# Independent transcription of the TDD §5.2 status values, member name ->
# expected string. Hand-built here on purpose, separate from `LeadStatus`.
# `Converted` is intentionally absent (reserved for P2.1).
EXPECTED_LEAD_STATUSES: dict[str, str] = {
    "NEW": "New",
    "WORKING": "Working",
    "QUALIFIED": "Qualified",
    "REJECTED": "Rejected",
}

# Independent transcription of the TDD §5.2 lead-source values, member name ->
# expected string. Hand-built here on purpose, separate from `LeadSource`.
EXPECTED_LEAD_SOURCES: dict[str, str] = {
    "PUBLIC_FORM": "public_form",
    "AGENT_ENTERED": "agent_entered",
}

# Independent transcription of the TDD §5.3 state machine: the exact set of legal
# (current, target) moves. Hand-built here on purpose.
EXPECTED_LEGAL_TRANSITIONS: set[tuple[str, str]] = {
    ("New", "Working"),  # claim
    ("New", "Rejected"),  # duplicate-resolution reject
    ("Working", "Qualified"),  # qualify
    ("Working", "Rejected"),  # reject
}

# A representative set of illegal moves the machine must reject: self-loops,
# backwards moves, exits from terminal states, and stage-skips.
ILLEGAL_TRANSITIONS: list[tuple[LeadStatus, LeadStatus]] = [
    (LeadStatus.NEW, LeadStatus.NEW),  # self-loop
    (LeadStatus.WORKING, LeadStatus.NEW),  # backwards
    (LeadStatus.QUALIFIED, LeadStatus.REJECTED),  # exit from terminal
    (LeadStatus.REJECTED, LeadStatus.WORKING),  # exit from terminal
    (LeadStatus.NEW, LeadStatus.QUALIFIED),  # skips a stage
]


def test_every_lead_status_has_the_expected_string_value():
    """Each `LeadStatus` member's value matches the hand-written expectation."""
    for member_name, expected_value in EXPECTED_LEAD_STATUSES.items():
        assert LeadStatus[member_name].value == expected_value, member_name


def test_lead_status_members_are_exactly_the_expected_set():
    """`LeadStatus` has every expected member and no extra or missing ones.

    Guards in particular against `Converted` slipping in early (it is P2.1's).
    """
    assert {member.name for member in LeadStatus} == set(EXPECTED_LEAD_STATUSES)


def test_every_lead_source_has_the_expected_string_value():
    """Each `LeadSource` member's value matches the hand-written expectation."""
    for member_name, expected_value in EXPECTED_LEAD_SOURCES.items():
        assert LeadSource[member_name].value == expected_value, member_name


def test_lead_source_members_are_exactly_the_expected_set():
    """`LeadSource` has every expected member and no extra or missing ones."""
    assert {member.name for member in LeadSource} == set(EXPECTED_LEAD_SOURCES)


def test_allowed_transitions_are_exactly_the_expected_set():
    """`ALLOWED_TRANSITIONS` holds every legal move and no extra or missing ones.

    The exact-set discipline the enum members get, applied to the transitions:
    an accidentally-added fifth move (e.g. a premature `Qualified -> Converted`)
    is caught here rather than silently widening the machine.
    """
    actual_transitions = {
        (current.value, target.value) for current, target in ALLOWED_TRANSITIONS
    }
    assert actual_transitions == EXPECTED_LEGAL_TRANSITIONS


def test_every_legal_transition_passes_silently():
    """Each of the four legal moves returns `None` (no exception raised)."""
    for current_value, target_value in EXPECTED_LEGAL_TRANSITIONS:
        current = LeadStatus(current_value)
        target = LeadStatus(target_value)
        assert assert_transition(current, target) is None, (current, target)


@pytest.mark.parametrize("current, target", ILLEGAL_TRANSITIONS)
def test_illegal_transition_raises(current: LeadStatus, target: LeadStatus):
    """A representative illegal move raises `InvalidLeadTransition`."""
    with pytest.raises(InvalidLeadTransition):
        assert_transition(current, target)


def test_invalid_transition_carries_current_and_target():
    """`InvalidLeadTransition` exposes the attempted statuses for the edge layer."""
    with pytest.raises(InvalidLeadTransition) as raised:
        assert_transition(LeadStatus.NEW, LeadStatus.QUALIFIED)
    assert raised.value.current == LeadStatus.NEW
    assert raised.value.target == LeadStatus.QUALIFIED
