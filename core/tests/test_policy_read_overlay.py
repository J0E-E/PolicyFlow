"""Unit tests for the `serialize_policy` *Renewal Due* overlay seam (P2.4 Epic 6).

`serialize_policy` is a pure function over a `Policy`'s attributes, so these tests need
no database — a lightweight stub carrying the read fields is enough. They pin the four
combinations of the overlay flag against the stored status (ADR 0005): the wire `status`
reads *Renewal Due* when the stored status already is, **or** when the overlay flag is
set (a baseline policy the caller's session has a renewal opportunity for); every other
field is unchanged regardless of the flag.
"""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from app.policies.read import serialize_policy


def _policy(status: str) -> SimpleNamespace:
    """Return a stub carrying exactly the attributes `serialize_policy` reads."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        opportunity_id=uuid.uuid4(),
        application_id=uuid.uuid4(),
        policy_number="MA-1001",
        status=status,
        carrier="Humana",
        product_label="Gold Plus HMO",
        coverage_amount=7500,
        premium_monthly=29,
        premium_annual=348,
        issued_at=datetime(2022, 3, 1, tzinfo=timezone.utc),
    )


def test_flag_off_stored_active_reads_active():
    """Baseline: no overlay, stored Active → Active."""
    assert serialize_policy(_policy("Active"))["status"] == "Active"


def test_flag_on_stored_active_reads_renewal_due():
    """Overlay flips a stored-Active (baseline) policy to Renewal Due at read."""
    assert (
        serialize_policy(_policy("Active"), overlay_renewal_due=True)["status"]
        == "Renewal Due"
    )


def test_flag_off_stored_renewal_due_reads_renewal_due():
    """A session-owned policy with the real Renewal Due status shows it without the flag."""
    assert (
        serialize_policy(_policy("Renewal Due"))["status"] == "Renewal Due"
    )


def test_flag_on_stored_renewal_due_reads_renewal_due():
    """Overlay and stored status agree — still Renewal Due."""
    assert (
        serialize_policy(_policy("Renewal Due"), overlay_renewal_due=True)["status"]
        == "Renewal Due"
    )


def test_overlay_leaves_every_other_field_unchanged():
    """The flag only touches `status`; all other wire fields are identical."""
    policy = _policy("Active")
    without = serialize_policy(policy)
    with_overlay = serialize_policy(policy, overlay_renewal_due=True)
    assert without["status"] == "Active"
    assert with_overlay["status"] == "Renewal Due"
    for field in without:
        if field != "status":
            assert without[field] == with_overlay[field]
