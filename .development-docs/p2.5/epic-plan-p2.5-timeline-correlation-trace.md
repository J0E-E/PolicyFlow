# Timeline + Correlation Trace Extension — Epic Plan

Source TDD: [./tdd-p2.5-timeline-correlation-trace.md](./tdd-p2.5-timeline-correlation-trace.md)

> **Review budget:** ~300 changed lines · ~16 non-generated files · one focused commit per epic. Tunable per project. **Automated mode targets ~half:** ~150 changed lines · ~8 non-generated files, one concern per epic.

> **Build strategy:** Tracer bullet — copied from the TDD; shapes the epic breakdown only, never phase order inside an epic (`0-conventions.md` → *Build strategies*).

> **Execution mode:** Automated — chosen at plan creation; grilled to zero here, tighter epics, ready for unattended runs (`0-conventions.md` → *Execution modes*).

> **QA checklists:** None — chosen at plan creation; ships a flat epic list with no section headings (`0-conventions.md` → *Sections & QA epics*).

> High-level agile roadmap. Every design decision was settled at plan creation (TDD §6, D1–D10, ADRs 0007/0008); `4-plan-epic` verifies zero open questions remain before any code is written.

## Epic 1 — Generalize the timeline read into a shared module

- **Goal:** Move the P1.9 lead-timeline read into a shared, entity-agnostic module so opportunity, policy, and trace reads can all reuse one derivation. Lead timeline behaves identically after the move.
- **Rough scope:** Move `app/leads/timeline.py` → `app/events/timeline.py` as `get_timeline_rows(db, entity_id)` (query + reaction-merge + status derivation unchanged, D2); re-point the lead route at it. Backend only, no new surface — a refactor the rest of the plan builds on. Lead-timeline regression test guards the move.
- **Open questions / decisions for stakeholders:** none — resolved at plan time.
- **Depends on:** none.
- **Implementation notes:** _none yet_

## Epic 2 — Opportunity detail per-record timeline [UI]

- **Goal:** Opportunity detail shows a live-updating per-record event timeline — the first customer-visible tracer slice. Quote-driven `stage_changed` events keep it moving during quoting.
- **Rough scope:** `GET /api/opportunities/{id}/timeline` (loads + guards the opportunity by existing visibility rules, calls the shared module); a continuous-polling timeline component on `OpportunityDetailPage` derived from `LeadTimeline` (no idle-stop, D8); `getOpportunityTimeline` client method. Strict `entity_id` keying — only the opportunity's own events (D2).
- **Open questions / decisions for stakeholders:** none — resolved at plan time.
- **Depends on:** Epic 1.
- **Implementation notes:** _none yet_

## Epic 3 — Policy detail page + policy read [UI]

- **Goal:** Give a policy a real detail page (none exists today — a policy only renders as an embedded `PolicySummary` card). Stands up the route and read; timeline lands in Epic 4.
- **Rough scope:** `GET /api/policies/{id}` (guarded read); new `PolicyDetailPage` at `/app/policies/:id` rendering `PolicySummary`; route wired in `App.tsx`; `PolicySummary` cards link to it; `getPolicy` client method (D1).
- **Open questions / decisions for stakeholders:** none — resolved at plan time.
- **Depends on:** none.
- **Implementation notes:** _none yet_

## Epic 4 — Policy detail per-record timeline [UI]

- **Goal:** The policy detail page shows a live-updating per-record event timeline, matching the opportunity surface.
- **Rough scope:** `GET /api/policies/{id}/timeline` (guard + shared module); mount the Epic 2 continuous-polling timeline component on `PolicyDetailPage`; `getPolicyTimeline` client method.
- **Open questions / decisions for stakeholders:** none — resolved at plan time.
- **Depends on:** Epic 1, Epic 2, Epic 3.
- **Implementation notes:** _none yet_

## Epic 5 — Trace read endpoint

- **Goal:** One journey's end-to-end story, server-side: ordered, entity-tagged event rows sharing a `correlation_id`, session-scoped. Core rows only — renewal links land in Epic 8.
- **Rough scope:** New `app/trace/router.py` — `GET /api/trace/{correlation_id}`: outbox rows `WHERE correlation_id = :cid AND (demo_session_id IS NULL OR = :session)`, oldest-first (`occurred_at, id`), reactions synthesized as in the shared read; each event row gains `entity_type` (from the known event-type prefix table; unknown → generic label) + `entity_id` (payload). Unknown/foreign id → empty rows, not 404 (D3). `getTrace` client method. Cross-session isolation tested here.
- **Open questions / decisions for stakeholders:** none — resolved at plan time.
- **Depends on:** Epic 1.
- **Implementation notes:** _none yet_

## Epic 6 — Trace page: flat chronological stream [UI]

