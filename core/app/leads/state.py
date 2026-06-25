"""The lead state machine — the single source of truth for lead status moves.

Before any persistence, intake, or action endpoint can be written, the phase
needs one agreed set of *lead statuses* (`New`, `Working`, ...), *lead sources*
(`public_form`, `agent_entered`), and the exact set of *legal status
transitions* pinned down in one place. Centralising them means the ORM model,
the create-path, and every action endpoint (claim, qualify, reject,
resolve-duplicate) can never disagree on a spelling or wave through an illegal
move — the same single-source-of-truth move already used for the event
`EventType` enum and the RBAC capability matrix.

This module is **pure logic — no database, no I/O, no FastAPI.** The enum values
are transcribed verbatim from the TDD §5.2 data-model table and the §5.3 state
machine, so they are frozen by the spec, not invented. `tests/test_lead_state.py`
asserts every member and every transition against an independent hand-written
expectation so the vocabulary can never silently drift out from under the phase.

`Converted` is the **terminal** lead state (added in P2.1): a lead reaches it via
the one `Qualified → Converted` edge and has **no outgoing edges**, so claim,
qualify, reject, and any other status move out of it all fail `assert_transition`
(the edge layer maps that to 409). The conversion action itself owns the freeze.

`InvalidLeadTransition` is deliberately framework-free (a plain `Exception`, not
an `HTTPException`). The endpoint epics (12–14) catch it at the edge and map it
to HTTP 409 / 422 — the pure core never reaches for the web framework.
"""

from enum import StrEnum

__all__ = [
    "LeadStatus",
    "LeadSource",
    "ALLOWED_TRANSITIONS",
    "InvalidLeadTransition",
    "assert_transition",
]


class LeadStatus(StrEnum):
    """One member per lead status (TDD §5.2 data-model table / §5.3 machine).

    Each string value is the exact stored/wire spelling. `Rejected` and
    `Converted` are the terminal states (no outgoing edges); a `Qualified` lead
    can still move on — to `Converted` via the conversion action.
    """

    NEW = "New"
    WORKING = "Working"
    QUALIFIED = "Qualified"
    REJECTED = "Rejected"
    CONVERTED = "Converted"


class LeadSource(StrEnum):
    """One member per way a lead enters the system (TDD §5.2 / §3 Goals).

    `public_form` is the unauthenticated self-service intake; `agent_entered`
    is the authenticated agent-entered intake.
    """

    PUBLIC_FORM = "public_form"
    AGENT_ENTERED = "agent_entered"


# The legal status moves as frozen spec data (TDD §5.3 state machine): exactly
# these four `(current, target)` pairs and no others. Any move not listed here
# is rejected by `assert_transition`. A frozenset because the source of truth is
# immutable.
ALLOWED_TRANSITIONS: frozenset[tuple[LeadStatus, LeadStatus]] = frozenset(
    {
        (LeadStatus.NEW, LeadStatus.WORKING),  # claim
        (LeadStatus.NEW, LeadStatus.REJECTED),  # duplicate-resolution reject
        (LeadStatus.WORKING, LeadStatus.QUALIFIED),  # qualify
        (LeadStatus.WORKING, LeadStatus.REJECTED),  # reject
        (LeadStatus.QUALIFIED, LeadStatus.CONVERTED),  # convert (P2.1)
    }
)


class InvalidLeadTransition(Exception):
    """Raised when a lead status move is not in `ALLOWED_TRANSITIONS`.

    Carries the attempted `current` and `target` statuses so the endpoint epics
    (12–14) can build a useful HTTP 409 / 422 message at the edge. Framework-free
    on purpose — the pure core never imports the web framework.
    """

    def __init__(self, current: LeadStatus, target: LeadStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Illegal lead status transition: {current} -> {target}")


def assert_transition(current: LeadStatus, target: LeadStatus) -> None:
    """Allow a legal status move; raise `InvalidLeadTransition` otherwise.

    Returns `None` when `(current, target)` is one of `ALLOWED_TRANSITIONS`
    (the caller proceeds). Raises `InvalidLeadTransition` for every other move,
    including self-loops, backwards moves, exits from terminal states, and
    stage-skips. This is the single public guard for status changes.
    """
    if (current, target) not in ALLOWED_TRANSITIONS:
        raise InvalidLeadTransition(current, target)
