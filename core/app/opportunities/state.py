"""The opportunity stage machine — the single source of truth for stage moves.

Before any stage endpoint, board, or Medicare gate can be written, the phase
needs one agreed set of *pipeline stages* (`New`, `Qualified`, `Quoted`, ...) and
the exact rule for which stage move is legal, pinned down in one place. Centralising
them means the service, the API edge, and the board can never disagree on a spelling
or wave through an illegal move — the same single-source-of-truth discipline already
used for `app.leads.state` and the event `EventType` enum.

This module is **pure logic — no database, no I/O, no FastAPI.** The enum values
are transcribed verbatim from the TDD §5.1 stage machine, so they are frozen by the
spec, not invented. `tests/test_opportunity_state.py` asserts every member and every
transition against an independent hand-written expectation so the vocabulary can
never silently drift out from under the phase.

Unlike the lead machine's static `ALLOWED_TRANSITIONS` set, the legal moves here
depend on the **tenant's enabled stage set** (a tenant may switch off the optional
`Quoted` / `Approved` stages). So the transition functions take that enabled set as
an argument and stay pure — the policy is *forward-by-one to the next enabled stage*,
plus *any active stage → Lost*. No backward moves, no multi-step skips, and no exit
from the terminal `Policy Active` / `Lost`.

`InvalidStageTransition` is deliberately framework-free (a plain `Exception`, not an
`HTTPException`). The stage endpoint catches it at the edge and maps it to HTTP 409 —
the pure core never reaches for the web framework.
"""

from enum import StrEnum

__all__ = [
    "OpportunityStage",
    "CANONICAL_FORWARD_ORDER",
    "OPTIONAL_STAGES",
    "ANCHOR_STAGES",
    "TERMINAL_STAGES",
    "ACTIVE_STAGES",
    "AUTOMATION_OWNED_STAGES",
    "InvalidStageTransition",
    "AutomationOwnedStageError",
    "next_enabled_stage",
    "allowed_targets",
    "assert_transition",
]


class OpportunityStage(StrEnum):
    """One member per pipeline stage (TDD §5.1 stage machine).

    Each string value is the exact stored/wire spelling — `Opportunity.stage`
    persists these literals (the model defaults to `'New'`). `Policy Active` and
    `Lost` are the terminal stages (no outgoing moves); `Lost` sits off the
    forward spine and is reachable from any active stage.
    """

    NEW = "New"
    QUALIFIED = "Qualified"
    QUOTED = "Quoted"
    APPLICATION_STARTED = "Application Started"
    SUBMITTED = "Submitted"
    APPROVED = "Approved"
    POLICY_ACTIVE = "Policy Active"
    LOST = "Lost"


# The ordered active spine (TDD §5.1): every forward move walks this tuple in
# order. `Lost` is intentionally absent — it is off-spine, reached sideways from
# any active stage, never by stepping forward. A tuple because order is the spec.
CANONICAL_FORWARD_ORDER: tuple[OpportunityStage, ...] = (
    OpportunityStage.NEW,
    OpportunityStage.QUALIFIED,
    OpportunityStage.QUOTED,
    OpportunityStage.APPLICATION_STARTED,
    OpportunityStage.SUBMITTED,
    OpportunityStage.APPROVED,
    OpportunityStage.POLICY_ACTIVE,
)

# The two stages a tenant may switch off (TDD §5.1). When disabled they drop out
# of the tenant's enabled set, so `next_enabled_stage` steps over them.
OPTIONAL_STAGES: frozenset[OpportunityStage] = frozenset(
    {OpportunityStage.QUOTED, OpportunityStage.APPROVED}
)

# The stages always present for every tenant (TDD §5.1): the spine endpoints plus
# `Lost`. `Qualified` and `Submitted` are also always present, but are neither
# optional nor anchors — they are simply never toggleable.
ANCHOR_STAGES: frozenset[OpportunityStage] = frozenset(
    {
        OpportunityStage.NEW,
        OpportunityStage.APPLICATION_STARTED,
        OpportunityStage.POLICY_ACTIVE,
        OpportunityStage.LOST,
    }
)

# The terminal stages — no outgoing moves (TDD §5.1). `Policy Active` ends the
# spine; `Lost` ends the sideways branch.
TERMINAL_STAGES: frozenset[OpportunityStage] = frozenset(
    {OpportunityStage.POLICY_ACTIVE, OpportunityStage.LOST}
)

