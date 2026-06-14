# Deferred Features Backlog

Items surfaced during the build that are **needed but out of the current epic's
scope**. Each earns its own requirements → TDD → epic plan when it reaches the
front of the queue. Add a one-line entry; link the source TDD.

| # | Item | Why / source | Owning phase (proposed) |
|---|---|---|---|
| 1 | **Explainer content: audit store topology + append-only/atomicity tradeoffs** — teach *why* audit is split into a per-tenant store and a platform store (isolation inherited; tenant audit can't leak cross-tenant) and *why* writes are append-only via a dedicated `audit_writer` role on a separate session (physical immutability; the deliberate non-atomicity tradeoff vs the P1.5 outbox that makes the **event** twin exactly-once). | Requested at P1.4 gate; see [p1.4/tdd-P1.4-audit-logging.md](./p1.4/tdd-P1.4-audit-logging.md) §6 (Decisions 1–2 + showcase callout). | P1.6 explainer shells → M4 (P4.5) content |
