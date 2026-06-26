"""Unit test for the Medicare eligibility gate — the pure rule.

Pure logic, no DB / no Docker. Exercises `is_blocked_for_medicare` across the
gated/non-gated line and the eligible/under-65/missing age band, plus the error's
carried fields. The expected behavior is hand-written from the TDD §5 / D4 rule.
"""

import pytest

from app.opportunities.eligibility import (
    ELIGIBLE_AGE_BAND,
    MedicareEligibilityError,
    is_blocked_for_medicare,
)
from app.tenancy.registry import ProductLine

GATED_LINE = ProductLine(
    key="medicare_advantage", label="Medicare Advantage", requires_medicare_age=True
)
PLAIN_LINE = ProductLine(key="final_expense", label="Final Expense")


def test_eligible_age_band_is_sixty_five_plus():
    """The band that clears the gate is the designed `"65+"` Medicare signal."""
    assert ELIGIBLE_AGE_BAND == "65+"


def test_gated_line_under_65_is_blocked():
    """A Medicare-gated line with an under-65 contact is blocked."""
    assert is_blocked_for_medicare(GATED_LINE, "55-64") is True


def test_gated_line_at_65_plus_is_allowed():
    """A Medicare-gated line clears the gate at `"65+"`."""
    assert is_blocked_for_medicare(GATED_LINE, "65+") is False


def test_gated_line_with_missing_age_band_is_blocked():
    """A missing age band is treated as under-65 (fails closed) for a gated line."""
    assert is_blocked_for_medicare(GATED_LINE, None) is True


def test_non_gated_line_is_never_blocked():
    """A non-Medicare line never gates, even for an under-65 contact."""
    assert is_blocked_for_medicare(PLAIN_LINE, "55-64") is False
    assert is_blocked_for_medicare(PLAIN_LINE, None) is False


def test_error_carries_the_line_key_and_age_band():
    """`MedicareEligibilityError` exposes the line key and band for the 422 message."""
    error = MedicareEligibilityError("medicare_advantage", "55-64")
    assert error.product_line_key == "medicare_advantage"
    assert error.age_band == "55-64"
    assert "medicare_advantage" in str(error)


def test_error_is_a_plain_exception_not_an_http_error():
    """The error is framework-free — a plain `Exception` (mapped to 422 at the edge)."""
    assert issubclass(MedicareEligibilityError, Exception)
    with pytest.raises(MedicareEligibilityError):
        raise MedicareEligibilityError("medicare_supplement", None)
