"""Exhaustive unit test for the application state machine (P2.3).

Pure logic, no DB / no Docker / no async — matching the suite's style for the
sibling pure machines (`test_lead_state.py`, `test_opportunity_state.py`).

The expected values below are written **independently** from the production
`state.py` symbols — they hand-transcribe the same normative TDD §5.2 state
machine. That makes every assertion a genuine cross-check against the spec rather
than a tautology over the module under test.
"""

import itertools

import pytest

from app.applications.state import (
    ACTIVE_STATUSES,
    ALLOWED_TRANSITIONS,
    TERMINAL_STATUSES,
    ApplicationStatus,
    InvalidApplicationTransition,
    assert_transition,
)

# Independent transcription of the TDD §5.2 status values, member name -> expected
# string. Hand-built here on purpose, separate from `ApplicationStatus`.
EXPECTED_STATUSES: dict[str, str] = {
    "DRAFT": "Draft",
    "SUBMITTED": "Submitted",
    "APPROVED": "Approved",
    "DECLINED": "Declined",
    "SUPERSEDED": "Superseded",
}

# Independent transcription of the TDD §5.2 legal transitions, as `(current,
# target)` value pairs. Hand-built here on purpose, separate from the module.
EXPECTED_TRANSITIONS: set[tuple[str, str]] = {
    ("Draft", "Submitted"),
    ("Submitted", "Approved"),
    ("Submitted", "Declined"),
    ("Declined", "Superseded"),
}

# The Active (in-flight) and terminal sets, hand-built separate from the module.
EXPECTED_ACTIVE: set[str] = {"Draft", "Submitted"}
EXPECTED_TERMINAL: set[str] = {"Approved", "Superseded"}


def test_every_status_has_the_expected_string_value():
    """Each `ApplicationStatus` member's value matches the hand-written expectation."""
    for member_name, expected_value in EXPECTED_STATUSES.items():
        assert ApplicationStatus[member_name].value == expected_value, member_name


def test_status_members_are_exactly_the_expected_set():
    """`ApplicationStatus` has every expected member and no extra or missing ones."""
    assert {member.name for member in ApplicationStatus} == set(EXPECTED_STATUSES)


def test_allowed_transitions_match_the_expected_set():
    """`ALLOWED_TRANSITIONS` is exactly the hand-written set of legal pairs."""
    actual = {(current.value, target.value) for current, target in ALLOWED_TRANSITIONS}
    assert actual == EXPECTED_TRANSITIONS


def test_active_statuses_match_the_expected_set():
    """`ACTIVE_STATUSES` is exactly the in-flight `{Draft, Submitted}` set."""
    assert {status.value for status in ACTIVE_STATUSES} == EXPECTED_ACTIVE


def test_terminal_statuses_match_the_expected_set():
    """`TERMINAL_STATUSES` is exactly `{Approved, Superseded}` — no outgoing edges."""
    assert {status.value for status in TERMINAL_STATUSES} == EXPECTED_TERMINAL


def test_terminal_statuses_have_no_outgoing_transitions():
    """No terminal status appears as the `current` side of any legal transition."""
    currents_with_moves = {current for current, _ in ALLOWED_TRANSITIONS}
    for terminal in TERMINAL_STATUSES:
        assert terminal not in currents_with_moves, terminal


def test_assert_transition_allows_every_legal_move():
    """`assert_transition` returns `None` for each legal `(current, target)` pair."""
    for current, target in ALLOWED_TRANSITIONS:
        assert assert_transition(current, target) is None


def test_assert_transition_rejects_every_illegal_move():
    """Every `(current, target)` pair not in the legal set raises, including self-loops."""
    for current, target in itertools.product(ApplicationStatus, repeat=2):
        if (current, target) in ALLOWED_TRANSITIONS:
            continue
        with pytest.raises(InvalidApplicationTransition):
            assert_transition(current, target)


def test_invalid_transition_carries_current_and_target():
    """The raised error exposes the attempted `current` / `target` for the edge's 409."""
    with pytest.raises(InvalidApplicationTransition) as error_info:
        assert_transition(ApplicationStatus.DRAFT, ApplicationStatus.APPROVED)
    assert error_info.value.current == ApplicationStatus.DRAFT
    assert error_info.value.target == ApplicationStatus.APPROVED
