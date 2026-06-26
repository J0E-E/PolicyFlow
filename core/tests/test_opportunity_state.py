"""Exhaustive unit test for the opportunity stage machine.

Pure logic, no DB / no Docker / no async (sync functions, matching the suite's
style for non-async tests; mirrors `test_lead_state.py`).

The expected values below are written **independently** from the production
`state.py` symbols — they hand-transcribe the same normative TDD §5.1 stage
machine. That makes every assertion a genuine cross-check against the spec rather
than a tautology over the module under test.
"""

import pytest

from app.opportunities.state import (
    ACTIVE_STAGES,
    ANCHOR_STAGES,
    AUTOMATION_OWNED_STAGES,
    CANONICAL_FORWARD_ORDER,
    OPTIONAL_STAGES,
    TERMINAL_STAGES,
    InvalidStageTransition,
    OpportunityStage,
    allowed_targets,
    assert_transition,
    next_enabled_stage,
)

# Independent transcription of the P2.3 automation-owned stages (D6), hand-built
# separate from the module — the stages the money-path automation drives and the
# manual machine is locked out of. `Quoted` is deliberately absent.
EXPECTED_AUTOMATION_OWNED = {"Application Started", "Submitted", "Approved", "Policy Active"}

# Independent transcription of the TDD §5.1 stage values, member name -> expected
# string. Hand-built here on purpose, separate from `OpportunityStage`.
EXPECTED_STAGES: dict[str, str] = {
    "NEW": "New",
    "QUALIFIED": "Qualified",
    "QUOTED": "Quoted",
    "APPLICATION_STARTED": "Application Started",
    "SUBMITTED": "Submitted",
    "APPROVED": "Approved",
    "POLICY_ACTIVE": "Policy Active",
    "LOST": "Lost",
}

# Independent transcription of the §5.1 ordered active spine (Lost off-spine).
EXPECTED_FORWARD_ORDER: list[str] = [
    "New",
    "Qualified",
    "Quoted",
    "Application Started",
    "Submitted",
    "Approved",
    "Policy Active",
]

# Independent transcription of the §5.1 stage sets, by string value.
EXPECTED_OPTIONAL: set[str] = {"Quoted", "Approved"}
EXPECTED_ANCHOR: set[str] = {"New", "Application Started", "Policy Active", "Lost"}
EXPECTED_TERMINAL: set[str] = {"Policy Active", "Lost"}
EXPECTED_ACTIVE: set[str] = {
    "New",
    "Qualified",
    "Quoted",
    "Application Started",
    "Submitted",
    "Approved",
}

# A tenant with every optional stage on = the whole forward spine enabled.
FULLY_ENABLED: frozenset[OpportunityStage] = frozenset(
    OpportunityStage(value) for value in EXPECTED_FORWARD_ORDER
)
# A Florida-like tenant with `Approved` switched off (proves the skip).
APPROVED_DISABLED: frozenset[OpportunityStage] = FULLY_ENABLED - {
    OpportunityStage.APPROVED
}
# A tenant with `Quoted` switched off.
QUOTED_DISABLED: frozenset[OpportunityStage] = FULLY_ENABLED - {
    OpportunityStage.QUOTED
}


# --- Vocabulary: members + frozen sets match the spec exactly --------------- #


def test_every_stage_has_the_expected_string_value():
    """Each `OpportunityStage` member's value matches the hand-written expectation."""
    for member_name, expected_value in EXPECTED_STAGES.items():
        assert OpportunityStage[member_name].value == expected_value, member_name


def test_stage_members_are_exactly_the_expected_set():
    """`OpportunityStage` has every expected member and no extra or missing ones."""
    assert {member.name for member in OpportunityStage} == set(EXPECTED_STAGES)


def test_canonical_forward_order_matches_the_spec():
    """The forward spine is the expected stages in the expected order (Lost off-spine)."""
    assert [stage.value for stage in CANONICAL_FORWARD_ORDER] == EXPECTED_FORWARD_ORDER
    assert OpportunityStage.LOST not in CANONICAL_FORWARD_ORDER


def test_optional_anchor_terminal_active_sets_match_the_spec():
    """Each frozen stage set holds exactly the expected members and no others."""
    assert {stage.value for stage in OPTIONAL_STAGES} == EXPECTED_OPTIONAL
    assert {stage.value for stage in ANCHOR_STAGES} == EXPECTED_ANCHOR
    assert {stage.value for stage in TERMINAL_STAGES} == EXPECTED_TERMINAL
    assert {stage.value for stage in ACTIVE_STAGES} == EXPECTED_ACTIVE


# --- Happy path: a fully-enabled tenant walks the whole spine --------------- #


def test_next_enabled_stage_walks_the_full_spine_to_none():
    """With every stage on, the forward target steps one-by-one to None at the end."""
    expected_next = {
        "New": OpportunityStage.QUALIFIED,
        "Qualified": OpportunityStage.QUOTED,
        "Quoted": OpportunityStage.APPLICATION_STARTED,
        "Application Started": OpportunityStage.SUBMITTED,
        "Submitted": OpportunityStage.APPROVED,
        "Approved": OpportunityStage.POLICY_ACTIVE,
        "Policy Active": None,  # end of spine
    }
    for current_value, expected in expected_next.items():
        current = OpportunityStage(current_value)
        assert next_enabled_stage(current, FULLY_ENABLED) is expected, current


