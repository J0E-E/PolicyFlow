# Opportunity Pipeline & Product Rules (P2.2) — Technical Design Document

> **Build strategy:** Tracer bullet — chosen at design time (rationale in §6, D12; locked by the Program & Phase Plan's M2 cross-cutting decision). `3-tdd-to-epic-plan` copies this to the epic plan and `4-plan-epic` honors it (`0-conventions.md` → *Build strategies*).

## 1. Summary
Give a converted opportunity a server-enforced **stage lifecycle**. P2.2 adds an explicit, testable opportunity **state machine** (`New → Qualified → Quoted → Application Started → Submitted → Approved → Policy Active`, plus `(any active) → Lost`), with **per-tenant configuration** (relabel stages, toggle the optional *Quoted* / *Approved* stages) held in the existing tenant **registry** (seed-driven, no live editor). It enforces the **Medicare eligibility gate** (an MA/Medicare opportunity cannot enter *Quoted* unless the customer is age ≥ 65), publishes `opportunity.stage_changed` / `opportunity.lost` via the transactional outbox, and ships a **pipeline board** UI grouped by stage that renders per-tenant labels/toggles and each opportunity's value fields. The two demo tenants are configured to look visibly different on the same board.

## 2. Business Requirements
Source BRD: [./brd-P2.2-opportunity-pipeline-product-rules.md](./brd-P2.2-opportunity-pipeline-product-rules.md). Constraints/clarifications surfaced during design (not already in the BRD):

- **No migration in P2.2.** The `opportunities` table (migration `0015`) already carries `stage` (TEXT, default `'New'`), `estimated_annual_premium`, `target_close_date`, `owner_user_id`, `correlation_id`, `demo_session_id`. Config lives in the registry (D1) and Lost-reason is deferred (D8), so the phase adds **zero** schema changes.
- **"MA/Part D" maps to the Medicare product lines.** Part D is not a modeled product line; the gate applies to the registry lines flagged Medicare (`medicare_advantage`, `medicare_supplement` — both key off 65-eligibility). See D4 + Risk R1.
- **Value fields are display-only and currently null.** P2.1 conversion does not populate them and P2.2 adds no edit UI; they are filled from the selected quote in **P2.3**. The board renders them, showing an em-dash when null. See D7 + Risk R2.
- **Stored stage = canonical English key; tenant labels are render-time overrides.** The stored value (`'New'`, `'Quoted'`, …) is tenant-independent; relabeling only changes display.

## 3. Goals / Non-Goals
**Goals**
- Manual, agent-driven stage transitions, validated **server-side**; invalid moves rejected with a clear reason, opportunity unchanged.
- Per-tenant (seed/registry-driven) stage labels + enabled optional stages; the four anchors always present; disabled-stage **skip** semantics.
- Medicare eligibility gate blocking entry to *Quoted* for under-65 customers, with a distinct rejection reason; enrichment flag never gates.
- `opportunity.stage_changed` + `opportunity.lost` events via the outbox, carrying `tenant_id` + `demo_session_id` + the forwarded `correlation_id`.
- Pipeline board grouped by stage, per-tenant labels/toggles read-only, value fields shown; the two tenants visibly differ.

**Non-Goals (deferred)**
- Application-status → stage **auto-advance coupling**, quotes, applications, policy issuance → **P2.3**.
- Auto-update of `estimated_annual_premium` to the selected quote → **P2.3**.
- Beneficiary / health-question steps → **P2.3** (on the Application).
- Pipeline-value **sorting** + value-by-stage rollups → **M4 [SHOULD]**.
- Editing value fields; reopening a *Lost* opportunity; live stage-config editor; Lost-reason capture (D8).

## 4. Current State
- **Opportunity model** — [core/app/models/opportunity.py](core/app/models/opportunity.py): schema-less ORM bound by `search_path`; `stage` TEXT `server_default 'New'`; value fields nullable; `contact_id`, `household_id`, `owner_user_id`, `correlation_id`, `demo_session_id` present. Table owned by migration `0015`, excluded from `alembic check`.
- **State-machine pattern to mirror** — [core/app/leads/state.py](core/app/leads/state.py): `StrEnum` of statuses + `ALLOWED_TRANSITIONS: frozenset[tuple]` + framework-free `InvalidLeadTransition` + `assert_transition`; pure logic, mapped to HTTP at the edge.
- **Conversion** — [core/app/leads/conversion.py](core/app/leads/conversion.py): creates opportunities at `stage='New'`, `origin='conversion'`, owned by the converting agent, value fields **unset**; emits `opportunity.created`. The `_emit` wrapper (reuse `correlation_id`, `causation_id=None`, ride the request txn) is the event idiom to follow.
- **Events** — [core/app/events/catalog.py](core/app/events/catalog.py): `EventType` StrEnum + `CONSUMER_BINDINGS`; `sync.logger` binds `#` (every event), `enrichment.stub` binds only `record.created`/`lead.created`. Adding new event types needs **no** new consumer (matches the M2 lean-seam decision).
- **Registry (per-tenant SSOT)** — [core/app/tenancy/registry.py](core/app/tenancy/registry.py): frozen `TenantConfig` per tenant holds `product_lines`, `brand_primary_color`, etc.; `tenant_by_schema(...)` resolves the caller's tenant from the active schema. `/api/tenants` ([core/app/demo/router.py](core/app/demo/router.py)) already serves registry-derived data to the FE.
- **Session-visibility helpers to reuse** — `current_demo_session(...)` + `visible_to_session(query, demo_session_id)` (NULL baseline ∪ caller's session) from the leads read path ([core/app/leads/router.py:261](core/app/leads/router.py#L261)); the convert endpoint's holder + write-isolation guard sequence ([core/app/leads/router.py:655](core/app/leads/router.py#L655)).
- **Age band** — [core/app/pii/masking.py:174](core/app/pii/masking.py#L174): Contact stores plaintext `age_band`; `"65+"` is the documented Medicare-eligibility signal (lower-bound inclusive at 65). No decryption needed for the gate.
- **Auth** — [core/app/auth/rbac.py](core/app/auth/rbac.py): `CREATE_EDIT_RECORDS` held by Agent + Tenant Admin only; `require_capability` is the gate dependency.
- **Routers** — mounted in [core/app/main.py:51](core/app/main.py#L51); each package owns an `APIRouter(prefix="/api/...")`.
- **Frontend** — "Opportunities" nav item exists **inert** ([frontend/src/components/navSections.ts:114](frontend/src/components/navSections.ts#L114)); no opportunity UI yet. Design system (Card, Button, StampTag, ExplainerPopover, SimulatedBadge) + AppShell + api client established.

## 5. Proposed Design

### 5.1 Stage machine — new `core/app/opportunities/state.py` (pure logic)
- `OpportunityStage(StrEnum)`: `NEW="New"`, `QUALIFIED="Qualified"`, `QUOTED="Quoted"`, `APPLICATION_STARTED="Application Started"`, `SUBMITTED="Submitted"`, `APPROVED="Approved"`, `POLICY_ACTIVE="Policy Active"`, `LOST="Lost"`.
- `CANONICAL_FORWARD_ORDER` — the ordered active spine: New, Qualified, Quoted, Application Started, Submitted, Approved, Policy Active. `LOST` is off-spine.
- `OPTIONAL_STAGES = frozenset({QUOTED, APPROVED})` (toggleable). `ANCHOR_STAGES = frozenset({NEW, APPLICATION_STARTED, POLICY_ACTIVE, LOST})` (always present). Qualified + Submitted are always-present, non-optional, non-anchor.
- `TERMINAL_STAGES = frozenset({POLICY_ACTIVE, LOST})`. `ACTIVE_STAGES` = forward spine minus `POLICY_ACTIVE` (i.e. everything Lost-able).
- **Enabled set** per tenant = (forward spine minus disabled optional stages). Functions take it as an argument so the machine stays pure:
  - `next_enabled_stage(current, enabled_stages) -> OpportunityStage | None` — the single forward target (next stage in canonical order that is enabled); `None` at `Policy Active`.
  - `allowed_targets(current, enabled_stages) -> set` — `{next_enabled_stage}` (if any) ∪ `{LOST}` when `current` is active.
  - `assert_transition(current, target, enabled_stages)` — raise `InvalidStageTransition(current, target)` (framework-free) unless `target ∈ allowed_targets(...)`.
- **Policy:** forward-by-one-to-next-enabled + any-active → Lost. **No** backward moves, **no** multi-step skips (only the next enabled stage), **no** exits from `Policy Active`/`Lost`. (Backward/decline returns are P2.3's coupling concern.)
- A hand-written `tests/test_opportunity_state.py` asserts members + transitions against an independent expectation (mirrors `test_lead_state.py`).

### 5.2 Per-tenant pipeline config — registry (D1)
- Extend `TenantConfig` ([registry.py](core/app/tenancy/registry.py)) with:
  - `stage_labels: dict[str, str]` — overrides keyed by canonical stage value (absent ⇒ canonical label).
  - `enabled_optional_stages: frozenset[str]` — subset of `{"Quoted", "Approved"}`.
- Extend `ProductLine` with `requires_medicare_age: bool` (default `False`).
- **Resolution helper** — `core/app/opportunities/pipeline.py::resolve_pipeline(tenant_config) -> list[StageView]` returns the **enabled** stages in canonical order with `{key, label, is_optional}` for the board's columns. Pure; reads only the registry.
- **Demo-distinct config** (D13) — concrete values:
  - **Sunshine** (Medicare): `enabled_optional_stages = {Quoted, Approved}`; labels rename e.g. `Qualified→"Needs Assessment"`, `Policy Active→"Enrolled"`. `medicare_advantage` + `medicare_supplement` → `requires_medicare_age=True`.
  - **Florida** (life/health): `enabled_optional_stages = {Quoted}` (**Approved disabled** → demonstrates skip: Submitted → Policy Active directly); labels rename e.g. `Quoted→"Proposal Sent"`, `Application Started→"App In Progress"`. No Medicare lines.

### 5.3 Stage-change action — new `core/app/opportunities/service.py`
- `change_opportunity_stage(db, tenant_id, *, opportunity, target_stage, enabled_stages, actor_*, demo_session_id) -> Opportunity`:
  1. `assert_transition(current, target, enabled_stages)` (caller's endpoint maps the exception to 409).
  2. If `target == QUOTED` and the opportunity is Medicare-gated (its `product_line.requires_medicare_age`) **and** the contact's `age_band != "65+"` → raise `MedicareEligibilityError` (endpoint → 422). Enrichment flag never consulted.
  3. Set `opportunity.stage = target`; flush.
  4. Emit `opportunity.stage_changed` always; **additionally** `opportunity.lost` when `target == LOST`. Both via the `_emit` idiom: reuse the opportunity's `correlation_id`, `causation_id=None`, ride the request txn (no commit here).
- The Medicare check is a small pure helper (`is_blocked_for_medicare(product_line, age_band)`) reused later by P2.3's quote-request path.

### 5.4 API — new `core/app/opportunities/router.py` (`APIRouter(prefix="/api/opportunities")`, mounted in `main.py`)
- `GET /api/opportunities` — guard `require_authenticated` (Read-Only included), `get_tenant_db`. Returns the board payload:
  - `pipeline`: `{ stages: [{key, label, is_optional}, …] }` (enabled stages, canonical order, tenant labels) from `resolve_pipeline`.
  - `opportunities`: list scoped by `visible_to_session` (NULL baseline ∪ caller's session), newest first, each `{id, contact_id, household_id, product_line, product_line_label, stage, estimated_annual_premium, target_close_date, owner_username, contact_first_name, contact_last_name, eligibility: {medicare_gated, age_eligible}}`. Plaintext contact name only (no PII decryption), mirroring the conversion summary.
- `POST /api/opportunities/{id}/stage` — guard `require_capability(CREATE_EDIT_RECORDS)` (Agent/Tenant-Admin), `get_tenant_db`; body `{ "target_stage": "<canonical>" }`. Guards **in order** (mirrors convert):
  1. Load by id in caller's schema; missing/cross-tenant → `404`.
  2. Demo-session write isolation: foreign session → `404`, shared-seed (`demo_session_id IS NULL`) → `409`. Resolved session id reused for events.
  3. **Holder** — owner **or** Tenant Admin may move it; else `403` (D5).
  4. **Transition** — `assert_transition` (tenant enabled set); invalid → `409` (reason names current+target).
  5. **Medicare gate** — target `Quoted` + gated + under-65 → `422` (clear reason).
  6. `change_opportunity_stage(...)`; return the updated opportunity (same shape as a list row) under `{"opportunity": …}`.
  - Marking **Lost** = this endpoint with `target_stage="Lost"`; emits both events.

### 5.5 Events (D9) — `core/app/events/catalog.py`
- Add `OPPORTUNITY_STAGE_CHANGED = "opportunity.stage_changed"`, `OPPORTUNITY_LOST = "opportunity.lost"`. `CONSUMER_BINDINGS` unchanged (sync.logger `#` covers them; no enrichment binding).
- Payloads (non-PII, entity refs only):
  - `opportunity.stage_changed`: `{entity_id, from_stage, to_stage, contact_id, household_id}`.
  - `opportunity.lost`: `{entity_id, from_stage, contact_id, household_id}`.
- `test_event_catalog.py` extended for the two new members.

### 5.6 Frontend — pipeline board at `/app/opportunities`
- Flip `navSections.ts` "opportunities" → `comingLater:false`, `to:"/app/opportunities"`; add the route in `App.tsx` behind the session guard.
- api client: `getOpportunities()`, `changeOpportunityStage(id, targetStage)` + types.
- Components (kept small per Frontend Philosophy; every element gets an `id`):
  - `OpportunityPipelinePage` — fetches board, owns refresh after a move.
  - `PipelineBoard` — renders one `PipelineColumn` per enabled stage (tenant label as heading).
  - `PipelineColumn` — groups its stage's opportunity cards.
  - `OpportunityCard` — contact name, product-line label, `OpportunityValueFields` (premium + close date, em-dash when null), owner; an **Advance** control (to the next enabled stage, labeled with that stage's tenant label) and a **Mark Lost** action.
  - Blocked moves (under-65 Medicare → Quoted) surface the server's reason inline; an `ExplainerPopover` explains the gate + the per-tenant config; a `SimulatedBadge` where appropriate.
- Read-only labels/toggles (no config editor). Tests per component (Vitest).

### 5.7 Primary flow (advance a stage)
`agent clicks Advance` → `POST /api/opportunities/{id}/stage {target}` → guards (load → session-isolation → holder → transition → Medicare) → set stage + emit `stage_changed` (+`lost`) on the request txn → 200 `{opportunity}` → board refetches → card moves column. Outbox relay publishes; `sync.logger` consumes; (P2.5 will render this on an opportunity timeline).

## 6. Decisions

**D1 — Pipeline config lives in the registry, not a DB table.**
Chosen: add `stage_labels` + `enabled_optional_stages` to frozen `TenantConfig`; serve to FE via the board endpoint. Alternatives: a per-tenant `tenant_pipeline_config` table (+ migration, ORM twin, seed, grants). Rationale: the registry is already the seed-driven SSOT and `/api/tenants` already serves registry config to the FE (`brand_primary_color` precedent); "seed-driven, no live editor" is fully satisfied without a table; avoids a migration entirely. No runtime mutability is needed in M2 (P4.3 is only sorting).

**D2 — Stored stage = canonical English key; labels are render-time overrides.**
Chosen: stage column keeps tenant-independent canonical values; relabeling changes display only. Alternatives: store per-tenant display strings; store snake_case keys. Rationale: the existing `'New'` rows are canonical English; keeping canonical keeps the machine, events, and cross-tenant reasoning tenant-independent and avoids rewriting stored data on a relabel.

**D3 — Transition policy: forward-by-one-to-next-enabled + any-active → Lost; no backward, no multi-skip.**
Chosen as above. Alternatives: allow arbitrary/backward moves now. Rationale: matches the BRD success criteria (advance + Lost), keeps the demo deterministic, and leaves backward/decline returns to P2.3's coupling rule where they actually originate. Disabled optional stages are skipped by "next *enabled*".

**D4 — Medicare gate keys off `product_line.requires_medicare_age` + `contact.age_band == "65+"`, blocks entry to *Quoted*, returns 422.**
Chosen: a `requires_medicare_age` flag on `ProductLine` (True for `medicare_advantage` + `medicare_supplement`); plaintext `age_band` check (no decryption); enrichment flag ignored. Alternatives: hardcode product-line keys in the rule; decrypt DOB and compute exact age. Rationale: the flag keeps the gated set declarative in the SSOT and extensible; `age_band_for` is *designed* so `"65+"` is the Medicare signal, so the plaintext band is authoritative and PII-free. 422 (precondition unmet) distinguishes the gate from a 409 structurally-invalid move, matching the convert endpoint's 422/409 split. *(Quote-request blocking is the same rule reused in P2.3, where the quote surface exists.)*

**D5 — Authorization: `CREATE_EDIT_RECORDS` + holder = owner OR Tenant Admin.**
Chosen: capability gate (Agent + Tenant Admin) then a handler check allowing the opportunity's owner or any Tenant Admin; else 403. Alternatives: owner-only (like convert); capability-only (no holder check). Rationale: BRD §5 explicitly lets Tenant Admins change stages; owner-or-admin matches that while keeping Read-Only/Platform-Admin out via the capability.

**D6 — Reuse the lead session-isolation pattern for opportunities.**
Chosen: `visible_to_session` for the list; a load→foreign-session-404→seed-409 guard for the mutation; reuse the resolved session id to stamp events. Rationale: opportunities are session-tagged like leads; one consistent isolation predicate; honors walkthrough step 18.

**D7 — Value fields are display-only; render em-dash when null; populated in P2.3.**
Chosen: P2.2 does not set or edit them. Alternatives: populate a deterministic placeholder at conversion (touches P2.1-owned code, conflicts with "set from quote in P2.3"). Rationale: matches the locked rung-1 decision; minimal scope; the board still "displays" the fields. See Risk R2.

**D8 — Defer Lost-reason capture → no migration.**
Chosen: Lost is a plain transition to a terminal stage; no reason column. Alternatives: add a nullable `lost_reason` (needs a migration on the `0015` table). Rationale: BRD open question leaned defer; reason belongs with renewals/reporting; keeping it out makes P2.2 migration-free.

**D9 — Two new event types, no new consumer.**
Chosen: add `opportunity.stage_changed` + `opportunity.lost`; `sync.logger` `#` covers them. Rationale: the M2 lean-seam decision — publish the real seam, wire no throwaway stub; the timeline only synthesizes reactions for bound consumers, keeping the M2 timeline honest.

**D10 — One board read + one mutation endpoint; Lost via `target_stage="Lost"`.**
Chosen: `GET /api/opportunities` (board: config + opportunities) and `POST /api/opportunities/{id}/stage`. Alternatives: separate config endpoint; a dedicated `/lost` route. Rationale: one round-trip populates the board; Lost is just another valid target, so one mutation path covers it (emitting both events).

**D11 — Pipeline board grouped by stage at `/app/opportunities`, flipping the existing inert nav item.**
Rationale: the nav already previews "Opportunities"; the BRD asks for a stage-grouped board with per-tenant labels and value fields; small components per the Frontend Philosophy.

**D12 — Build strategy: tracer bullet (locked by the Program & Phase Plan, M2).**
Chosen: thinnest customer-visible thread first (advance one converted opportunity one stage, server-validated, event emitted, board updates), then layer machine completeness, config, gate, Lost, isolation. Rationale: the requirements/UX carry the risk more than the architecture (events/outbox/isolation are all proven seams), so feedback-first beats skeleton-first; consistent with every M1/M2 phase.

**D13 — The two tenants are configured visibly different (labels + enabled stages).**
Chosen: Sunshine enables both optional stages with Medicare relabels; Florida disables *Approved* (proving skip) with its own relabels. Rationale: satisfies the demo-difference + skip-semantics requirements with registry data alone.

**D14 — Manual reach of automation-owned stages is allowed in P2.2 (interim).**
Chosen: an agent may manually advance all the way to *Policy Active* through the canonical machine; no special gating beyond transition validity + the Medicare gate. Rationale: lets the full machine be demoed before P2.3's auto-advance coupling exists (confirmed open question).

## 7. Risks and Open Questions
- **R1 — Demonstrable Medicare block needs an under-65 Sunshine Medicare opportunity.** Current Sunshine session-lead seed has no clean under-65 lead on a Medicare line (the under-65 persona, Priya, is on `dental_vision_hearing`). Mitigation: during the demo the agent can enter such a lead, **or** adjust one Sunshine `SESSION_LEAD_TEMPLATES` entry (DOB or product line) so converting it yields a gated under-65 opportunity. **Decide at epic-plan time** whether to nudge the seed (cheap, seed-only) — recommended for a reliable scripted step 8.
- **R2 — Value fields display empty in P2.2** (nothing populates them until P2.3 quotes). The board shows em-dashes. Accepted per D7; flagged so the operator can choose otherwise at epic time.
- **R3 — "MA/Part D" vs modeled lines.** Part D isn't a product line; the gate covers `medicare_advantage` + `medicare_supplement`. Confirm this gated set matches intent (D4).
- **R4 — Shared full-suite flakes** (rate-limiter / duplicate-matcher singletons on the shared container) are pre-existing; re-run in isolation before treating a 1–2 test failure as a regression (P1.9 gotcha).

## 8. Rollout / Verification
- **No migration, no feature flag, no backwards-compat concern** — additive code + registry config only; the `opportunities` table is unchanged.
- **Manual verification (walkthrough step 8):** convert a qualified lead (P2.1) → open `/app/opportunities` → advance the opportunity `New → … → Policy Active`; confirm an invalid move is refused (server 409); mark one Lost from an active stage and confirm it's terminal. For Sunshine, convert an under-65 Medicare lead and confirm it's blocked from *Quoted* with a visible reason, then allowed once the customer is 65+.
- **Isolation (step 18):** switch tenants and confirm different stage labels / enabled stages on the same board, and that Tenant 1's opportunities are absent for Tenant 2.
- **Events:** confirm `opportunity.stage_changed` (+ `opportunity.lost`) appear on the outbox with `tenant_id` + `demo_session_id` + forwarded `correlation_id`.
- **Gates:** green-gate (backend pytest on real Postgres+RabbitMQ; frontend Vitest; `tsc -b && vite build`); a named `test_opportunity_pipeline_acceptance.py` proves the machine, gate, per-tenant config/skip, isolation, and events end-to-end.

## 9. Work Breakdown
Tracer-bullet order — first item is the thinnest customer-visible end-to-end slice through all layers; then layer complexity. Small-and-layered.

1. **Stage vocabulary + machine** — `opportunities/state.py` (`OpportunityStage`, canonical order, optional/anchor/terminal sets, `next_enabled_stage`/`allowed_targets`/`assert_transition`, `InvalidStageTransition`) + `test_opportunity_state.py`.
2. **Tracer slice — advance one stage end-to-end** — minimal `GET /api/opportunities` (flat list, no config yet) + `POST /api/opportunities/{id}/stage` with capability + holder + transition guards (no optional-skip, no Medicare yet) + `change_opportunity_stage` emitting `opportunity.stage_changed`; mount router; add the two event types; a minimal `/app/opportunities` board that lists cards and advances one stage. (Pierces machine→service→events→API→UI.)
3. **Registry config + resolution** — `stage_labels` + `enabled_optional_stages` on `TenantConfig`; `requires_medicare_age` on `ProductLine`; `pipeline.py::resolve_pipeline`; configure Sunshine/Florida distinctly (D13).
4. **Enabled-set skip semantics** — feed the tenant's enabled set into the machine + endpoint so disabled optional stages are skipped; board renders enabled stages with tenant labels.
5. **Medicare eligibility gate** — `is_blocked_for_medicare` helper; 422 on `→ Quoted` for under-65 gated opportunities; board surfaces the reason + explainer.
6. **Mark Lost** — `target_stage="Lost"` path emits `opportunity.lost` (+`stage_changed`); board "Mark Lost" action; terminal enforcement.
7. **Demo-session write isolation + board read hardening** — `visible_to_session` on the list, foreign-404/seed-409 on the mutation; eligibility + value fields + contact name in the list payload.
8. **Board UI polish** — group-by-stage columns, value-field rendering (em-dash when null), per-card advance/lost controls, SimulatedBadge/ExplainerPopover, component tests; flip nav item + route.
9. **(Optional, R1) Seed nudge** — adjust one Sunshine session-lead template so a converted under-65 Medicare opportunity exists for the scripted gate demo.
10. **Acceptance suite** — `test_opportunity_pipeline_acceptance.py` (machine + gate + per-tenant config/skip + isolation + events on the real substrate) + frontend acceptance block.