# The Lost-able stages: the forward spine minus the terminal `Policy Active`
# (TDD §5.1, "everything Lost-able"). An opportunity at any of these may be
# marked `Lost`; one already terminal may not.
ACTIVE_STAGES: frozenset[OpportunityStage] = frozenset(
    CANONICAL_FORWARD_ORDER
) - {OpportunityStage.POLICY_ACTIVE}


# The stages the P2.3 money-path **automation** owns (TDD §5.5 / D6): a quote
# selection, a submit, the carrier decision, and policy issuance drive these via the
# internal stage-setter, never the manual machine. Once P2.3 ships, a manual move
# *into* one of these is rejected (the lockdown), so the automation is the single
# writer of these stages. `Quoted` is **not** here — the agent still drives → Quoted
# manually (or the quote round-trip advances it), so it stays manually reachable.
AUTOMATION_OWNED_STAGES: frozenset[OpportunityStage] = frozenset(
    {
        OpportunityStage.APPLICATION_STARTED,
        OpportunityStage.SUBMITTED,
        OpportunityStage.APPROVED,
        OpportunityStage.POLICY_ACTIVE,
    }
)


class InvalidStageTransition(Exception):
    """Raised when an opportunity stage move is not allowed for the tenant.

    Carries the attempted `current` and `target` stages so the stage endpoint can
    build a useful HTTP 409 message at the edge. Framework-free on purpose — the
    pure core never imports the web framework (mirrors `InvalidLeadTransition`).
    """

    def __init__(self, current: OpportunityStage, target: OpportunityStage) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Illegal opportunity stage transition: {current} -> {target}")


class AutomationOwnedStageError(Exception):
    """Raised when the **manual** machine is asked to move into an automation-owned stage.

    The move is otherwise legal (it passed `assert_transition`), but `target` is one
    of `AUTOMATION_OWNED_STAGES` — reached only by the P2.3 automation (the internal
    stage-setter), never by an agent's manual `POST /stage`. Carries the `target` so
    the endpoint builds a useful HTTP 422 "lifecycle-driven" message. Framework-free
    on purpose, like `InvalidStageTransition`. The internal setter does **not** raise
    this — it is the very path that owns these stages.
    """

    def __init__(self, target: OpportunityStage) -> None:
        self.target = target
        super().__init__(
            f"stage {target} is lifecycle-driven and cannot be set manually"
        )


def next_enabled_stage(
    current: OpportunityStage, enabled_stages: frozenset[OpportunityStage]
) -> OpportunityStage | None:
    """Return the single forward target — the next enabled stage after `current`.

    Walks `CANONICAL_FORWARD_ORDER` from just past `current` and returns the first
    stage that is in the tenant's `enabled_stages`, skipping any disabled optional
    stage. Returns `None` when there is no forward stage left — i.e. `current` is
    `Policy Active` (end of spine) or off-spine `Lost`.
    """
    if current not in CANONICAL_FORWARD_ORDER:
        return None  # off-spine `Lost` has no forward move
    current_index = CANONICAL_FORWARD_ORDER.index(current)
    for candidate in CANONICAL_FORWARD_ORDER[current_index + 1 :]:
        if candidate in enabled_stages:
            return candidate
    return None


def allowed_targets(
    current: OpportunityStage, enabled_stages: frozenset[OpportunityStage]
) -> set[OpportunityStage]:
    """Return every stage a `current` opportunity may legally move to.

    That is the next enabled stage (if any) plus `Lost` whenever `current` is an
    active (non-terminal) stage. A terminal `current` (`Policy Active` / `Lost`)
    yields an empty set — no moves out.
    """
    targets: set[OpportunityStage] = set()
    forward = next_enabled_stage(current, enabled_stages)
    if forward is not None:
        targets.add(forward)
    if current in ACTIVE_STAGES:
        targets.add(OpportunityStage.LOST)
    return targets


def assert_transition(
    current: OpportunityStage,
    target: OpportunityStage,
    enabled_stages: frozenset[OpportunityStage],
) -> None:
    """Allow a legal stage move; raise `InvalidStageTransition` otherwise.

    Returns `None` when `target` is one of `allowed_targets(current, enabled_stages)`
    (the caller proceeds). Raises `InvalidStageTransition` for every other move,
    including self-loops, backwards moves, multi-step skips, and exits from the
    terminal stages. This is the single public guard for stage changes; the
    endpoint maps the exception to HTTP 409.
    """
    if target not in allowed_targets(current, enabled_stages):
        raise InvalidStageTransition(current, target)
