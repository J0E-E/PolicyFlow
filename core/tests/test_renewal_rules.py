"""Unit tests for the pure renewal predicates (`app.renewals.rules`).

Pure unit tests — no DB, no Docker, no clock: every function takes its dates as
arguments, so each assertion passes fixed dates and pins an exact boundary. Covers
the AEP window edges (Oct 15 / Dec 7 inclusive, and just outside), the rolling
anniversary check (exactly 60 days, just over, same-day, the year rollover, and the
Feb-29 leap case), the renewal deadline per rule, and the cycle-key format.
"""

from datetime import date

import pytest

from app.renewals.rules import (
    anniversary_within,
    in_aep_window,
    next_anniversary,
    renewal_cycle_key,
    renewal_deadline,
)


# --- in_aep_window: Oct 15 <= today <= Dec 7 inclusive, year-agnostic ----------

def test_aep_window_includes_the_october_15_start_boundary():
    """October 15 is inside the window (inclusive start)."""
    assert in_aep_window(date(2026, 10, 15)) is True


def test_aep_window_includes_the_december_7_end_boundary():
    """December 7 is inside the window (inclusive end)."""
    assert in_aep_window(date(2026, 12, 7)) is True


def test_aep_window_includes_a_mid_window_date():
    """A date squarely inside the window is included."""
    assert in_aep_window(date(2026, 11, 1)) is True


def test_aep_window_excludes_the_day_before_the_start():
    """October 14 is one day before the window and excluded."""
    assert in_aep_window(date(2026, 10, 14)) is False


def test_aep_window_excludes_the_day_after_the_end():
    """December 8 is one day after the window and excluded."""
    assert in_aep_window(date(2026, 12, 8)) is False


def test_aep_window_excludes_a_date_well_outside():
    """A date far from the window (mid-July) is excluded."""
    assert in_aep_window(date(2026, 7, 18)) is False


def test_aep_window_is_year_agnostic():
    """The same month/day gives the same verdict regardless of year."""
    assert in_aep_window(date(2020, 11, 20)) is True
    assert in_aep_window(date(2099, 11, 20)) is True


# --- anniversary_within: next anniversary on/after today is <= days away --------

def test_anniversary_at_exactly_sixty_days_is_within():
    """An anniversary exactly `days` away is included (inclusive boundary)."""
    today = date(2026, 1, 1)  # 60 days later is March 2 in a non-leap year.
    assert anniversary_within(date(2019, 3, 2), today, days=60) is True


def test_anniversary_one_day_over_sixty_is_not_within():
    """An anniversary one day past `days` is excluded."""
    today = date(2026, 1, 1)  # March 3 is 61 days away.
    assert anniversary_within(date(2019, 3, 3), today, days=60) is False


def test_anniversary_today_itself_is_within():
    """A policy whose anniversary is today is zero days away and included."""
    today = date(2026, 6, 15)
    assert anniversary_within(date(2010, 6, 15), today, days=60) is True


def test_anniversary_uses_next_year_when_this_years_has_passed():
    """When this year's anniversary is already behind today, the next one counts."""
    today = date(2026, 12, 1)  # This year's Jan 15 has passed; next is 45 days off.
    assert anniversary_within(date(2020, 1, 15), today, days=60) is True
    assert anniversary_within(date(2020, 1, 15), today, days=44) is False


def test_anniversary_far_off_is_not_within():
    """An anniversary months away is excluded under the default 60-day window."""
    today = date(2026, 1, 1)
    assert anniversary_within(date(2015, 8, 20), today) is False


def test_feb_29_issue_date_observes_february_28_in_a_non_leap_year():
    """A Feb-29 issue date falls on Feb 28 in a non-leap year (8 days from Feb 20)."""
    issued_at = date(2024, 2, 29)  # A leap-year issue date.
    today = date(2026, 2, 20)  # 2026 is not a leap year.
    assert anniversary_within(issued_at, today, days=8) is True
    assert anniversary_within(issued_at, today, days=7) is False


# --- next_anniversary: the upcoming anniversary date on/after today -------------

def test_next_anniversary_is_this_years_when_still_ahead():
    """This year's anniversary is returned when it has not yet passed."""
    assert next_anniversary(date(2019, 3, 2), date(2026, 1, 1)) == date(2026, 3, 2)


def test_next_anniversary_is_today_when_the_anniversary_is_today():
    """A policy whose anniversary is today returns today (zero days away)."""
    assert next_anniversary(date(2010, 6, 15), date(2026, 6, 15)) == date(2026, 6, 15)


def test_next_anniversary_rolls_to_next_year_when_this_years_has_passed():
    """When this year's anniversary is behind today, next year's is returned."""
    assert next_anniversary(date(2020, 1, 15), date(2026, 12, 1)) == date(2027, 1, 15)


def test_next_anniversary_of_feb_29_is_february_28_in_a_non_leap_year():
    """A Feb-29 issue date observes its anniversary on Feb 28 in a non-leap year."""
    assert next_anniversary(date(2024, 2, 29), date(2026, 2, 20)) == date(2026, 2, 28)


# --- renewal_deadline: AEP -> Dec 7 of cycle year; anniversary -> the date ------

def test_renewal_deadline_for_aep_is_december_7_of_the_cycle_year():
    """An AEP renewal is due by December 7 of its cycle year."""
    assert renewal_deadline("aep", 2026, date(2000, 1, 1)) == date(2026, 12, 7)


def test_renewal_deadline_for_anniversary_is_the_anniversary_date():
    """An anniversary renewal is due on the policy's anniversary date."""
    anniversary = date(2026, 4, 30)
    assert renewal_deadline("anniversary", 2026, anniversary) == anniversary


def test_renewal_deadline_rejects_an_unknown_rule():
    """A rule with no deadline (e.g. `none`) raises rather than guessing."""
    with pytest.raises(ValueError):
        renewal_deadline("none", 2026, date(2026, 4, 30))


# --- renewal_cycle_key: aep-<year> / anniv-<year> -------------------------------

def test_renewal_cycle_key_for_aep_is_prefixed_and_year_stamped():
    """The AEP cycle key is `aep-<year>`."""
    assert renewal_cycle_key("aep", 2026) == "aep-2026"


def test_renewal_cycle_key_for_anniversary_is_prefixed_and_year_stamped():
    """The anniversary cycle key is `anniv-<year>`."""
    assert renewal_cycle_key("anniversary", 2026) == "anniv-2026"


def test_renewal_cycle_key_rejects_an_unknown_rule():
    """A rule with no cycle (e.g. `none`) raises rather than guessing."""
    with pytest.raises(ValueError):
        renewal_cycle_key("none", 2026)
