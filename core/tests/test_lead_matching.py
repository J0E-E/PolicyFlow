"""True unit tests for the duplicate matcher (`app.leads.matching`).

These are **pure unit tests with no database**. The matcher has two collaborators:
the PII service seam `compute_blind_index` and the session's `execute`. Both are
stubbed here (monkeypatched as imported into `app.leads.matching`, and a hand-built
fake session) — mirroring how `test_lead_masking.py` stubs `decrypt_field` — so each
test runs without Docker, keys, or crypto.

What these prove is the matcher's **own half**: that each value is **normalized
before** it is fingerprinted (the normalize → blind-index step), that the row the
session returns surfaces as the match, and that an empty result returns `None`. The
end-to-end semantics on real Postgres (OR / oldest-wins / self-exclusion / Rejected
excluded / tenant isolation / no decryption) are `test_lead_matching_db.py`'s job.

`pytest.ini` sets `asyncio_mode = auto`, so the async tests carry no
`@pytest.mark.asyncio` decorator.
"""

import uuid

import pytest

from app.leads import matching as matching_module
from app.leads.matching import find_duplicate_lead

TENANT_ID = uuid.uuid4()

# Inputs written in a deliberately un-normalized style — mixed case and surrounding
# whitespace on the email, punctuated phone — so the assertion that the matcher
# normalizes before fingerprinting is a genuine cross-check, not a tautology.
RAW_EMAIL = "  Jane.Doe@Example.COM  "
RAW_PHONE = "+1 (555) 867-5309"
NORMALIZED_EMAIL = "jane.doe@example.com"
NORMALIZED_PHONE = "15558675309"


class FakeScalarResult:
    """The thin slice of a SQLAlchemy `Result` the matcher reaches for.

    The matcher calls `(await db.execute(query)).scalars().first()`, so the fake
    result only needs `scalars()` (returning itself) and `first()` (returning the
    single pre-set row or `None`). It records nothing — it is just a canned answer.
    """

    def __init__(self, row):
        self._row = row

    def scalars(self):
        return self

    def first(self):
        return self._row


class FakeSession:
    """A stand-in `AsyncSession` that returns a canned row and records the query.

    `execute` is awaitable (the matcher awaits it), returns a `FakeScalarResult`
    wrapping the pre-set row, and stashes the query it was handed so a test can
    confirm a query was actually built and run. No real database is touched.
    """

    def __init__(self, row):
        self._row = row
        self.executed_query = None

    async def execute(self, query):
        self.executed_query = query
        return FakeScalarResult(self._row)


@pytest.fixture
def captured_blind_index_inputs(monkeypatch):
    """Stub `compute_blind_index` as imported into `app.leads.matching`.

    The matcher calls `compute_blind_index` through its own module-level name, so
    the stub is patched onto `app.leads.matching` (the binding it actually uses),
    not `app.pii.service`. Each call records the `(tenant_id, normalized_value)` it
    was handed and returns a distinct sentinel fingerprint, so a test can assert the
    value was already normalized by the time it reached the fingerprinting step.
    """
    recorded_calls: list[tuple[uuid.UUID, str]] = []

    async def fake_compute_blind_index(tenant_id: uuid.UUID, normalized_value: str):
        recorded_calls.append((tenant_id, normalized_value))
        return f"blind-index::{normalized_value}".encode("utf-8")

    monkeypatch.setattr(
        matching_module, "compute_blind_index", fake_compute_blind_index
    )
    return recorded_calls


async def test_inputs_are_normalized_before_fingerprinting(
    captured_blind_index_inputs,
):
    """Email and phone are normalized before `compute_blind_index` ever sees them."""
    await find_duplicate_lead(
        FakeSession(row=None), TENANT_ID, RAW_EMAIL, RAW_PHONE
    )

    # One call per field, each carrying this tenant id and the **normalized** value
    # (trim + lowercase email; digits-only phone) — proving the normalize step runs
    # before the fingerprinting step.
    normalized_values_by_tenant = set(captured_blind_index_inputs)
    assert normalized_values_by_tenant == {
        (TENANT_ID, NORMALIZED_EMAIL),
        (TENANT_ID, NORMALIZED_PHONE),
    }


async def test_returned_row_surfaces_as_the_match(captured_blind_index_inputs):
    """The row the session returns is handed straight back as the match."""
    prior_lead = object()

    match = await find_duplicate_lead(
        FakeSession(row=prior_lead), TENANT_ID, RAW_EMAIL, RAW_PHONE
    )

    assert match is prior_lead


async def test_empty_result_returns_none(captured_blind_index_inputs):
    """An empty result (no matching prior lead) returns `None`, not an error."""
    match = await find_duplicate_lead(
        FakeSession(row=None), TENANT_ID, RAW_EMAIL, RAW_PHONE
    )

    assert match is None
