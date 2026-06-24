# Per-record Event Timeline (P1.9) — Technical Design Document

> **Build strategy:** Tracer bullet — chosen at design time (rationale in §6, D8); `3-tdd-to-epic-plan` copies this to the epic plan and `4-plan-epic` honors it (`0-conventions.md` → *Build strategies*).

## 1. Summary

A live-updating **event timeline** on the lead detail page that makes PolicyFlow's
event-driven processing visible. For one lead it renders, in a single oldest-first
stream, every **domain event** (from the tenant's `outbox`) and every **sidecar
reaction** (from `processed_events`) as sibling rows, each with a status and
timestamp; reaction rows also carry a one-line result summary and a "Simulated"
badge, and the timeline carries one explainer of the outbox/event-bus mechanism. It
is a pure read/visibility surface over data that already exists — no new domain
events, no workflow change — and it delivers walkthrough step 4: the viewer watches
the enrichment reaction advance `Pending → Processing → Done` on-screen without
refreshing.

## 2. Business Requirements

Source: [./brd-P1.9-event-timeline.md](./brd-P1.9-event-timeline.md) — read as the agreed
requirements; not re-narrated here. Constraints/clarifications surfaced during this design:

- **The reaction store carries no lead or session link.** `processed_events` has no
  `entity_id` and no `demo_session_id`; a reaction joins to its lead and session only
  through its originating `outbox` row on `event_id`. This shapes the whole read.
- **The reaction store carries no result.** The "quality score" exists nowhere today —
  the stub effect only logs. A place to store it must be added (§6 D4).
- **The tenant web role cannot read the outbox.** `0008` revoked `SELECT` on `outbox`
  from the tenant role (kept it on `processed_events` explicitly "for the P1.9
  timeline"). A grant is required (§6 D5).
- **Stubs are terminal and complete near-instantly** (`consumers.py`): they record one
  `processed_events` row and ack — no completion event, no stored intermediate state.
  The status motion is therefore *derived*, not stored (§6 D2).

## 3. Goals / Non-Goals

**Goals**
- One per-lead, oldest-first timeline of domain events + sidecar reactions on the lead
  detail page, each row with status + timestamp; reaction rows with a result summary.
- Honest, watchable `Pending → Processing → Done` motion for the enrichment reaction,
  live without manual refresh (walkthrough step 4).
- Coherent, pre-populated timelines on historical/seed leads (no empty timelines).
- Reuse P1.6 "Simulated" badge + explainer; preserve tenant + demo-session isolation,
  re-proven by test; add no new visibility.

**Non-Goals**
- No new domain events, no workflow behavior, no real sidecars (M3), no `Failed` data
  path (`Failed` is in the vocabulary but dormant).
- No timeline on opportunities/policies and no correlation-trace view (P2.5).
- No retry/DLQ/replay visibility, no integration-health dashboard (M3/M4).
- No push transport (SSE/WebSocket) — polling only (§6 D6).

## 4. Current State

- **Outbox (durable event log).** [core/app/models/outbox_event.py](../../core/app/models/outbox_event.py)
  — per-tenant, schema-less `outbox`; columns include `event_id`, `event_type`,
  `occurred_at`, `published_at`, `correlation_id`, `demo_session_id`, `payload` (JSONB
  with `entity_type`/`entity_id`). Rows **persist** after publish — the relay only
  `SELECT`s + stamps `published_at`, never deletes
  ([core/app/events/relay.py](../../core/app/events/relay.py)). Written in-request by
  [enqueue_event](../../core/app/events/outbox.py); lead events carry
  `payload.entity_type == "lead"`, `entity_id == str(lead.id)`
  ([core/app/leads/intake.py](../../core/app/leads/intake.py), router actions).
- **Processed events (reaction store).** [core/app/models/processed_event.py](../../core/app/models/processed_event.py)
  — per-tenant `processed_events` (`consumer_name`, `event_id`, `event_type`,
  `correlation_id`, `processed_at`). **No `entity_id`, no `demo_session_id`,
  no result.** Written once per fresh event by the terminal stubs
  ([core/app/events/consumers.py](../../core/app/events/consumers.py)).
- **Event vocabulary.** [core/app/events/catalog.py](../../core/app/events/catalog.py)
  — `EventType` (`lead.created`, `lead.assigned`, `lead.qualified`, `lead.rejected`,
  `lead.duplicate_detected`, …) and `CONSUMER_BINDINGS`: `enrichment.stub` binds
  `lead.created` (+ `record.created`); `sync.logger` binds `#` (every event).
- **Grants.** [core/alembic/versions/0008_event_bus.py](../../core/alembic/versions/0008_event_bus.py)
  — tenant `db_role` is INSERT-only on `outbox` (`SELECT` **revoked**, line ~202) and
  SELECT-only on `processed_events` (kept "for the P1.9 timeline"). Latest migration
  is `0013`; next is `0014`.
- **Lead read + isolation.** [core/app/leads/router.py](../../core/app/leads/router.py)
  (`get_tenant_db`, `_guard_loaded_lead_for_session`),
  [core/app/leads/visibility.py](../../core/app/leads/visibility.py)
  (`visible_to_session`: seed `demo_session_id IS NULL` ∪ own session),
  [core/app/leads/masking.py](../../core/app/leads/masking.py),
  [core/app/demo/session.py](../../core/app/demo/session.py) (`current_demo_session`).
- **Frontend.** [frontend/src/pages/LeadDetailPage.tsx](../../frontend/src/pages/LeadDetailPage.tsx)
  (stacked Cards, `useEffect` fetch pattern, Epic 12 expiry gate),
  [frontend/src/api/client.ts](../../frontend/src/api/client.ts) (`getLead`),
  reusable [SimulatedBadge.tsx](../../frontend/src/components/SimulatedBadge.tsx) +
  [ExplainerPopover.tsx](../../frontend/src/components/ExplainerPopover.tsx).
- **Seed.** [core/app/seed.py](../../core/app/seed.py) `seed_shared_historical_leads`
  inserts baseline leads directly (`demo_session_id IS NULL`, backdated `created_at`,
  own `correlation_id`) — fires **no** bus events, so their timelines are empty today.

## 5. Proposed Design

**Approach** — one server-merged read endpoint + a frontend timeline component that
polls it; a tiny migration; a one-line consumer change; and a seed extension.

**Components added / affected**
- *New* `GET /api/leads/{lead_id}/timeline` (in `app/leads/router.py`) + a timeline
  read/merge module (`app/leads/timeline.py`) holding the query, merge, and status
  derivation. *New* response schema(s) in `app/leads/schemas.py`.
- *New* frontend `LeadTimeline` component (+ row sub-components) rendered on
  `LeadDetailPage`; *new* `getLeadTimeline(leadId)` in `api/client.ts`.
- *Changed* `consumers.py` — `_run_enrichment_effect` (and `_run_sync_logger_effect`)
  write `result_summary`; `_record_processed_event` includes it in the INSERT.
- *Changed* `processed_event.py` ORM twin — add `result_summary` column.
- *New* migration `0014` — grant tenant role `SELECT` on `outbox`; add nullable
  `result_summary` to `processed_events` (every tenant schema).
- *Changed* `seed.py` — synthesize a status-derived outbox + processed_events trail per
  baseline lead.

**Data model changes**
- `processed_events.result_summary text NULL` (new). No other schema changes; `outbox`
  / `processed_events` columns are otherwise reused as-is.
- Grant: `GRANT SELECT ON <schema>.outbox TO <tenant db_role>` per tenant.

**Interfaces**
- `GET /api/leads/{lead_id}/timeline` → `{"rows": [TimelineRow, ...]}`, oldest-first.
  Reuses `get_tenant_db` (auto-isolated) and the existing lead-guard, so a missing /
  cross-tenant / cross-session lead is the same `404` as the detail read.
- `TimelineRow` (one shape, discriminated by `kind`):
  - common: `kind` (`"event"` | `"reaction"`), `occurred_at` (ISO), `event_type`,
    `correlation_id`.
  - event: `status = "occurred"`.
  - reaction: `consumer_name`, `status` ∈ `{pending, processing, done, failed}`
    (`failed` dormant), `result_summary` (string | null), `is_simulated = true`.
- Status derivation (per expected reaction = event × bound consumer from
  `CONSUMER_BINDINGS`):
  - `done` — a `processed_events` row exists for `(consumer_name, event_id)`.
  - `processing` — no processed row **and** the event's `published_at IS NOT NULL`.
  - `pending` — no processed row **and** `published_at IS NULL`.

**Primary flow — the live moment (sequence)**
1. Agent creates a lead → `enqueue_event(lead.created)` writes one `outbox` row in the
   request txn (`published_at = NULL`).
2. Page opens; first `GET /timeline` returns: `lead.created` (event, occurred) +
   synthesized reactions `enrichment.stub` and `sync.logger` as `pending` (event not
   yet published).
3. Relay sweep (~1s) publishes the row, stamps `published_at` → next poll shows the
   reactions as `processing`.
4. Each stub processes near-instantly, inserts its `processed_events` row (enrichment
   writes `result_summary`) → next poll shows `done` + the quality-score summary.
5. Poll idle-stops once every row is terminal.

**Isolation** — primary gate is the lead-guard (caller must already be able to see the
lead). Defense-in-depth: the outbox query filters `payload->>'entity_id' = :lead_id`,
and a lead's events can only carry that lead's own `demo_session_id` (or `NULL` for
seed), so reactions joined via `event_id` inherit the same visibility. No row from
another tenant (schema-isolated) or another session can appear. Re-proven by test (§8).

> **Amended 2026-06-24 (Epic 1 impl):** the filter is `entity_id` **alone**, not the
> originally-written `entity_type='lead' AND entity_id`. Only `lead.created` carries
> `payload.entity_type="lead"`; `assigned`/`qualified`/`rejected`/`duplicate_detected`
> (and the envelope) carry **no** `entity_type`, so the AND clause would silently drop
> every event but `lead.created` — breaking the Goal and Epic 5's coherent trail. Every
> lead event reliably carries `entity_id = str(lead.id)` (a UUID, no cross-entity
> collision), the query is per-tenant (schema-scoped), and the lead-guard is the primary
> gate — so dropping the `entity_type` clause loses no isolation.

**Seeded history** — for each baseline lead, derive its event sequence from `status`
(`lead.created` always; `+ lead.assigned` if claimed; `+ lead.qualified` /
`lead.rejected` for terminal status), insert `outbox` rows (`published_at` set,
`demo_session_id = NULL`, `occurred_at` backdated + spread, reuse the lead's
`correlation_id`) and the matching `processed_events` rows (all `done`, enrichment
carrying a `result_summary`). Count-based idempotent, like the rest of `seed`.

## 6. Decisions

**D1 — Read shape: one server-merged endpoint.**
- *Chosen:* `GET /api/leads/{id}/timeline` under `get_tenant_db`; server loads+guards
  the lead, reads its outbox rows, LEFT JOINs `processed_events` on `event_id`, derives
  status + summary, merges to one oldest-first list.
- *Alternatives:* two endpoints with client-side merge; fold timeline into `getLead`.
- *Rationale:* one round trip and one place for the join/merge/status logic (can't
  drift); inherits isolation from the existing lead-guard; keeps the fast detail read
  uncoupled from a heavier join and keeps the poll cheap.

**D2 — Reaction status derived from real bus state.**
- *Chosen:* `pending` (`published_at IS NULL`) → `processing` (published, no processed
  row) → `done` (processed row present); reaction rows synthesized from
  `CONSUMER_BINDINGS` so they appear before processing.
- *Alternatives:* client-optimistic cosmetic "Processing"; a stored status column the
  consumer advances.
- *Rationale:* every state maps to a real fact, so the demo's honesty contract holds;
  the real ~1s relay gap makes the progression watchable; needs no fake delay, no
  change to the M3-bound terminal-consumer contract.

**D3 — Faithful fan-out of reactions.**
- *Chosen:* render every reaction the catalog fires — `enrichment.stub` on
  `lead.created`, `sync.logger` on every event.
- *Alternatives:* collapse `sync.logger` to one row; show only the enrichment reaction.
- *Rationale:* truthful to the bus and teaches the fan-out; satisfies acceptance #3
  (both stub kinds as sibling rows); per-lead event counts are small, so the extra rows
  aren't noisy.

**D4 — Result summary stored on `processed_events`.**
- *Chosen:* add nullable `result_summary`; the enrichment stub computes a deterministic
  canned score and writes it (`sync.logger` writes its own one-liner or null); the read
  returns it verbatim.
- *Alternatives:* derive the score at read-time from `event_id`, store nothing.
- *Rationale:* forward-compatible per §7 — M3's real sidecar writes a real value to the
  same column with the read path unchanged (the stub effect is already documented as
  "the placeholder M3 swaps in"); the summary appears exactly when the row flips to
  `done`. Marginal cost: one nullable column + a few lines in the stub.

**D5 — Grant tenant role `SELECT` on `outbox`.**
- *Chosen:* migration `0014` grants `SELECT ON <schema>.outbox` to each tenant
  `db_role` (and adds `result_summary`).
- *Alternatives:* a dedicated NOLOGIN timeline-reader role the endpoint `SET ROLE`s into.
- *Rationale:* mirrors how `0008` already kept `processed_events` SELECT for this
  timeline; the role only ever sees its own schema, so isolation is unchanged; a new
  role is heavier than this read warrants.

**D6 — Live updates by client polling (~2s, idle-stop).**
- *Chosen:* the page re-fetches `/timeline` every ~2s while mounted and stops once every
  row is terminal (`done`); a viewer action re-arms it.
- *Alternatives:* fixed poll that never stops; SSE/WebSocket push.
- *Rationale:* meets the 1–2s target with no new server infra, matches the relay's
  polling ethos, and is trivial to test; push adds connection lifecycle and a fan-out
  seam that a small-volume demo doesn't need.

**D7 — Seeded history: status-derived coherent trail.**
- *Chosen:* synthesize each baseline lead's events from its status (+ reactions, all
  `done`, backdated, `demo_session_id NULL`, idempotent).
- *Alternatives:* minimal `lead.created`-only trail; replay through the real bus at seed
  time.
- *Rationale:* a Qualified/Rejected lead's timeline shows its qualify/reject event
  (acceptance #2 "coherent"); avoids coupling the boot-time seed to a running
  broker/consumers and keeps timestamps as backdated history.

**D8 — Build strategy: tracer bullet.**
- *Chosen:* first slice = thinnest customer-visible thread (real domain-event rows on
  the page), then layer reactions → status → polling → summary → seed → badge/explainer.
- *Alternatives:* walking skeleton (faked rows end-to-end first).
- *Rationale:* the risk is the UX/live moment, not architecture — the event bus,
  outbox, consumers, page, and demo-session scoping all already exist, so there's little
  structural risk to de-risk; optimize for fast feedback on the visible thing.

## 7. Risks and Open Questions

- **Timing of the live moment.** With a ~1s relay and ~2s poll, a poll could land
  showing `pending` then `done`, skipping a visible `processing` tick. *Mitigation:* the
  three states are all real, so even a skipped tick is honest; the poll cadence (~2s)
  is tuned against the relay interval to make `processing` usually observable; cadence
  is adjustable within the 1–2s target if needed.
- **Determinism of the canned score.** Must be stable across re-renders/redeliveries.
  *Mitigation:* derive from `event_id` (stable), write once on the fresh-insert path.
- **Session expiry mid-view.** A `/timeline` poll may `404` when the demo session
  expires. *Mitigation:* reuse the lead-detail Epic 12 expiry gate; the poll stops and
  the gate shows, no trap.
- **Seed idempotency in the shared container.** Re-seeding must not duplicate trails.
  *Mitigation:* count-based skip keyed to the baseline (`demo_session_id IS NULL`)
  outbox rows, matching `seed_shared_historical_leads`.
- **`processed_events` has no `entity_id`.** All lead↔reaction linkage rides the
  `event_id` join; an event with no matching outbox row would orphan a reaction.
  *Mitigation:* the query drives from outbox (the lead's events) and LEFT JOINs
  reactions, so orphans cannot appear.

## 8. Rollout / Verification

- **Migration `0014`** — additive only (one grant + one nullable column); no
  data backfill at upgrade. `alembic check` must stay green (the `processed_events`
  ORM twin gains the column; the migration owns it, per the schema-less pattern).
  Downgrade reverses the grant + drops the column.
- **No feature flag** — a new read surface on an existing page; nothing pre-existing
  changes behavior. Backwards compatible: the consumer change is an added write to a new
  nullable column; older rows simply have `result_summary = NULL`.
- **Manual verification:**
  1. Create a fresh lead, open detail; watch the enrichment reaction go
     `Pending → Processing → Done` with a quality score, no refresh (acceptance #1).
  2. Open a historical/seed lead; confirm a populated, coherent chronological trail
     with statuses + timestamps (acceptance #2).
  3. Confirm both stub reactions appear as sibling rows (#3); the "Simulated" badge on
     reaction rows and one explainer present (#4).
  4. As a second demo session, confirm another session's reactions never appear (#5).
- **Tests ship with each slice** (standing gate): endpoint unit/integration (merge,
  status derivation, summary), the isolation test (tenant + demo-session, #5), a seed
  test (coherent non-empty trail), and frontend render/poll tests.

## 9. Work Breakdown

Tracer-bullet order — first the thinnest customer-visible thread, then layer. Tests
ship with each item.

1. **Migration `0014` — outbox read grant + `result_summary` column.**
   - `GRANT SELECT ON <schema>.outbox` per tenant; add `processed_events.result_summary`
     (nullable); update the ORM twin; keep `alembic check` green.
2. **Timeline endpoint (tracer): domain-event rows only.**
   - `GET /api/leads/{id}/timeline` — guard the lead, select its `outbox` events
     (`payload->>'entity_id' = :lead_id`; see the §5 amendment), return oldest-first
     event rows (`status="occurred"`, timestamps). `getLeadTimeline` in the API client.
3. **Frontend: render the event rows on lead detail.**
   - `LeadTimeline` component below the detail cards; chronological rows with relative
     timestamp + absolute on hover; unique `id` per element. Single fetch on open.
4. **Reaction rows + status derivation.**
   - Synthesize expected reactions from `CONSUMER_BINDINGS`, LEFT JOIN
     `processed_events` on `event_id`, derive `pending`/`processing`/`done` (+ dormant
     `failed` in the type). Render reaction rows as siblings with status.
5. **Result summary.**
   - Enrichment stub computes + writes the deterministic `result_summary`; endpoint
     returns it; reaction rows show the one-line summary.
6. **Live polling.**
   - Client polls `/timeline` ~2s while mounted; idle-stop when all rows terminal;
     handle the session-expiry `404` via the existing gate.
7. **Seeded history.**
   - Extend `seed.py` to synthesize the status-derived outbox + `processed_events` trail
     per baseline lead (all `done`, backdated, `demo_session_id NULL`, idempotent).
8. **"Simulated" badge + explainer.**
   - Reuse P1.6 `SimulatedBadge` on stub-reaction rows; one `ExplainerPopover` on the
     timeline describing the outbox/event-bus mechanism.
9. **Isolation + acceptance hardening.**
   - Re-prove tenant + demo-session isolation on the timeline surface; cover the five
     acceptance criteria end-to-end.
