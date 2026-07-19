# P2.5 — Timeline + Correlation Trace Extension — Technical Design Document

> **Build strategy:** Tracer bullet — chosen at design time (rationale in §6, D9);
> `3-tdd-to-epic-plan` slices the epics by it and copies it to the epic-plan header
> (`0-conventions.md` → *Build strategies*).

## 1. Summary

Extend the P1.9 per-record event timeline to opportunity and policy detail views, and add
a correlation-trace view that renders one journey's end-to-end story (lead →
contact/household → opportunity → quote → application → policy) from the events sharing
its `correlation_id` — live-updating, reachable from every per-record timeline and the
walkthrough stepper, with bidirectional links between an original journey's trace and its
renewal's. Read/UI only: no new event emission; the one write-side change is the seed,
which gains full plausible event history for baseline journeys (ADR 0007) on a single
per-journey correlation id (ADR 0008). Delivers walkthrough step 20.

## 2. Business Requirements

Source: [./brd-P2.5-timeline-correlation-trace.md](./brd-P2.5-timeline-correlation-trace.md)
— read as the agreed requirements; not re-narrated. Constraints/clarifications surfaced
during this design:

- **No policy detail view exists.** No `/policies/:id` route; a policy renders only as an
  embedded `PolicySummary` card on opportunity and household detail. "Policy detail view"
  therefore has to be built (§6 D1).
- **Renewals do not share the origin's `correlation_id`.** The sweep mints a fresh one
  with `causation_id=None`; parentage is the `opportunity.source_policy_id` row fact
  (`renewals/service.py`). The BRD's "renewals carry causal parentage" assumption holds
  via that column, not the envelope.
- **The baseline seed contradicts live correlation flow.** Live conversion propagates the
  lead's `correlation_id` through every downstream entity; the baseline money-path seed
  gives each opp→app→policy chain its own fresh id (`seed.py` `chain_correlation_id`) —
  and seeds **zero** outbox rows for those chains (P1.9 trails covered only the
  standalone historical leads).
- **Stepper steps carry no links.** `stepperSteps.ts` entries are prose-only
  (`number`/`title`/`seeing`/`built`); a deep-link needs a new optional field plus docket
  rendering.
- **No migration needed.** The tenant role already holds `SELECT` on `outbox` (P1.9
  migration `0014`) and `processed_events` (`0008`); the trace and generalized timeline
  reads reuse those grants. No schema change anywhere in this phase.

## 3. Goals / Non-Goals

**Goals**
- Live per-record timelines (P1.9 behavior: chronology, relative timestamps, reaction
  status, result summaries, "Simulated" badges, one explainer) on opportunity detail and
  a new policy detail page.
- A correlation-trace view: flat, ordered, entity-tagged story of one journey, polling
  live, prominent mono `correlation_id`, per UI guide §6.11.
- "View full trace" links on lead/opportunity/policy timelines; walkthrough step 20
  deep-link to the baseline journey's trace.
- Bidirectional origin ↔ renewal trace links.
- Baseline journeys fully populated: seeded plausible history, one correlation per
  journey, indistinguishable in shape from live emission.

**Non-Goals**
- No per-record timelines on quotes/applications (their events appear only in the trace).
- No standalone journey-list page; no push transport (polling only); no new event
  emission or payload change to P2.1–P2.4 emitters; no Notification/Metrics reactions
  (M3/M4); no change to the lead timeline's existing idle-stop polling.

## 4. Current State

- **Timeline read.** [core/app/leads/timeline.py](../../core/app/leads/timeline.py) —
  `get_lead_timeline_rows` filters outbox on `payload->>'entity_id'` **alone** (P1.9 §5
  amendment), synthesizes expected reactions from `consumers_for_event_type`, derives
  status (`pending`/`processing`/`done`) from `published_at` + `processed_events`. The
  query is already entity-agnostic; only the route's guard is lead-specific
  ([core/app/leads/router.py](../../core/app/leads/router.py)).