- **Goal:** The correlation-trace view — a flat, ordered, entity-tagged story of one journey on a bare page, polling live. Real rows rendering is the tracer for the centerpiece surface.
- **Rough scope:** `TracePage` at `/app/trace/:correlationId`; §6.11 ink console; §6.1 row anatomy + entity-type chip per row; prominent mono `correlation_id` header; "Simulated" badges; one explainer; continuous poll (D4/D8). No renewal-link rows yet.
- **Open questions / decisions for stakeholders:** none — resolved at plan time.
- **Depends on:** Epic 5.
- **Implementation notes:** _none yet_

## Epic 7 — "View full trace" links on per-record timelines [UI]

- **Goal:** One click from any per-record timeline to that record's full trace.
- **Rough scope:** Add a "view full trace" link built from the record's `correlation_id` (already present on every timeline row) to the lead, opportunity, and policy timelines.
- **Open questions / decisions for stakeholders:** none — resolved at plan time.
- **Depends on:** Epic 2, Epic 4, Epic 6.
- **Implementation notes:** _none yet_

## Epic 8 — Renewal ↔ origin trace links [UI]

- **Goal:** An original journey's trace links out to its renewal's trace, and the renewal's trace links back — bidirectional, derived server-side.
- **Rough scope:** In the trace response, derive `origin_trace` / `renewal_traces` from `opportunity.source_policy_id` (origin → renewal: opportunities whose `source_policy_id` ∈ the trace's `policy.created` ids → their `correlation_id`s; renewal → origin: the trace opportunity's `source_policy_id` → that policy's `correlation_id`), session-scoped in the same query (D5); render link rows on `TracePage`.
- **Open questions / decisions for stakeholders:** none — resolved at plan time.
- **Depends on:** Epic 5, Epic 6.
- **Implementation notes:** _none yet_

## Epic 9 — Seed: unify baseline chains onto one correlation per journey

- **Goal:** Each baseline money-path journey carries one `correlation_id` end-to-end, mirroring live conversion (which already propagates the lead's id through every downstream entity).
- **Rough scope:** Drop `chain_correlation_id`; baseline chains reuse `conversion_correlation_id` (D6, ADR 0008). Count-based idempotency keys unchanged; takes effect on fresh reseed. Seed tests extended with a correlation-unification assertion. No trail synthesis yet.
- **Open questions / decisions for stakeholders:** none — resolved at plan time.
- **Depends on:** none.
- **Implementation notes:** _none yet_

## Epic 10 — Seed: synthesize full plausible per-journey event trails

- **Goal:** Baseline journeys are indistinguishable in shape from live emission — their opportunity/policy timelines and journey traces populate on reseed, never empty.
- **Rough scope:** Synthesize the full outbox + `processed_events` trail per baseline journey (lead trail created→assigned→qualified→converted; conversion events household/contact/opportunity created; per-chain quote.requested/completed + stage changes + application started/submitted/approved + policy.created), payloads identical to the live writers, catalog reactions all `done` (`published_at` set), timestamps backdated and spread lead-date → issue-date, count-based idempotent (D7, ADR 0007). Seed tests extended with trail shape + idempotency assertions.
- **Open questions / decisions for stakeholders:** none — resolved at plan time.
- **Depends on:** Epic 9.
- **Implementation notes:** _none yet_

## Epic 11 — Stepper deep-link to the baseline trace [UI]

- **Goal:** Walkthrough step 20 deep-links to the fully-populated baseline journey's trace — delivering the phase's shippable acceptance.
- **Rough scope:** Baseline-trace resolver (`GET /api/trace/baseline`, returns the tenant's seeded journey correlation id; if ever more than one, oldest) + `getBaselineTrace` client method; optional `link` field on `stepperSteps.ts` entries rendered by `GuidedDocket` (steps were prose-only); step 20 → `/app/trace/baseline` (the `baseline` alias resolves then substitutes on `TracePage`) (D9).
- **Open questions / decisions for stakeholders:** none — resolved at plan time.
- **Depends on:** Epic 6, Epic 10.
- **Implementation notes:** _none yet_

## Epic 12 — Acceptance hardening: end-to-end + cross-session isolation

- **Goal:** The five BRD acceptance criteria hold end-to-end across the surfaces built above, and no trace surface leaks cross-session rows.
- **Rough scope:** Integration tests spanning the surfaces — live opportunity/policy timelines during a quote; the signature live-growing trace (drive convert → quote → bind, events append through the final sync reaction); one-click trace from lead/opportunity/policy; bidirectional renewal links; fresh-reseed populated baseline timelines + traces — plus a cross-session isolation sweep confirming a second demo session sees no cross-session rows on the trace surfaces. Per-slice unit/isolation tests already ship with their epics; this is the cross-surface end-to-end pass.
- **Open questions / decisions for stakeholders:** none — resolved at plan time.
- **Depends on:** Epic 1, Epic 2, Epic 3, Epic 4, Epic 5, Epic 6, Epic 7, Epic 8, Epic 9, Epic 10, Epic 11.
- **Implementation notes:** _none yet_
