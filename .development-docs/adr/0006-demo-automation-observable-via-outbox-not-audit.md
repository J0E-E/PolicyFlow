# ADR 0006 — Platform-Admin demo automation is observable via the outbox event trail, not an audit record

The renewal sweeps (P2.4 Epics 6/8), task completion (Epic 10), and cross-sell accept (Epic 13)
are Platform-Admin / agent demo mutations that write **no** P1.4 audit record; their observability
is the transactional outbox event trail each already emits (e.g. a renewal emits `opportunity.created`
+ `policy.renewal_due`). This mirrors the sibling `reset_demo_session`, which writes no audit either,
and matches P1.4's scope — audit records target cross-tenant reads and sensitive PII/security actions,
not session-scoped demo automation. Chosen over adding a `renewal.sweep` (and peer) audit vocabulary,
which would add scope with no consumer this phase; a later observability epic can add it if the demo
ever needs an admin action log.
Source: tdd-P2.4 §5.7, epic-plan-P2.4 Epic 6