- **Event vocabulary.** [core/app/events/catalog.py](../../core/app/events/catalog.py) —
  lead/contact/household/opportunity/quote/application/policy event types; consumers:
  `enrichment.stub` (`lead.created`, `record.created`), quote stub (`quote.requested`),
  `sync.logger` (`#`).
- **Payload keying.** Every event carries `payload.entity_id` = its own entity's id;
  quote/application events additionally carry `opportunity_id`. Opportunity events:
  `opportunity.created` / `stage_changed` / `lost`; policy events: `policy.created` /
  `policy.renewal_due`.
- **Correlation flow.** Lead conversion reuses the lead's `correlation_id` for household,
  contact, opportunities ([core/app/leads/conversion.py](../../core/app/leads/conversion.py));
  quotes/applications/policies propagate it (e.g.
  [core/app/policies/service.py](../../core/app/policies/service.py) copies
  `application.correlation_id`). Renewals: fresh id, `causation_id=None`, parentage via
  `opportunity.source_policy_id` ([core/app/renewals/service.py](../../core/app/renewals/service.py)).
- **Frontend.** [LeadTimeline.tsx](../../frontend/src/pages/LeadTimeline.tsx) (+ row
  components) polls ~2s with idle-stop; `SimulatedBadge` / `ExplainerPopover` reusable.
  [OpportunityDetailPage.tsx](../../frontend/src/pages/OpportunityDetailPage.tsx) exists;
  `PolicySummary` renders inside it and
  [HouseholdDetailPage.tsx](../../frontend/src/pages/HouseholdDetailPage.tsx). Routes in
  [App.tsx](../../frontend/src/App.tsx) — no policy route.
- **Walkthrough.** [stepperSteps.ts](../../frontend/src/components/stepperSteps.ts) step
  20 is prose-only; `GuidedDocket` renders no links.
- **Seed.** [core/app/seed.py](../../core/app/seed.py) `seed_baseline_money_paths` —
  household/contact/backing-lead share `conversion_correlation_id`; each chain mints
  `chain_correlation_id`; no outbox/processed rows for any of it.
  `_insert_lead_trail`-style synthesis exists for historical leads (P1.9 D7 pattern).
- **Isolation.** Tenant schema scoping via `get_tenant_db`; demo-session visibility rule
  (`demo_session_id IS NULL` ∪ own session) as in
  [core/app/leads/visibility.py](../../core/app/leads/visibility.py).

## 5. Proposed Design

**Approach** — generalize the P1.9 read into a shared module behind thin per-entity
routes; add one trace read endpoint + view; extend the seed; wire links.

**Components added / affected**
- *Moved/generalized* `app/leads/timeline.py` → `app/events/timeline.py`:
  `get_timeline_rows(db, entity_id)` (query + merge + status derivation unchanged); lead
  route re-pointed.
- *New* `GET /api/opportunities/{id}/timeline` (in `opportunities/router.py`) and
  `GET /api/policies/{id}/timeline` (policy router) — each loads + guards its record
  (existing visibility rules), then calls the shared module.
- *New* policy detail read `GET /api/policies/{id}` + *new* `PolicyDetailPage` at
  `/app/policies/:id` (PolicySummary + timeline + trace link); `PolicySummary` cards gain
  a link to it.
- *New* `app/trace/router.py` — `GET /api/trace/{correlation_id}`: outbox rows
  `WHERE correlation_id = :cid AND (demo_session_id IS NULL OR = :session)`, oldest-first
  (`occurred_at, id`), reactions synthesized as in the timeline read; each event row
  gains `entity_type` (derived from the `event_type` prefix) + `entity_id` (payload).
  Response also carries `origin_trace` / `renewal_traces` link objects (correlation id +
  label context), derived from `source_policy_id` (§6 D5).
- *New* baseline-trace resolver (`GET /api/trace/baseline` or equivalent) returning the
  tenant's seeded journey correlation id.
