# Per-record Event Timeline (P1.9) — Epic Plan

Source TDD: [./tdd-P1.9-event-timeline.md](./tdd-P1.9-event-timeline.md)

> **Review budget:** ~150 changed lines · ~8 non-generated files · one focused commit per epic. (Program default; tunable per epic.)

> **Build strategy:** Tracer bullet — copied from the TDD; `4-plan-epic` orders each epic's phases by it (`0-conventions.md` → *Build strategies*).

> High-level agile roadmap. Each epic's design specifics are confirmed with stakeholders at epic time (`4-plan-epic`) before any code is written.

## Epic 1 — Timeline tracer: domain-event rows on the lead detail page [UI] — **COMPLETED** (53m · 43.6M tok · 812k tok/min)
- **Goal:** Open a lead and see a real, oldest-first list of its own domain events (from the tenant's `outbox`) rendered as a timeline below the detail cards — the thinnest customer-visible thread through migration, endpoint, and UI.
- **Rough scope:** Migration `0014` (grant the tenant role `SELECT` on `outbox`; add the nullable `result_summary` column the later summary epic fills, kept as one additive migration). A new per-lead timeline read endpoint that guards the lead (same 404 as the detail read) and returns its `outbox` event rows. API-client method + a new `LeadTimeline` component on the lead detail page; single fetch on open; relative timestamp with absolute on hover; unique `id` per element.
- **Open questions / decisions for stakeholders:** none — resolved at plan time (rung-3 grill):
  - **Placement:** the EVENT TIMELINE console sits at the **very bottom** of the lead detail page, *after* the qualify/reject actions section (keeps the agent's read→act flow first; the dark showcase anchors the page end).
  - **Console scope this slice:** build the **full Guide §6.1 event-row ink-console anatomy now** — inverted ink console card, "EVENT TIMELINE" stamp overline, vertical hairline + per-row tick marker, raw event name + mono `event_id`, neutral OCCURRED stamp. Deferred to their owning epics: reaction sibling rows + `└─` connectors (Epic 2), Simulated badge + explainer (Epic 6), live slide-in/polling (Epic 4).
  - **Timestamps:** row shows a **full-words relative** label ("just now" / "2 hours ago" / "3 days ago"); **absolute on hover** (title attr) is a **fixed-width UTC** stamp `YYYY-MM-DD HH:MM:SS UTC` (locale-independent, tabular-nums, time-of-day precision — the date-only `leadDate` won't do).
  - **Empty timeline:** the console **always renders**; zero events shows a calm **on-ink note** ("No events recorded for this lead yet"). Seed leads are empty until Epic 5 seeds trails — consistent before/after.
  - **Event status stamp:** a **neutral OCCURRED stamp** (on-ink-variant tone, *not* a state bright) — §2.2 "information is not a signal." State-colored stamps belong to Epic 2's reaction rows.
  - **Event name:** the **raw dotted bus value verbatim** (`lead.created`) — truthful to the bus, teaches the vocabulary; matches Epic 2's raw consumer names.
- **Depends on:** none.
- **Implementation notes:**
  - This slice builds the ink console **minus reactions** (event rows are neutral by design — the state-colored Pending/Processing/Done stamps are reaction-row state, not event fact). **Epic 2** adds reaction sibling rows + `└─` connectors onto *this* console, **Epic 4** adds live slide-in/polling, **Epic 6** the Simulated badge + explainer — none a rebuild.
  - The timeline outbox query filters on **`payload->>'entity_id'` ALONE** (not `entity_type='lead' AND …`): only `lead.created` carries `payload.entity_type`, so an `entity_type` clause would silently drop every event after creation. **Epic 2's LEFT JOIN of `processed_events` rides this same `entity_id`-keyed event set** — keep the filter `entity_id`-only.
  - `0014`'s `outbox` SELECT re-grant means the **0008 migration test was updated** — the tenant role now has INSERT **and** SELECT on its own outbox (UPDATE/DELETE still revoked). Any later epic touching outbox grants must keep that pair.
  - Migration `0014` adds `processed_events.result_summary` (nullable, **unused until Epic 3**) alongside the grant, as one additive migration; **Epic 3** fills the column with no new migration.
  - **Epic 4's polling layers onto `LeadTimeline`'s single-fetch `useEffect`** — extend it, don't rebuild.

## Epic 2 — Reaction rows + status derivation [UI]
- **Goal:** Show each sidecar reaction the catalog fires (`enrichment.stub` on `lead.created`, `sync.logger` on every event) as a sibling row carrying a derived status — `pending → processing → done` (with `failed` present in the vocabulary but dormant).
- **Rough scope:** Synthesize the expected reactions per event from `CONSUMER_BINDINGS`, LEFT JOIN `processed_events` on `event_id`, and derive status from real bus state (no processed row + unpublished = pending; published, no processed row = processing; processed row present = done). Endpoint merge logic + reaction-row rendering as siblings of event rows.
- **Open questions / decisions for stakeholders:** Visual distinction of reaction rows vs. event rows and how the three statuses read at a glance (pill/label styling), within the Guide.
- **Depends on:** Epic 1.
- **Implementation notes:** _none yet_

## Epic 3 — Result summary on the enrichment reaction [UI]
- **Goal:** When a reaction flips to `done`, the enrichment row shows a one-line result summary (a deterministic canned quality score), proving the M3-forward-compatible result path.
- **Rough scope:** The enrichment stub computes a deterministic summary (stable across redeliveries, derived from `event_id`) and writes it to `result_summary` on the fresh-insert path; `sync.logger` writes its own one-liner or null. The endpoint returns it verbatim; reaction rows render it. (Column already added in Epic 1's migration.)
- **Open questions / decisions for stakeholders:** Exact shape/wording of the canned summary string; how a null summary renders.
- **Depends on:** Epic 2.
- **Implementation notes:** _none yet_

## Epic 4 — Live polling: the watchable moment [UI]
- **Goal:** The timeline updates live without manual refresh — a freshly created lead's enrichment reaction visibly advances `Pending → Processing → Done` on screen (walkthrough step 4).
- **Rough scope:** Client re-fetches the timeline on a short cadence (~2s) while mounted, idle-stops once every row is terminal, and re-arms on a viewer action. Reuse the existing Epic 12 session-expiry gate so an expired-session `404` stops the poll gracefully rather than trapping.
- **Open questions / decisions for stakeholders:** Final poll cadence tuned against the ~1s relay so `processing` is usually observable (TDD risk); re-arm trigger.
- **Depends on:** Epic 3.
- **Implementation notes:** _none yet_

## Epic 5 — Seeded history: coherent trails on baseline leads
- **Goal:** Historical/seed leads open with a populated, coherent chronological timeline (never empty), matching their status.
- **Rough scope:** Extend the seed to synthesize each baseline lead's event sequence from its status (`lead.created` always; `+ lead.assigned` if claimed; `+ lead.qualified`/`lead.rejected` for terminal status) plus matching `processed_events` rows — all `done`, backdated and spread, `demo_session_id = NULL`, enrichment carrying a `result_summary`. Count-based idempotent, like the rest of the seed.
- **Open questions / decisions for stakeholders:** Backdating spread/spacing of synthesized timestamps; whether every baseline status variant needs coverage.
- **Depends on:** Epic 3 (so seeded reactions carry a result summary).
- **Implementation notes:** _none yet_

## Epic 6 — "Simulated" badge + outbox explainer [UI]
- **Goal:** Reaction rows are clearly marked as simulated, and the timeline carries one explainer of the outbox/event-bus mechanism — reusing the P1.6 components.
- **Rough scope:** Reuse the P1.6 `SimulatedBadge` on stub-reaction rows and one `ExplainerPopover` on the timeline describing how the outbox/event bus drives the reactions.
- **Open questions / decisions for stakeholders:** Explainer copy and placement; whether the badge sits per-row or once on the reaction group.
- **Depends on:** Epic 2 (reaction rows must exist to badge).
- **Implementation notes:** _none yet_

## Epic 7 — Isolation + acceptance hardening
- **Goal:** Re-prove tenant + demo-session isolation on the new timeline surface and cover the five acceptance criteria end-to-end.
- **Rough scope:** A named acceptance/isolation test proving another session's reactions never appear and no cross-tenant row leaks (linkage rides the `event_id` join off the lead's own events), plus end-to-end coverage of the live moment, coherent seeded trail, both stub reactions as siblings, and the badge/explainer presence.
- **Open questions / decisions for stakeholders:** none expected — acceptance criteria are fixed by the TDD §8.
- **Depends on:** Epics 1–6.
- **Implementation notes:** _none yet_
