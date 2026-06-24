# Per-record Event Timeline (P1.9) — Epic Plan

Source TDD: [./tdd-P1.9-event-timeline.md](./tdd-P1.9-event-timeline.md)

> **Review budget:** ~150 changed lines · ~8 non-generated files · one focused commit per epic. (Program default; tunable per epic.)

> **Build strategy:** Tracer bullet — copied from the TDD; `4-plan-epic` orders each epic's phases by it (`0-conventions.md` → *Build strategies*).

> High-level agile roadmap. Each epic's design specifics are confirmed with stakeholders at epic time (`4-plan-epic`) before any code is written.

## Epic 1 — Timeline tracer: domain-event rows on the lead detail page [UI]
- **Goal:** Open a lead and see a real, oldest-first list of its own domain events (from the tenant's `outbox`) rendered as a timeline below the detail cards — the thinnest customer-visible thread through migration, endpoint, and UI.
- **Rough scope:** Migration `0014` (grant the tenant role `SELECT` on `outbox`; add the nullable `result_summary` column the later summary epic fills, kept as one additive migration). A new per-lead timeline read endpoint that guards the lead (same 404 as the detail read) and returns its `outbox` event rows. API-client method + a new `LeadTimeline` component on the lead detail page; single fetch on open; relative timestamp with absolute on hover; unique `id` per element.
- **Open questions / decisions for stakeholders:** Exact placement and visual treatment of the timeline within the UI/UX Guide (card vs. inline section); timestamp display detail. Otherwise the read shape is settled by the TDD (D1).
- **Depends on:** none.
- **Implementation notes:** _none yet_

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