- *New* `TracePage` at `/app/trace/:correlationId` (`baseline` alias resolves then
  substitutes): ink-console flat stream per §6.11 — §6.1 row anatomy + entity-type chip
  per row, prominent mono `correlation_id`, renewal/origin link rows, explainer,
  "Simulated" badges.
- *Changed* timeline components — `LeadTimeline` (and the new generalized timeline) gain
  a "view full trace" link built from the record's `correlation_id` (already in every
  timeline row).
- *Changed* `stepperSteps.ts` + `GuidedDocket` — optional per-step `link`; step 20 →
  `/app/trace/baseline`.
- *Changed* `seed.py` — chains reuse `conversion_correlation_id` (drop
  `chain_correlation_id`); synthesize the full plausible outbox + `processed_events`
  trail for each baseline journey (lead → conversion → per-chain quote → application →
  policy events; reactions all done; backdated spread; live-identical payloads;
  count-based idempotent).

**Data model changes** — none. No migration.

**Interfaces**
- Timeline endpoints return the P1.9 `{"rows": [TimelineRow, ...]}` envelope unchanged.
- `GET /api/trace/{correlation_id}` → `{"correlation_id", "rows": [TraceRow...],
  "origin_trace": {correlation_id, label} | null, "renewal_traces": [{...}]}`;
  `TraceRow` = `TimelineRow` + `entity_type` + `entity_id` on event rows. Unknown /
  invisible correlation → empty rows (not 404 — a UUID key leaks nothing).
- Frontend: `getOpportunityTimeline`, `getPolicyTimeline`, `getPolicy`, `getTrace`,
  `getBaselineTrace` in `api/client.ts`.

**Primary flow — the signature moment (walkthrough step 20)**
1. Viewer opens a lead's trace via "view full trace" (or `/app/trace/baseline` from the
   stepper).
2. TracePage polls `GET /api/trace/{cid}` every ~2s continuously while mounted.
3. In another tab the viewer drives convert → quote → bind; each action's events land on
   the same `correlation_id`.
4. Each poll appends the new event + reaction rows in order — `lead.converted`,
   `opportunity.created`, `quote.requested` + quote reaction, … `policy.created`, each
   with the sync-logger reaction — no refresh, through the final sync reaction.
5. If the journey later spawns a renewal, the trace shows a renewal link; the renewal's
   trace links back.

**Isolation** — tenant schema scoping is automatic; the trace read adds the demo-session
filter (`NULL` ∪ own). Renewal-link derivation reads opportunities/policies under the same
session; another session's renewal never surfaces. No PII: rows carry event types, ids,
statuses, summaries — references, never values.

## 6. Decisions

**D1 — Policy timeline lives on a new policy detail page.**
- *Chosen:* `/app/policies/:id` + `GET /api/policies/{id}`; `PolicySummary` cards link to
  it; timeline + trace link render there.
- *Alternatives:* collapsible timeline inside the embedded `PolicySummary` cards.
- *Rationale:* gives "policy detail view" a real home matching the lead/opportunity
  structure instead of duplicating a console into two paper-card hosts; the page is thin
  (summary + timeline) so the extra scope is small.

**D2 — Generalized timeline: per-entity routes over one shared module.**
- *Chosen:* move the P1.9 read to `app/events/timeline.py`; thin
  opportunity/policy/lead routes own their guards and call it. Strict `entity_id` keying —
  an opportunity's timeline shows only its own events; quote/application events appear
  only in the trace (BRD scope). The quote-driven `stage_changed` events keep the
  opportunity timeline moving during quoting.
- *Alternatives:* one generic `GET /api/timeline/{entity_type}/{id}` with a guard
  dispatch table.
- *Rationale:* the query is already entity-agnostic, so only guards differ — and guards
  are exactly what the existing per-entity routers already do idiomatically; a dispatch
  table invents a new pattern for no route savings that matter.

