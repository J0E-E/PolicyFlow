# Opportunity Pipeline & Product Rules (P2.2) — Epic Plan

Source TDD: [./tdd-P2.2-opportunity-pipeline-product-rules.md](./tdd-P2.2-opportunity-pipeline-product-rules.md)

> **Review budget:** ~300 changed lines · ~16 non-generated files · one focused commit per epic. Tunable per project.

> **Build strategy:** Tracer bullet — copied from the TDD; `4-plan-epic` orders each epic's phases by it (`0-conventions.md` → *Build strategies*). **Epic 1** is the pure-logic substrate; **Epic 2 is the thinnest customer-visible end-to-end thread** (advance one converted opportunity one stage, server-validated, event emitted, board updates); everything after layers config, skip semantics, the gate, Lost, isolation, and polish onto it.

> High-level agile roadmap. Each epic's design specifics are confirmed with stakeholders at epic time (`4-plan-epic`) before any code is written.

## Epic 1 — Stage vocabulary + machine — **COMPLETED** (11m50s)
- **Goal:** Stand up the pure, framework-free opportunity state machine: the canonical stage vocabulary, the forward spine, optional/anchor/terminal sets, and the transition functions (`next_enabled_stage` / `allowed_targets` / `assert_transition`) that take a tenant's enabled set so the logic stays pure. Policy: forward-by-one-to-next-enabled + any-active → Lost; no backward, no multi-skip, no exit from Policy Active/Lost. No wiring yet — this is the ground every later epic validates against.
- **Rough scope:** a new `opportunities/state.py` mirroring `leads/state.py` (`OpportunityStage` StrEnum, canonical order, the stage sets, `InvalidStageTransition`); a hand-written state test asserting members + transitions against an independent expectation.
- **Open questions / decisions for stakeholders:** none expected.
- **Depends on:** none.
- **Implementation notes:** `opportunities/state.py` transition functions (`assert_transition`/`next_enabled_stage`/`allowed_targets`) take `enabled_stages: frozenset[OpportunityStage]` — Epics 3/4 build that per-tenant set and pass it in.