def test_every_forward_by_one_move_passes_silently():
    """Each legal forward-by-one move returns None (no exception) for a full tenant."""
    spine = [OpportunityStage(value) for value in EXPECTED_FORWARD_ORDER]
    for current, target in zip(spine, spine[1:]):
        assert assert_transition(current, target, FULLY_ENABLED) is None, (
            current,
            target,
        )


def test_allowed_targets_of_an_active_stage_are_next_plus_lost():
    """An active stage may move forward-by-one or to Lost — and nowhere else."""
    assert allowed_targets(OpportunityStage.QUALIFIED, FULLY_ENABLED) == {
        OpportunityStage.QUOTED,
        OpportunityStage.LOST,
    }


# --- Skip semantics: a disabled optional stage is stepped over -------------- #


def test_disabled_approved_is_skipped_to_policy_active():
    """With Approved off, Submitted's forward target is Policy Active (the skip)."""
    assert (
        next_enabled_stage(OpportunityStage.SUBMITTED, APPROVED_DISABLED)
        is OpportunityStage.POLICY_ACTIVE
    )
    # The skipped stage is not a legal target, but the skip-to stage is.
    assert assert_transition(
        OpportunityStage.SUBMITTED, OpportunityStage.POLICY_ACTIVE, APPROVED_DISABLED
    ) is None
    with pytest.raises(InvalidStageTransition):
        assert_transition(
            OpportunityStage.SUBMITTED, OpportunityStage.APPROVED, APPROVED_DISABLED
        )


def test_disabled_quoted_is_skipped_to_application_started():
    """With Quoted off, Qualified's forward target is Application Started (the skip)."""
    assert (
        next_enabled_stage(OpportunityStage.QUALIFIED, QUOTED_DISABLED)
        is OpportunityStage.APPLICATION_STARTED
    )


# --- Any active stage may move to Lost; terminals may not move at all -------- #


def test_every_active_stage_may_move_to_lost():
    """From any active (non-terminal) stage, the move to Lost is legal."""
    for stage in ACTIVE_STAGES:
        assert OpportunityStage.LOST in allowed_targets(stage, FULLY_ENABLED), stage
        assert assert_transition(stage, OpportunityStage.LOST, FULLY_ENABLED) is None, (
            stage
        )


def test_terminal_stages_have_no_outgoing_moves():
    """`Policy Active` and `Lost` yield an empty target set and reject every move."""
    for terminal in (OpportunityStage.POLICY_ACTIVE, OpportunityStage.LOST):
        assert allowed_targets(terminal, FULLY_ENABLED) == set(), terminal
        assert next_enabled_stage(terminal, FULLY_ENABLED) is None, terminal
    with pytest.raises(InvalidStageTransition):
        assert_transition(
            OpportunityStage.POLICY_ACTIVE, OpportunityStage.LOST, FULLY_ENABLED
        )
    with pytest.raises(InvalidStageTransition):
        assert_transition(
            OpportunityStage.LOST, OpportunityStage.NEW, FULLY_ENABLED
        )


# --- Illegal moves: self-loops, backwards, multi-skips ---------------------- #

ILLEGAL_TRANSITIONS: list[tuple[OpportunityStage, OpportunityStage]] = [
    (OpportunityStage.NEW, OpportunityStage.NEW),  # self-loop
    (OpportunityStage.QUALIFIED, OpportunityStage.NEW),  # backwards
    (OpportunityStage.NEW, OpportunityStage.QUOTED),  # multi-step skip
    (OpportunityStage.NEW, OpportunityStage.POLICY_ACTIVE),  # skip to the end
    (OpportunityStage.POLICY_ACTIVE, OpportunityStage.LOST),  # exit from terminal
    (OpportunityStage.LOST, OpportunityStage.QUALIFIED),  # exit from terminal
]


@pytest.mark.parametrize("current, target", ILLEGAL_TRANSITIONS)
def test_illegal_transition_raises(
    current: OpportunityStage, target: OpportunityStage
):
    """A representative illegal move raises `InvalidStageTransition`."""
    with pytest.raises(InvalidStageTransition):
        assert_transition(current, target, FULLY_ENABLED)


def test_invalid_transition_carries_current_and_target():
    """`InvalidStageTransition` exposes the attempted stages for the edge layer."""
    with pytest.raises(InvalidStageTransition) as raised:
        assert_transition(
            OpportunityStage.NEW, OpportunityStage.POLICY_ACTIVE, FULLY_ENABLED
        )
    assert raised.value.current == OpportunityStage.NEW
    assert raised.value.target == OpportunityStage.POLICY_ACTIVE


def test_automation_owned_stages_match_the_spec():
    """`AUTOMATION_OWNED_STAGES` is exactly the four money-path automation stages (D6)."""
    assert {stage.value for stage in AUTOMATION_OWNED_STAGES} == EXPECTED_AUTOMATION_OWNED
    # `Quoted` stays manually reachable, so it is never automation-owned.
    assert OpportunityStage.QUOTED not in AUTOMATION_OWNED_STAGES