**D3 — Trace read: own router, session-scoped by the standing visibility rule.**
- *Chosen:* `GET /api/trace/{correlation_id}` in new `app/trace/`; filter
  `demo_session_id IS NULL OR = current`; tenant schema scoping automatic; empty result
  for unknown/foreign ids.
- *Alternatives:* guard via a visible record (`/api/leads/{id}/trace` etc.).
- *Rationale:* a trace spans six entity types, so no single record guard fits without
  per-entity duplication; the session filter already blocks cross-session rows and
  correlation ids are unguessable UUIDs — same protection, one route.

**D4 — Trace renders as a flat chronological stream.**
- *Chosen:* one oldest-first list; each event row tagged with an entity-type chip +
  short ref; §6.1 anatomy on an ink console; mono `correlation_id` header.
- *Alternatives:* grouped-by-entity sections.
- *Rationale:* the trace's value is the causal story in time order — grouping tears
  interleaved cause/effect apart and duplicates what per-record timelines already show.

**D5 — Renewal ↔ origin links derived server-side in the trace response.**
- *Chosen:* origin → renewal: opportunities whose `source_policy_id` ∈ the trace's
  `policy.created` entity ids → their `correlation_id`s. Renewal → origin: the trace
  opportunity's `source_policy_id` → that policy's `correlation_id`. Returned as
  `origin_trace` / `renewal_traces` with label context.
- *Alternatives:* client-side stitching via follow-up calls.
- *Rationale:* one round trip and one home for the derivation; session scoping applies in
  the same query instead of being re-implemented client-side.

**D6 — Baseline chains unified onto one per-journey correlation id. (ADR 0008)**
- *Chosen:* seed chains reuse `conversion_correlation_id`; `chain_correlation_id`
  removed. Takes effect on fresh reseed (count-based idempotency skips existing data).
- *Alternatives:* keep per-chain fresh ids.
- *Rationale:* live conversion already gives one journey one correlation end-to-end; a
  split baseline would trace without its lead half — unfaithful to live and failing the
  "complete story" acceptance on the records visitors see first.

**D7 — Seeded history: full plausible per-journey trail (fills ADR 0007's shape).**
- *Chosen:* synthesize every event a live journey emits — lead trail (created → assigned
  → qualified → converted), conversion events (household/contact/opportunity created),
  per-chain quote.requested/completed + stage changes + application
  started/submitted/approved + policy.created — payload shapes identical to the live
  writers, catalog reactions all `done` (`published_at` set), timestamps backdated and
  spread lead-date → issue-date, count-based idempotent.
- *Alternatives:* minimal `opportunity.created` + `policy.created` per chain.
- *Rationale:* the trace is the engineering centerpiece; a gappy baseline story undercuts
  the claim it exists to prove, and the synthesis is the same mechanical
  per-event-type-table technique P1.9 already used for lead trails.

**D8 — New surfaces poll continuously (~2s) while mounted; no idle-stop.**
- *Chosen:* trace + opportunity/policy timelines re-fetch every ~2s until unmount or the
  session-expiry gate; lead timeline unchanged.
- *Alternatives:* P1.9-style idle-stop with focus re-arm.
- *Rationale:* these surfaces' events originate on *other* pages (the signature
  acceptance is cross-tab), so "all rows terminal" is a false stop signal — idle-stop
  could freeze the trace during the exact walkthrough beat it exists for; demo-scale
  polling cost is negligible.

**D9 — Stepper deep-link resolves to the baseline journey's trace.**
- *Chosen:* optional `link` on stepper steps rendered by the docket; step 20 →
  `/app/trace/baseline`, resolved via a small read to the tenant's seeded journey
  correlation id.
- *Alternatives:* resolve the caller's latest session journey with baseline fallback.
- *Rationale:* deterministic and always fully populated (D6/D7); the live-journey case
  is already one click via the per-record trace links, so "latest" heuristics buy
  ambiguity, not value.

