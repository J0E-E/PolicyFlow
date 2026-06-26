"""The Medicare eligibility gate — the pure rule plus its framework-free error.

A Medicare-gated product line (its `requires_medicare_age` flag, set in the
registry — Sunshine's `medicare_advantage` + `medicare_supplement`) may only enter
the *Quoted* stage for a customer who is **65 or older**. The age signal is the
contact's plaintext `age_band` — `"65+"` is the designed Medicare marker — so the
check reads it directly, **never decrypting** the date of birth. The enrichment
flag is **never** consulted; eligibility is decided by the stored age band alone.

This module is **pure logic — no database, no I/O, no framework.** The stage
endpoint maps `MedicareEligibilityError` to HTTP 422 (a precondition-failed, kept
distinct from the 409 of a structurally-invalid move). `is_blocked_for_medicare`
is the single rule the stage action calls now and the P2.3 quote-request path
reuses later.
"""

from ..tenancy.registry import ProductLine

# The age band that clears the Medicare gate — the designed `age_band_for` signal
# for "65 or older". Any other band (or a missing one) is under-65 for the gate.
ELIGIBLE_AGE_BAND = "65+"


class MedicareEligibilityError(Exception):
    """Raised when a Medicare-gated move to *Quoted* is blocked for an under-65 contact.

    Carries the offending `product_line_key` and the contact's `age_band` so the
    stage endpoint can build a clear HTTP 422 message. Framework-free on purpose —
    the pure core never imports the web framework (mirrors `InvalidStageTransition`).
    """

    def __init__(self, product_line_key: str, age_band: str | None) -> None:
        self.product_line_key = product_line_key
        self.age_band = age_band
        super().__init__(
            f"Medicare-gated product line '{product_line_key}' cannot be quoted "
            f"for a customer under 65 (age band: {age_band})"
        )


def is_blocked_for_medicare(
    product_line: ProductLine, age_band: str | None
) -> bool:
    """Return True when this product line is Medicare-gated and the contact is under 65.

    The gate fires only for a `requires_medicare_age` line whose contact's
    `age_band` is not the eligible `"65+"` band. A non-Medicare line is never
    blocked; a `"65+"` contact is always eligible. Pure — no decryption, no
    enrichment-flag read.
    """
    return product_line.requires_medicare_age and age_band != ELIGIBLE_AGE_BAND
