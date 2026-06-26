"""Unit test for the pipeline resolver — the tenant config → board columns map.

Pure logic, no DB / no Docker. The expected stage lists are hand-transcribed from
the TDD §5.2 demo-distinct config (D13), independently of the registry values, so
a drift in either the registry config or the resolver is caught here.
"""

from app.opportunities.pipeline import StageView, resolve_pipeline
from app.tenancy.registry import FLORIDA, SUNSHINE

# Sunshine runs the full spine (both optional stages on) with the Medicare relabels.
EXPECTED_SUNSHINE: list[tuple[str, str, bool]] = [
    ("New", "New", False),
    ("Qualified", "Needs Assessment", False),
    ("Quoted", "Quoted", True),
    ("Application Started", "Application Started", False),
    ("Submitted", "Submitted", False),
    ("Approved", "Approved", True),
    ("Policy Active", "Enrolled", False),
]

# Florida disables Approved (so Submitted is followed by Policy Active) and relabels
# Quoted + Application Started.
EXPECTED_FLORIDA: list[tuple[str, str, bool]] = [
    ("New", "New", False),
    ("Qualified", "Qualified", False),
    ("Quoted", "Proposal Sent", True),
    ("Application Started", "App In Progress", False),
    ("Submitted", "Submitted", False),
    ("Policy Active", "Policy Active", False),
]


def _as_tuples(views: list[StageView]) -> list[tuple[str, str, bool]]:
    return [(view.key, view.label, view.is_optional) for view in views]


def test_sunshine_resolves_the_full_relabeled_spine():
    """Sunshine shows all seven stages, in order, with its Medicare relabels."""
    assert _as_tuples(resolve_pipeline(SUNSHINE)) == EXPECTED_SUNSHINE


def test_florida_skips_disabled_approved_and_relabels():
    """Florida shows six stages — Approved omitted — with its relabels."""
    assert _as_tuples(resolve_pipeline(FLORIDA)) == EXPECTED_FLORIDA


def test_disabled_optional_stage_is_absent_from_the_columns():
    """A disabled optional stage never appears as a column (Florida's Approved)."""
    florida_keys = [view.key for view in resolve_pipeline(FLORIDA)]
    assert "Approved" not in florida_keys
    # Sunshine, with Approved enabled, does show it.
    sunshine_keys = [view.key for view in resolve_pipeline(SUNSHINE)]
    assert "Approved" in sunshine_keys


def test_only_optional_stages_are_flagged_is_optional():
    """`is_optional` is true exactly for the toggleable stages that are shown."""
    for tenant in (SUNSHINE, FLORIDA):
        optional_keys = {
            view.key for view in resolve_pipeline(tenant) if view.is_optional
        }
        assert optional_keys <= {"Quoted", "Approved"}, tenant.slug
