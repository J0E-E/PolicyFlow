# ADR 0002 — Cross-sell prompt is a live coverage check, not an event-set flag

The Household cross-sell prompt is computed from current coverage at render time (≥1 active
policy and ≥1 uncovered tenant product line → one suggestion per uncovered line), applying to
seeded and session-created households alike. Chosen over the literal "on policy.created"
trigger (invisible on seeded data) and a persistent flag (goes stale); "policy created"
remains the conceptual trigger. Source: brd-P2.4 §6
