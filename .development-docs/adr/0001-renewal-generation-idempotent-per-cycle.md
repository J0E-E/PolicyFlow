# ADR 0001 — Renewal generation is idempotent: one Renewal Opportunity per policy per cycle

A renewal sweep (AEP or anniversary) creates at most one Renewal Opportunity per policy per
renewal cycle; re-runs skip already-covered policies (even if the earlier renewal was closed
or lost) and report generated/skipped counts. Chosen over always-generate (duplicate clutter,
misrepresents real CRM jobs) and regenerate-after-close (edge-case loops).
Source: brd-P2.4 §6, §9
