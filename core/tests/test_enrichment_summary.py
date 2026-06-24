"""Unit tests for the deterministic enrichment result summary (P1.9 Epic 3).

`enrichment_result_summary` is a **pure** function of the event id — the canned
quality score the enrichment stub writes onto its fresh ``processed_events`` row,
and the *same* derivation Epic 5's seed reuses by importing this function rather
than re-deriving the rule. These tests pin the three properties that guarantee make
that reuse safe:

- **Deterministic / stable** — the same ``event_id`` always yields the same string
  (across calls, and so across redeliveries and across the seed-vs-live split). The
  derivation hashes ``event_id.bytes`` with SHA-256, not the salted built-in
  ``hash()``, so it is also stable across processes.
- **Shape** — the frozen string is ``Quality score <N>/100 · <Band>`` with ``N`` in
  ``0..100`` and ``Band`` one of Low / Medium / High.
- **Banding boundaries** — Low ``0..59`` / Medium ``60..79`` / High ``80..100``.

Pure logic — no DB, no Docker, no async fixtures.
"""

import re
import uuid

from app.events.enrichment import (
    QUALITY_BAND_HIGH,
    QUALITY_BAND_LOW,
    QUALITY_BAND_MEDIUM,
    enrichment_result_summary,
    quality_band_for_score,
    quality_score_for_event,
)

# A fixed event id so the deterministic output is reproducible in assertions.
FIXED_EVENT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")

SUMMARY_PATTERN = re.compile(r"^Quality score (\d{1,3})/100 · (Low|Medium|High)$")


def test_summary_is_deterministic_across_calls():
    """The same event id yields the exact same summary every call (stable)."""
    first = enrichment_result_summary(FIXED_EVENT_ID)
    second = enrichment_result_summary(FIXED_EVENT_ID)
    assert first == second


def test_summary_matches_the_frozen_shape():
    """The summary reads ``Quality score <N>/100 · <Band>`` with N in 0..100."""
    summary = enrichment_result_summary(FIXED_EVENT_ID)
    match = SUMMARY_PATTERN.match(summary)
    assert match is not None, summary
    score = int(match.group(1))
    assert 0 <= score <= 100


def test_summary_band_agrees_with_its_score():
    """The band rendered in the string is the band the score derivation assigns."""
    summary = enrichment_result_summary(FIXED_EVENT_ID)
    match = SUMMARY_PATTERN.match(summary)
    assert match is not None, summary
    score = int(match.group(1))
    assert match.group(2) == quality_band_for_score(score)


def test_score_stays_in_range_for_many_ids():
    """Across many random event ids the score never leaves ``0..100``."""
    for _ in range(1000):
        score = quality_score_for_event(uuid.uuid4())
        assert 0 <= score <= 100


def test_band_boundaries():
    """Low covers 0..59, Medium 60..79, High 80..100 (the frozen bands)."""
    assert quality_band_for_score(0) == QUALITY_BAND_LOW
    assert quality_band_for_score(59) == QUALITY_BAND_LOW
    assert quality_band_for_score(60) == QUALITY_BAND_MEDIUM
    assert quality_band_for_score(79) == QUALITY_BAND_MEDIUM
    assert quality_band_for_score(80) == QUALITY_BAND_HIGH
    assert quality_band_for_score(100) == QUALITY_BAND_HIGH
