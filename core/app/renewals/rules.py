"""Pure renewal predicates — clock-free and DB-free (P2.4 / TDD §5.1).

Every function here takes the dates it needs as arguments and returns a plain
value: none of them read the wall clock or touch the database. That keeps them
trivially unit-testable at every boundary and lets the generation core (Epic 4)
own the single call to the real clock, passing `today` down. The `renewal_rule`
strings (`"aep"`, `"anniversary"`, `"none"`) are the ones classified on each
`ProductLine` in the tenant registry (ADR 0003).
"""

from datetime import date

# The Medicare Annual Enrollment Period, as month/day boundaries (year-agnostic):
# October 15 through December 7, both inclusive. Held as `(month, day)` tuples so
# the window check is a pure ordering comparison independent of the year.
AEP_WINDOW_START = (10, 15)
AEP_WINDOW_END = (12, 7)


def in_aep_window(today: date) -> bool:
    """Return whether ``today`` falls inside the Medicare AEP window.

    The window is October 15 through December 7 inclusive, compared on month and
    day only so it holds in any year (ADR 0004's on-demand sweep bypasses this
    gate, but the seasonal rule is defined here).
    """
    return AEP_WINDOW_START <= (today.month, today.day) <= AEP_WINDOW_END


def next_anniversary(issued_at: date, today: date) -> date:
    """Return the next yearly anniversary of ``issued_at`` on or after ``today``.

    Starts from this year's anniversary and rolls to next year's when this year's
    has already passed, so the result is always the upcoming (or today's)
    anniversary. The generation core (Epic 4) needs this concrete date for two
    things: the anniversary renewal's deadline (`renewal_deadline`) and its cycle
    year (`renewal_cycle_key`). Kept here beside `anniversary_within`, which shares
    it, so the Feb-29 leap rule lives in exactly one place.
    """
    anniversary = _anniversary_in_year(issued_at, today.year)
    if anniversary < today:
        anniversary = _anniversary_in_year(issued_at, today.year + 1)
    return anniversary


def anniversary_within(issued_at: date, today: date, days: int = 60) -> bool:
    """Return whether the next yearly anniversary of ``issued_at`` is near.

    "Near" means the next anniversary on or after ``today`` is at most ``days``
    away (default 60). A policy issued exactly ``days`` from now is included;
    one issued a day further out is not.
    """
    return (next_anniversary(issued_at, today) - today).days <= days


def _anniversary_in_year(issued_at: date, year: int) -> date:
    """Return ``issued_at``'s anniversary in ``year``.

    A February 29 issue date has no anniversary in a non-leap year; we observe it
    on February 28 that year (the last day of the month, rather than slipping into
    March), so the anniversary sweep still fires once every year.
    """
    try:
        return date(year, issued_at.month, issued_at.day)
    except ValueError:
        return date(year, 2, 28)


def renewal_deadline(rule: str, cycle_year: int, anniversary_date: date) -> date:
    """Return the target close date for a renewal opportunity under ``rule``.

    An AEP renewal is due by December 7 of its ``cycle_year``; an anniversary
    renewal is due on the policy's ``anniversary_date``. Any other rule raises
    ``ValueError`` — only the two renewing rules have a deadline.
    """
    if rule == "aep":
        return date(cycle_year, 12, 7)
    if rule == "anniversary":
        return anniversary_date
    raise ValueError(f"no renewal deadline for rule {rule!r}")


def renewal_cycle_key(rule: str, year: int) -> str:
    """Return the idempotency cycle key for ``rule`` in ``year``.

    The key uniquely names one renewal cycle so a re-run generates nothing new
    (ADR 0001): ``"aep-<year>"`` for the AEP sweep, ``"anniv-<year>"`` for the
    anniversary sweep. Any other rule raises ``ValueError``.
    """
    if rule == "aep":
        return f"aep-{year}"
    if rule == "anniversary":
        return f"anniv-{year}"
    raise ValueError(f"no renewal cycle key for rule {rule!r}")
