# ADR 0005 — The "Renewal Due" overlay is derived at read from the session's renewal opportunity

A baseline (seeded) policy shows *Renewal Due* only when the caller's session holds a renewal
opportunity for it (`source_policy_id` match), computed at read time — no stored flag, no overlay
table — so seeded rows stay byte-identical and the mechanism mirrors ADR 0002's live-check
philosophy. Session-created policies instead take a real, guarded `Active → Renewal Due` write.
Chosen over a session-scoped overlay table (new table + purge wiring) and over mutating seeded rows.
Source: tdd-P2.4 §6