**D10 — Build strategy: tracer bullet.**
- *Chosen:* first slice = live opportunity-detail timeline end-to-end (near-pure reuse),
  then the trace tracer (real rows on a bare page), then layer links/renewals/seed/polish.
- *Alternatives:* walking skeleton.
- *Rationale:* every layer (outbox reads, guards, polling, UI anatomy) shipped in
  P1.9–P2.4 — there is no structural risk left to prove; the risk is whether the trace
  story reads well, which only real visible slices answer.

## 7. Risks and Open Questions

- **Trace volume on multi-chain baselines.** One journey with several product lines plus
  full sync-logger fan-out yields a long stream. *Mitigation:* demo-scale counts (tens of
  rows); flat anatomy scrolls; if noisy, a per-entity filter chip is a cheap later add.
- **`entity_type` derivation from `event_type` prefix.** `record.created` / `pii.revealed`
  don't map to journey entities. *Mitigation:* they never share a journey correlation;
  derive from the known prefix table and label anything unknown generically.
- **Seed regression risk.** The correlation unification + trail synthesis touches the
  largest seed function. *Mitigation:* existing seed tests (`test_seed_money_paths`)
  extended with trail + correlation assertions; idempotency keys unchanged.
- **Baseline resolver ambiguity.** Each tenant has exactly one baseline money-path
  household today; if that ever grows, "the" baseline journey needs a pick rule (oldest).
- **Poll cost of continuous polling.** Accepted (D8); bounded by one mounted page.

## 8. Rollout / Verification

- **No migration, no feature flag.** Purely additive read surfaces + seed change; seed
  applies on fresh reseed only (demo reset path).
- **Manual verification:**
  1. Opportunity detail: run a quote; watch the timeline move live (stage change +
     reactions). Policy page: open from a PolicySummary link; timeline populated.
  2. Signature: open a lead's trace, drive convert → quote → bind in another tab; events
     append live through the final sync reaction (acceptance #1/step 20).
  3. One-click trace from lead, opportunity, and policy detail (#3); stepper step 20
     lands on the populated baseline trace.
  4. Run a renewal sweep; original trace shows the renewal link, renewal trace links
     back (#4).
  5. Fresh reseed: baseline opp/policy timelines + journey traces fully populated (#5);
     second demo session sees no cross-session rows.
- **Tests ship with each slice** (standing gate): shared timeline module reuse (lead
  regression + opp/policy routes + guards), trace read (ordering, session filter, empty
  unknown id, renewal links both directions), baseline resolver, seed trail
  (shape/correlation/idempotency), frontend render + continuous-poll + link tests.

## 9. Work Breakdown

Tracer-bullet order — visible thread first, then layer. Tests with each item.

1. **Generalize the timeline read + opportunity timeline (tracer).**
   - Move to `app/events/timeline.py`; re-point lead route; add
     `GET /api/opportunities/{id}/timeline` + `LeadTimeline`-derived component on
     opportunity detail with continuous polling.
2. **Policy detail page + policy timeline.**
   - `GET /api/policies/{id}` + `/app/policies/:id` page (PolicySummary + timeline);
     link from PolicySummary cards.
3. **Trace endpoint (tracer): ordered entity-tagged rows.**
   - `app/trace/router.py`, session filter, `TraceRow` shape.
4. **Trace page: flat stream UI.**
   - `/app/trace/:correlationId`, §6.11 ink console, chips, mono id, badges, explainer,
     continuous poll.
5. **"View full trace" links on the three per-record timelines.**
6. **Renewal ↔ origin trace links.**
   - Server derivation in the trace response + link rows in the UI.
7. **Seed: one correlation per journey + full plausible trails.**
   - Unify chain correlation (D6); synthesize journey event + reaction rows (D7).
8. **Stepper deep-link.**
   - Baseline resolver read; optional step `link`; step 20 → `/app/trace/baseline`.
9. **Acceptance hardening.**
   - Cross-session isolation on trace surfaces; the five BRD acceptance criteria
     end-to-end.
