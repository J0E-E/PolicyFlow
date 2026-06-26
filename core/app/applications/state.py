"""The application state machine — the single source of truth for status moves.

Before any code creates an application, the phase needs one agreed set of
*application statuses* (`Draft`, `Submitted`, ...) and the exact set of *legal
status transitions* pinned down in one place. Centralising them means the ORM
model, the select/submit actions, and the inline carrier decision can never
disagree on a spelling or wave through an illegal move — the same
single-source-of-truth discipline already used for `app.leads.state`,
`app.opportunities.state`, and the event `EventType` enum.

This module is **pure logic — no database, no I/O, no FastAPI.** The enum values
are transcribed verbatim from the TDD §5.2 state machine, so they are frozen by
the spec, not invented. `tests/test_application_state.py` asserts every member and
every transition against an independent hand-written expectation so the vocabulary
can never silently drift out from under the phase.

Unlike the opportunity machine (whose legal moves depend on the tenant's enabled
stage set), the application machine is **static** — the same five moves for every
tenant — so it follows the `app.leads.state` shape: a frozen set of
`(current, target)` pairs and a single `assert_transition` guard, with no tenant
argument. `Approved` and `Superseded` are the terminal states (no outgoing edges);
`Declined` is non-terminal — it has the one `Declined → Superseded` edge a later
selection sets when a fresh application supersedes it. **Active** is `{Draft,
Submitted}` — the in-flight statuses the "one active application per opportunity"
rule (TDD C5) keys on.

`InvalidApplicationTransition` is deliberately framework-free (a plain `Exception`,
not an `HTTPException`). The action epics catch it at the edge and map it to HTTP
409 — the pure core never reaches for the web framework (mirrors
`InvalidLeadTransition`).
"""

from enum import StrEnum

__all__ = [
    "ApplicationStatus",
    "ALLOWED_TRANSITIONS",
    "ACTIVE_STATUSES",
    "TERMINAL_STATUSES",
    "InvalidApplicationTransition",
    "assert_transition",
]


class ApplicationStatus(StrEnum):
    """One member per application status (TDD §5.2 state machine).

    Each string value is the exact stored/wire spelling — `Application.status`
    persists these literals. `Approved` and `Superseded` are the terminal states
    (no outgoing edges); `Declined` is non-terminal, reachable from `Submitted`
    and itself moving on only to `Superseded` when a later selection supersedes it.
    """

    DRAFT = "Draft"
    SUBMITTED = "Submitted"
    APPROVED = "Approved"
    DECLINED = "Declined"
    SUPERSEDED = "Superseded"


# The legal status moves as frozen spec data (TDD §5.2 state machine): exactly
# these four `(current, target)` pairs and no others. Any move not listed here is
# rejected by `assert_transition`. A frozenset because the source of truth is
# immutable.
ALLOWED_TRANSITIONS: frozenset[tuple[ApplicationStatus, ApplicationStatus]] = frozenset(
    {
        (ApplicationStatus.DRAFT, ApplicationStatus.SUBMITTED),  # submit
        (ApplicationStatus.SUBMITTED, ApplicationStatus.APPROVED),  # carrier approve
        (ApplicationStatus.SUBMITTED, ApplicationStatus.DECLINED),  # carrier decline
        (ApplicationStatus.DECLINED, ApplicationStatus.SUPERSEDED),  # re-selection supersedes
    }
)


# The in-flight statuses (TDD §5.2 "Active"): an application at one of these is the
# opportunity's single live application — the set the "one active per opportunity"
# rule (C5) and its partial unique index key on. `Declined` is **not** active (it
# is retained read-only history awaiting supersession).
ACTIVE_STATUSES: frozenset[ApplicationStatus] = frozenset(
    {ApplicationStatus.DRAFT, ApplicationStatus.SUBMITTED}
)


# The terminal statuses — no outgoing moves (TDD §5.2). `Approved` ends the happy
# path; `Superseded` ends a declined application's life once a fresh one replaces
# it. `Declined` is deliberately absent — it still has the move to `Superseded`.
TERMINAL_STATUSES: frozenset[ApplicationStatus] = frozenset(
    {ApplicationStatus.APPROVED, ApplicationStatus.SUPERSEDED}
)


class InvalidApplicationTransition(Exception):
    """Raised when an application status move is not in `ALLOWED_TRANSITIONS`.

    Carries the attempted `current` and `target` statuses so the action epics can
    build a useful HTTP 409 message at the edge. Framework-free on purpose — the
    pure core never imports the web framework (mirrors `InvalidLeadTransition`).
    """

    def __init__(self, current: ApplicationStatus, target: ApplicationStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(
            f"Illegal application status transition: {current} -> {target}"
        )


def assert_transition(
    current: ApplicationStatus, target: ApplicationStatus
) -> None:
    """Allow a legal status move; raise `InvalidApplicationTransition` otherwise.

    Returns `None` when `(current, target)` is one of `ALLOWED_TRANSITIONS` (the
    caller proceeds). Raises `InvalidApplicationTransition` for every other move,
    including self-loops, backwards moves, exits from the terminal states, and
    multi-step skips. This is the single public guard for status changes; the
    action epics map the exception to HTTP 409.
    """
    if (current, target) not in ALLOWED_TRANSITIONS:
        raise InvalidApplicationTransition(current, target)
