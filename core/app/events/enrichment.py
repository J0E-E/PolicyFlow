"""The enrichment stub's deterministic result summary — a pure, shared function.

The ``enrichment.stub`` consumer writes a one-line ``result_summary`` onto its
fresh ``processed_events`` row (P1.9 Epic 3): a canned quality score that the
per-record event timeline renders under the reaction. It is a **placeholder** for
the real enrichment output M3 swaps in (the stubs are terminal — Decision 8).

The score is **deterministic from the event id alone**, so a redelivery of the
same event yields the same summary, and — crucially — Epic 5's seed can synthesise
the *same* score a live delivery would produce by importing this one function
rather than re-deriving the rule. That is why this lives in its own pure module
with **no database, no I/O**: both the consumer write-path and the seed reach it.

The derivation hashes ``event_id.bytes`` with SHA-256 (a stable, process-independent
hash — unlike the salted built-in ``hash()``), reduces it to a score in ``0..100``,
and bands it Low / Medium / High. The string shape is frozen by the plan:
``Quality score <N>/100 · <Band>``.
"""

import hashlib
import uuid

__all__ = [
    "QUALITY_BAND_LOW",
    "QUALITY_BAND_MEDIUM",
    "QUALITY_BAND_HIGH",
    "quality_score_for_event",
    "quality_band_for_score",
    "enrichment_result_summary",
]

# The three quality bands the score maps onto (frozen by the plan).
QUALITY_BAND_LOW = "Low"
QUALITY_BAND_MEDIUM = "Medium"
QUALITY_BAND_HIGH = "High"


def quality_score_for_event(event_id: uuid.UUID) -> int:
    """Return a deterministic quality score in ``0..100`` for one event id.

    Hashes the event id's raw 16 bytes with SHA-256 and reduces the digest to an
    integer in ``0..100`` inclusive (mod 101). SHA-256 is used rather than Python's
    built-in ``hash()`` because the built-in is salted per process for ``bytes`` —
    the same event would score differently across runs, breaking the "stable across
    redeliveries" and "seed matches live" guarantees. ``event_id.bytes`` is the
    canonical 16-byte form, so the score never depends on string formatting.
    """
    digest = hashlib.sha256(event_id.bytes).digest()
    return int.from_bytes(digest, "big") % 101


def quality_band_for_score(score: int) -> str:
    """Band a ``0..100`` quality score Low / Medium / High.

    Low covers ``0..59``, Medium ``60..79``, High ``80..100`` (frozen by the plan).
    """
    if score < 60:
        return QUALITY_BAND_LOW
    if score < 80:
        return QUALITY_BAND_MEDIUM
    return QUALITY_BAND_HIGH


def enrichment_result_summary(event_id: uuid.UUID) -> str:
    """Return the enrichment stub's one-line result summary for one event id.

    The frozen string shape ``Quality score <N>/100 · <Band>`` — a deterministic
    canned quality score (`quality_score_for_event`) and its band
    (`quality_band_for_score`). Pure: the same ``event_id`` always yields the same
    string, so a redelivery and Epic 5's seed both reproduce it exactly.
    """
    score = quality_score_for_event(event_id)
    band = quality_band_for_score(score)
    return f"Quality score {score}/100 · {band}"