## Epic 2 — Tracer slice — advance one stage end-to-end [UI] — **COMPLETED** (29m01s)
- **Goal:** The thinnest demoable thread through every layer. A minimal board at `/app/opportunities` lists a session's converted opportunities; an Advance control calls the stage endpoint, the server validates the move and emits `opportunity.stage_changed` on the request transaction, and the board refetches so the card reflects its new stage. Pierces machine → service → events → API → UI; later epics layer real config, the gate, and polish onto it.
- **Rough scope:** add the two event types (`opportunity.stage_changed`, `opportunity.lost`) + catalog test; `service.py::change_opportunity_stage` (transition + emit, ride the request txn, reuse the opportunity's `correlation_id`); `router.py` with a flat `GET /api/opportunities` and `POST /api/opportunities/{id}/stage` (guards: capability → holder → transition), mounted in `main.py`; FE api client + types, the route behind the session guard, flip the inert "opportunities" nav item live, a minimal page that lists cards and advances one stage (every element gets an `id`).
- **Open questions / decisions for stakeholders:** none expected — minimal payload (id, contact ref, stage) and a single Advance affordance; richer payload/columns/controls come later.
- **Depends on:** Epic 1.
- **Implementation notes:** Tracer hardcodes `FULL_ENABLED_STAGES = frozenset(CANONICAL_FORWARD_ORDER)` in `router.py` (every stage on) — **Epics 3/4 replace it with the resolved per-tenant enabled set**. The board read returns a server-computed `next_stage` per row (`router.py::_opportunity_row`) so the FE Advance control has its target without the machine — **Epic 4** may drop it once `pipeline.stages` columns drive the target. `service.py::change_opportunity_stage` emits only `opportunity.stage_changed`; the `opportunity.lost` type is defined but **unemitted until Epic 6** (its `_emit` helper is ready for the Lost branch). Deferred guards are named gaps in `router.py::change_stage`: demo-session write-isolation 404/409 (**Epic 7**), Medicare 422 (**Epic 5**); the board read is tenant-schema-scoped only — **Epic 7** adds `visible_to_session`. Deviation: the standalone service DB test was folded into `test_opportunity_stage.py` (stage write + event payload + 409 over the real path).

## Epic 3 — Per-tenant pipeline config + resolution
- **Goal:** Make the pipeline tenant-configurable from the seed-driven registry (no DB table, no migration): each tenant carries stage-label overrides and its enabled optional stages, and product lines carry the Medicare-age flag. A pure resolver returns the enabled stages in canonical order with their tenant labels for the board, and the two demo tenants are configured to look visibly different.
- **Rough scope:** extend `TenantConfig` (`stage_labels`, `enabled_optional_stages`) and `ProductLine` (`requires_medicare_age`); `pipeline.py::resolve_pipeline`; configure Sunshine (both optional stages on, Medicare relabels, Medicare lines flagged) and Florida (Approved disabled to prove skip, its own relabels) per D13; surface `pipeline.stages` in the board payload.
- **Open questions / decisions for stakeholders:** confirm the exact per-tenant label strings + enabled-stage sets (TDD §5.2 proposes concrete values — recommend adopting as-is).
- **Depends on:** Epic 2.
- **Implementation notes:** _none yet_

## Epic 4 — Enabled-set skip semantics [UI]
- **Goal:** Honor each tenant's enabled set end-to-end: the machine and the stage endpoint skip disabled optional stages (Advance targets the next *enabled* stage), and the board renders one column per enabled stage under its tenant label, grouping cards by stage. Florida's disabled *Approved* visibly demonstrates the Submitted → Policy Active skip.
- **Rough scope:** feed the resolved enabled set into `assert_transition` / `next_enabled_stage` at the endpoint; board reads `pipeline.stages` and renders grouped, tenant-labeled columns; the Advance control names the next enabled stage's tenant label.
- **Open questions / decisions for stakeholders:** none expected.
- **Depends on:** Epics 2, 3.
- **Implementation notes:** _none yet_

## Epic 5 — Medicare eligibility gate [UI]
- **Goal:** Block entry to *Quoted* for an under-65 customer on a Medicare-gated product line, with a distinct, clear rejection (422, separate from a 409 invalid move); the enrichment flag never gates. The board surfaces the server's reason inline and an explainer describes the gate + the per-tenant config.
- **Rough scope:** a pure `is_blocked_for_medicare(product_line, age_band)` helper (plaintext `age_band == "65+"`, no decryption) reused later by P2.3; the stage endpoint returns 422 on a gated `→ Quoted` for under-65; board shows the blocked reason + an `ExplainerPopover` for the gate.
- **Open questions / decisions for stakeholders:** confirm the gated product-line set is `medicare_advantage` + `medicare_supplement` (Part D isn't a modeled line — Risk R3; recommend confirming as the intended set).
- **Depends on:** Epics 2, 3.
- **Implementation notes:** _none yet_

## Epic 6 — Mark Lost [UI]
- **Goal:** Let an agent mark an active opportunity *Lost* (a terminal stage) through the same stage endpoint with `target_stage="Lost"`, emitting both `opportunity.lost` and `opportunity.stage_changed`; a Lost opportunity is terminal (no further moves). The board gains a Mark Lost action.
- **Rough scope:** the Lost branch in `change_opportunity_stage` (emit both events); endpoint accepts `"Lost"` as a valid target from any active stage; terminal enforcement (no exit from Lost/Policy Active); board "Mark Lost" affordance per card.
- **Open questions / decisions for stakeholders:** none expected — Lost-reason capture is deferred (D8); Lost is non-reopenable in P2.2.
- **Depends on:** Epic 2.
- **Implementation notes:** _none yet_

## Epic 7 — Demo-session write isolation + board read hardening
- **Goal:** Close the session-isolation invariant for the board and enrich the read so the UI has what it needs: the list is scoped to the caller's session (NULL baseline ∪ caller's session), the mutation refuses a foreign session (404) and a shared-seed opportunity (409) and reuses the resolved session id to stamp events, and the list payload carries the value fields, contact name, owner, and eligibility flags.
- **Rough scope:** `visible_to_session` on `GET /api/opportunities`; the load → foreign-session-404 → seed-409 guard sequence on the mutation (mirrors convert); extend the list row with `estimated_annual_premium`, `target_close_date`, plaintext contact name, owner, and `eligibility: {medicare_gated, age_eligible}`.
- **Open questions / decisions for stakeholders:** none expected.
- **Depends on:** Epic 2.
- **Implementation notes:** _none yet_

## Epic 8 — Board UI polish [UI]
- **Goal:** Finish the board as small, focused components: per-stage columns with cards showing contact name, product-line label, value fields (em-dash when null), and owner, plus the per-card Advance / Mark Lost controls and a `SimulatedBadge` where appropriate. Component tests cover each piece.
- **Rough scope:** split into `PipelineBoard` / `PipelineColumn` / `OpportunityCard` / `OpportunityValueFields` per the Frontend Philosophy; render the enriched payload (value fields, names, eligibility); Vitest per component; every element gets an `id`.
- **Open questions / decisions for stakeholders:** none expected — value fields render empty (em-dash) in P2.2 until P2.3 populates them (Risk R2, accepted per D7).
- **Depends on:** Epics 4, 7.
- **Implementation notes:** _none yet_

## Epic 9 — Seed nudge for the Medicare-gate demo
- **Goal:** Make the scripted gate demo (walkthrough step 8) reliable: ensure a converted under-65 Sunshine opportunity on a Medicare line exists, so the agent can demonstrate the block to *Quoted* without ad-hoc data entry.
- **Rough scope:** adjust one Sunshine `SESSION_LEAD_TEMPLATES` entry (DOB/age band or product line) so converting it yields a gated under-65 opportunity; seed-only, no behavior change.
- **Open questions / decisions for stakeholders:** confirm nudging the seed (recommended — cheap, seed-only, gives a deterministic step-8 block) vs leaving the agent to enter such a lead live (Risk R1).
- **Depends on:** Epic 3.
- **Implementation notes:** _none yet_

## Epic 10 — Acceptance suite
- **Goal:** Prove the whole phase end-to-end on the real substrate: the machine (advance through stages, invalid move refused, Lost terminal), the Medicare gate (under-65 blocked from Quoted, allowed at 65+), per-tenant config + the Florida skip, cross-tenant/session isolation, and both events on the outbox carrying `tenant_id` + `demo_session_id` + forwarded `correlation_id`; plus a frontend acceptance block for the board flow.
- **Rough scope:** the named `test_opportunity_pipeline_acceptance.py` against real Postgres + RabbitMQ; a FE acceptance block (board → advance → gate-block → mark lost).
- **Open questions / decisions for stakeholders:** none expected.
- **Depends on:** Epics 1–9.
- **Implementation notes:** _none yet_
