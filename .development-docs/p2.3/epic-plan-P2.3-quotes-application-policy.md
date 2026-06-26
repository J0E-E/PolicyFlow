# Quotes → Application → Policy — Epic Plan

Source TDD: [./tdd-P2.3-quotes-application-policy.md](./tdd-P2.3-quotes-application-policy.md)

> **Review budget:** ~300 changed lines · ~16 non-generated files · one focused commit per epic. Tunable per project.

> **Build strategy:** Tracer bullet — copied from the TDD; `4-plan-epic` orders each epic's phases by it (`0-conventions.md` → *Build strategies*).

> High-level agile roadmap. Each epic's design specifics are confirmed with stakeholders at epic time (`4-plan-epic`) before any code is written.

## Epic 1 — Event vocabulary + catalog binding — **COMPLETED** (5m59s)
- **Goal:** Add the seven new domain event types and the single new consumer binding so every later epic can publish/consume on a real seam. No behavior change yet — just the vocabulary.
- **Rough scope:** The event catalog: the `EventType` members (`quote.requested`, `quote.completed`, `application.started`, `application.submitted`, `application.approved`, `application.declined`, `policy.created`) and the `carrier.quote` → `quote.requested` binding; `sync.logger` continues to cover everything. Update the catalog test.
- **Open questions / decisions for stakeholders:** none — resolved at plan time.
- **Depends on:** none.
- **Implementation notes:** _none — pure-vocabulary epic; the 7 `EventType` members + `carrier.quote→quote.requested` binding are already specified for the epics that consume them._

## Epic 2 — Carrier/product catalog in the registry — **COMPLETED** (11m13s)
- **Goal:** Extend the registry with the per-tenant carriers and per-product option templates the quote stub will read, plus the two new per-product/per-tenant flags later epics key on — pure config, zero migration.
- **Rough scope:** Registry config only: carriers + a per-`ProductLine` tuple of 2–3 option templates (`carrier`, `product_label`, `coverage_amount`, `premium_monthly`; annual = monthly × 12); the `ProductLine.application_step` attribute and the `TenantConfig.collects_medicare_id` flag; registry tests.
- **Open questions / decisions for stakeholders:** none — resolved at plan time (catalog content auto-picked: plausible demo carriers + coverage/premium numbers, table in the plan; shape locked by D4).
- **Depends on:** none.
- **Implementation notes:** _none — pure registry data. `QuoteOptionTemplate` (with derived `premium_annual` property) + `ProductLine.{application_step,quote_options}` + `TenantConfig.{carriers,collects_medicare_id}` consumed by Epic 3 (stub reads `quote_options`), Epic 6 (`application_step`), Epic 11 (`collects_medicare_id`)._

## Epic 3 — Quote round-trip tracer [UI] — **COMPLETED** (34m00s)
- **Goal:** The thinnest customer-visible end-to-end slice: from a *Qualified* opportunity an agent requests quotes, watches the broker round-trip go pending → completed, and sees the canned options attach — moving the opportunity to *Quoted*.
- **Rough scope:** Migration 0016 for `quote_requests` + `quotes` (with grants); the new **non-terminal** `carrier.quote` consumer (parallel consume path running own-session as the tenant role, registry-driven option generation, `quote_request_id` dedupe, emits `quote.completed`); the request + poll endpoints; opportunity → *Quoted* on first completion; minimal agent-workspace UI (request control, polling status, quote list) reusing the P1.9 poll idiom.
- **Open questions / decisions for stakeholders:** none — resolved at plan time.
- **Depends on:** Epic 1, Epic 2.
- **Implementation notes:**
  - _New `app/quotes/` service (`request_quotes` + `complete_quote_request`) + `QuoteRequest`/`Quote` ORM models + migration 0016 land here; Epics 5/7/8 extend the service and add the applications/policies tables in follow-on migrations._
  - _The agent-workspace **opportunity detail page** (`/app/opportunities/:id`, reuses the board fetch — no single-opportunity GET endpoint) is introduced here; Epics 5/6/7/8/11 extend this same page._
  - _**DEVIATION from TDD §5.4.4:** the opportunity → *Quoted* move rides the **`carrier.quote` consumer's** completing transaction, not the poll endpoint — this keeps the GET poll a pure read so a Read-Only viewer polling never triggers a mutation (resolving the §5.9 "Read-Only, no actions" tension). The consumer advances *Qualified → Quoted* directly (a normal forward stage, gate already cleared at request); Epic 5 formalizes this as the internal stage-setter for the automation-owned stages._
  - _The `POST …/quote-requests` endpoint requires the opportunity at *Qualified* (409 otherwise) — the coherent round-trip precondition; re-quote from later stages is deferred (D11)._

## Epic 4 — Application state machine — **COMPLETED** (2m59s)
- **Goal:** The pure, framework-free application lifecycle machine — the single source of truth for valid status transitions — landed and tested before any code creates an application.
- **Rough scope:** A pure `applications/state.py` mirroring the opportunities precedent: `ApplicationStatus` (`Draft`, `Submitted`, `Approved`, `Declined`, `Superseded`), the transition rules, the *Active* set, and a framework-free invalid-transition error; unit tests. No DB, no endpoints.
- **Open questions / decisions for stakeholders:** none — resolved at plan time.
- **Depends on:** none.
- **Implementation notes:** _none — pure static machine (`app/applications/state.py`: `ApplicationStatus`, `ALLOWED_TRANSITIONS`, `ACTIVE_STATUSES`={Draft,Submitted}, `TERMINAL_STATUSES`={Approved,Superseded}, `assert_transition`). Mirrors the lead machine (static, no tenant arg) since the application machine is tenant-independent. Consumed by Epic 5 (select→Draft), Epic 7 (submit/decision), Epic 10 (supersession)._

## Epic 5 — Quote selection → Application (Draft) [UI] — **COMPLETED** (18m34s)
- **Goal:** Selecting an attached quote creates a `Draft` Application (carrier/product/coverage/premium copied from the quote), advances the opportunity to *Application Started*, and updates its estimated annual premium.
- **Rough scope:** `applications` table (minimal columns) in migration 0016; the select endpoint; the **internal stage-setter** mechanism (writes the opportunity stage directly + emits, bypassing the manual machine) introduced here for the *Application Started* move; `application.started` emission; minimal UI to select a quote and see the Application created.
- **Open questions / decisions for stakeholders:** none — resolved at plan time.
- **Depends on:** Epic 3, Epic 4.
- **Implementation notes:**
  - _**Internal stage-setter** `opportunities/service.py::set_stage_internal` lands here (D6) — writes `opportunity.stage` directly + emits, bypassing `assert_transition` + the Medicare gate. The mechanism Epics 5–8 drive the **automation-owned** stages with; Epic 9's manual lockdown must stay **purely additive** to it._
  - _**Migration moved to 0017** (the plan said "0016", but Epic 3 took 0016 for the quote tables). The `applications` table is created with the **full D5 column set** (beneficiary/health_answers/medicare_id_encrypted/decision/decided_at/superseded_by) so Epics 6/7/10/11 **populate** columns rather than each ALTER-ing. The partial-unique "one-active" index is **Epic 10's** deliverable, not here._
  - _The select endpoint (`POST …/applications`) requires the opportunity at *Quoted* (409 otherwise). UI selection works within the live session right after the round-trip; reloading a *Quoted* opp to select later is not supported (no list-quote-requests-for-opportunity endpoint — the generalized read is P2.5), same limitation as Epic 3's quote reload._

## Epic 6 — Product-specific application step [UI] — **COMPLETED** (19m02s)
- **Goal:** Capture the product-specific step on a Draft application — beneficiary details or health questions, chosen by the product line — so the application carries what submission needs.
- **Rough scope:** The update endpoint capturing `beneficiary` / `health_answers` (jsonb) per the product line's `application_step`; the agent-workspace step form. (Medicare-ID capture is Epic 11.)
- **Open questions / decisions for stakeholders:** none — resolved at plan time (content: beneficiary `{full_name, relationship, date_of_birth}`; 5 yes/no health questions — keys in `app/applications/steps.py`).
- **Depends on:** Epic 5.
- **Implementation notes:**
  - _**New `/api/applications` router** (`PATCH /{id}`) mounted in `main.py` — Epics 7/11 add submit + Medicare-reveal under it. The step contract is `app/applications/steps.py` (`BENEFICIARY_FIELDS`, `HEALTH_QUESTION_KEYS`, `application_step_for`); the FE `ApplicationStep.tsx` renders the matching keys/prompts._
  - _**Shared application serializer** `app/applications/read.py::serialize_application` is now the single application wire shape — the create endpoint (Epic 5) switched to it and the old `opportunities/router._application_row` was removed. The application response now carries `application_step` + `beneficiary` + `health_answers` so the workspace knows which step form to render._
  - _**Flake fix (folded in):** the broker drain helpers (`drain_for_event_id` / `deliver_for_event_id` in `test_demo_session_acceptance.py` + `test_event_bus_acceptance.py`) capped at `max_messages=50`, but `publish_pending_once` flushes the **whole suite's** accumulated unpublished outbox and `sync.logger` binds `#`, so under full-suite load the target event sat past position 50 in the backlog → intermittent "event never arrived on sync.logger". Raised the budget to 5000 (+ reset the consecutive-empty counter, + a bounded async-publish wait). Pre-existing latent issue surfaced by the growing suite; validated green over the full suite._

## Epic 7 — Submit + inline carrier decision [UI] — **COMPLETED** (14m51s)
- **Goal:** Submitting an application runs the deterministic inline carrier decision (approved by default; declined when the contact's email contains `deny`) and couples the outcome to the opportunity stage.
- **Rough scope:** The submit endpoint (`Draft → Submitted`, opportunity → *Submitted*, `application.submitted`); the inline decision (decrypt the contact email, `deny` substring → declined, value never logged/returned); on approve → `application.approved` + opportunity advance via the internal stage-setter; on decline → `application.declined`. (Policy issuance is Epic 8; the full decline → supersession loop is Epic 10.)
- **Open questions / decisions for stakeholders:** none — resolved at plan time.
- **Depends on:** Epic 6.
- **Implementation notes:**
  - _`POST /api/applications/{id}/submit` → `applications/service.py::submit_application`: Draft→Submitted (opp→Submitted via setter, `application.submitted`), then the inline decision — `decrypt_field(tenant_id, contact.email_encrypted)`, `deny` substring → declined. The plaintext is used only for the membership test, never stored/logged/returned; only the outcome is stored on `Application.decision` (`approved`/`declined`) + `decided_at`. Approve → `application.approved` + opp→**Approved** via the setter (Epic 8 adds policy issuance + Policy Active on this approve path). Decline → `application.declined`, opp left at **Submitted** (Epic 10 returns it to Quoted)._
  - _Submit requires the product step **complete** (409 otherwise) — a line with a step must have captured it. `serialize_application` now also returns `decision` + `decided_at`._

## Epic 8 — Policy issuance [UI] — **COMPLETED** (14m56s)
- **Goal:** On approval, an issued Policy lands atomically in the same transaction with a human-readable number, and the opportunity reaches *Policy Active* — the customer-visible end of the happy path.
- **Rough scope:** `policies` table (follow-on migration); auto-issue on approval (create the row + `policy.created`); deterministic policy number derived from the application; opportunity → *Approved* → *Policy Active* via the internal stage-setter; the agent-workspace policy view.
- **Open questions / decisions for stakeholders:** none — resolved at plan time.
- **Depends on:** Epic 7.
- **Implementation notes:**
  - _Migration **0018** (policies). New `app/policies/` package: `service.py::issue_policy` (+ `policy_number` helper) + `read.py::serialize_policy`. Issuance hooks into `submit_application`'s **approve branch** (D8) — create the policy + `policy.created` + opp → *Policy Active* via the setter, all in the approve transaction. `submit_application` now returns `(application, policy|None)` and takes a `policy_prefix`._
  - _Policy number `POL-<PREFIX>-<YEAR>-<6HEX>`: PREFIX = `schema_name[:3].upper()` (Sunshine `SUN`, Florida `FLO`), YEAR = current year, 6HEX = first 6 of the application uuid (deterministic given the app, C6). The submit response now also carries `policy`._
  - _Policy view (`PolicySummary`) shown **in-session** after issuance (no GET-policy endpoint — same reload limitation as quotes/applications; the generalized read is P2.5). Epic 7's approve test updated here (opp now → *Policy Active*, response carries the policy)._

## Epic 9 — Application↔Opportunity coupling lockdown [UI] — **COMPLETED** (20m37s)
- **Goal:** Make automation-owned stages unreachable by the manual machine — the manual stage endpoint rejects them and the board never offers an Advance that would fail — and migrate the pre-existing P2.2 stage tests that this breaks.
- **Rough scope:** `AUTOMATION_OWNED_STAGES`; the manual `POST /opportunities/{id}/stage` endpoint rejects any target in the set (422); the board suppresses its Advance control when the next stage is automation-owned; **update the affected P2.2 stage/pipeline tests** that previously advanced manually into those stages (TDD R2). The internal stage-setter itself already exists (Epic 5) — this epic is the manual-side lockdown only.
- **Open questions / decisions for stakeholders:** none — **confirmed clean** at plan time: every Epic 5–8 automation move uses `set_stage_internal` (never the manual `POST /stage`), so the lockdown is purely additive.
- **Depends on:** Epic 8.
- **Implementation notes:**
  - _`AUTOMATION_OWNED_STAGES` + `AutomationOwnedStageError` in `opportunities/state.py`. The **manual** `change_opportunity_stage` rejects an automation-owned target **after** `assert_transition` (so an illegal move stays **409**, only a *legal* move into a lifecycle-driven stage is the **422**); `set_stage_internal` (the automation path) bypasses it. The board row gained `can_advance` (false when `next_stage` is automation-owned); `OpportunityCard` suppresses Advance accordingly._
  - _**Migrated the P2.2 tests (R2)** broken by the lockdown: `test_machine_walks_the_full_enabled_spine` → walks the manual spine (→Quoted) then asserts *Application Started* 422s; `test_florida_submitted_skips...` / `test_sunshine_submitted...` / `test_florida_board_config_and_approved_skip` → legal manual advances into automation-owned stages now assert 422 + `can_advance` false. FE test row-helpers gained `can_advance`._

## Epic 10 — Decline → supersession [UI] — **COMPLETED** (19m47s)
- **Goal:** A declined application is retained read-only and returns the opportunity to *Quoted* (else *Qualified*); selecting a different attached quote creates a fresh Draft and marks the prior declined application Superseded — with one active application per opportunity enforced.
- **Rough scope:** Decline-path opportunity return; supersession on re-selection (`Declined → Superseded`, link the superseding application); service-level one-active enforcement plus the partial unique index backstop; the UI for re-selecting after a decline.
- **Open questions / decisions for stakeholders:** none — resolved at plan time.
- **Depends on:** Epic 7 (decline path), Epic 8 (issuance reused on re-approval).
- **Implementation notes:**
  - _**Migration 0019** — partial unique index `(opportunity_id) WHERE status IN ('Draft','Submitted')` (one-active backstop, C5). **Gotcha:** alembic revision ids must be ≤32 chars (`alembic_version.version_num` is `varchar(32)`) — the first id was 33 chars and failed `upgrade head` at test setup; shortened to `0019_one_active_index`._
  - _`select_quote` now enforces **one active** (`OneActiveApplicationError` → 409) and **supersedes** any `Declined` application on re-selection (`Declined → Superseded` + `superseded_by_application_id`). `submit_application`'s decline branch returns the opportunity to `decline_return_stage` (*Quoted* if enabled else *Qualified*) via `set_stage_internal` (a backward move) — so the Epic 7 decline test was updated (opp now → *Quoted*)._
  - _FE: the detail page re-enables quote **Select** when the application is `null` **or** `Declined`, and clears the policy view on re-select. (The deny-contact thread keeps declining on re-submit — re-approval reuses Epic 8's issuance for a non-deny contact; the full end-to-end re-approval is Epic 14's acceptance.)_

## Epic 11 — Medicare ID (Tenant-1) [UI] — **COMPLETED** (25m00s)
- **Goal:** For Tenant 1, the agent enters a Medicare ID during the application step; it is encrypted at rest, masked by default on Application and Policy reads, and revealed only through an audited capability-gated endpoint. Tenant 2 never sees the field.
- **Rough scope:** Encrypt on capture (reusing the P1.3 field encryption); masked render on Application + Policy; the reveal endpoint mirroring the leads-reveal pattern (capability → decrypt → audit seam → return); field presence gated by `collects_medicare_id`; the masked + click-to-reveal UI.
- **Open questions / decisions for stakeholders:** none — resolved at plan time.
- **Depends on:** Epic 6 (the step that captures it), Epic 8 (Policy read masking).
- **Implementation notes:**
  - _`PATCH /api/applications/{id}` now also captures `medicare_id` — `encrypt_field` on capture, gated on `collects_medicare_id` (Tenant-2 → 422). `serialize_application` gained `collects_medicare_id` + `medicare_id_masked` (the masked value, never plaintext); `serialize_policy` gained `medicare_id_masked` (from its application — the policy stores none). The PATCH validation was restructured so a no-step Sunshine line (e.g. medicare_advantage) can capture the Medicare ID alone._
  - _**Reveal:** `POST /api/applications/{id}/reveal-medicare-id` (`REVEAL_PII` → `decrypt_field` → `on_pii_revealed(db, identity, "application", id, "medicare_id")` → return) — entity_type is a free string, no audit-enum change. `_guard_application_for_session` gained `refuse_seed` (the reveal allows seed reads, the leads precedent)._
  - _FE: `MedicareReveal` (masked + click-to-reveal) on the application + policy views; `ApplicationStep` gained a Medicare input (also renders standalone for no-step Sunshine lines). Capture is **optional** — it does not gate submit._

## Epic 12 — Demo-session isolation — **COMPLETED** (12m13s)
- **Goal:** Every new record and the quote stub respect demo-session isolation — a visitor never sees or mutates another session's quotes, applications, or policies, and the stub propagates the session through the round-trip.
- **Rough scope:** `demo_session_id` on all four tables; `visible_to_session` reads and the foreign-404 / seed-409 mutation guards applied across the new endpoints (the opportunities-router trio); the `carrier.quote` stub propagating `demo_session_id` (and `correlation_id`) from the envelope.
- **Open questions / decisions for stakeholders:** none — resolved at plan time.
- **Depends on:** Epic 8 (all four record types exist), Epic 3 (the stub).
- **Implementation notes:**
  - _The isolation guards (`_guard_opportunity_for_session` / `_guard_application_for_session` / `_scope_to_session`) and the stub's `demo_session_id` + `correlation_id` propagation were applied **as each endpoint was built** (Epics 3/5/6/7/11); this epic **verifies** them with acceptance tests (cross-session 404, stub propagation)._
  - _**Gap closed:** the demo-**purge** engine (`app/demo/purge.py`) did not sweep the 4 new tables — a reset would have orphaned them. Added `policies` / `applications` / `quotes` / `quote_requests` to the per-tenant sweep (children-first, no FKs) + 4 `PurgeCounts` fields. The migrations already granted `demo_purge` SELECT+DELETE on all four._

## Epic 13 — Seed — **COMPLETED** (23m44s)
- **Goal:** Seed coherent quote/application/policy demo data plus the prerequisite contact whose decrypted email contains `deny`, so both the happy path and the decline thread are demoable and the acceptance suite has its fixtures.
- **Rough scope:** Per-tenant + per-session seed for the new record types fitting the existing shared-baseline / per-session story; the `deny@…` decline contact (contacts have no email-edit path, so this is seed-only — TDD R3/C4).
- **Open questions / decisions for stakeholders:** none — resolved at plan time.
- **Implementation notes:**
  - _**The `deny@` decline fixture** is a **session-queue** lead added to **both** tenants' `SESSION_LEAD_TEMPLATES` (Sunshine `darnell.deny@…`/final_expense, Florida `bianca.deny@…`/term_life). It must be a session lead (not shared baseline) so a **live session can convert it** (converting a shared seed lead is a seed-409); the line is non-Medicare-gated so the round-trip is unblocked. The Priya under-65 seed-nudge precedent._
  - _The session queue is now **5 per tenant** (was 4) — **migrated ~20 count assertions** across 6 demo/session test files (`== 4`→`5`, totals `8`→`10`, `16`→`20`), leaving `ledger_deleted` untouched. Analogous to the P2.2 test migration (R2)._
  - _**CONTENT DECISION — no seeded quote/application/policy chains.** The seed model is leads → **interactive** conversion (it seeds no converted opportunities/contacts), so completed money-path records would need seeded converted opportunities the seed does not create. The money path is created **interactively** (the demo) and by Epic 14's acceptance, so seeded depth is out of scope; the `deny@` fixture is the critical seeded prerequisite._

## Epic 14 — Acceptance suite
- **Goal:** A named acceptance suite proving both threads end-to-end on the real Postgres + RabbitMQ substrate — happy path to issued Policy and decline → supersession → re-approval — plus the coupling and tenant/session isolation proofs.
- **Rough scope:** The end-to-end happy-path and decline/supersession threads; the coupling proof (status moves advance the opportunity, manual reach into automation-owned stages rejected); the isolation proofs (Tenant-1 records absent in Tenant-2, no Medicare field in Tenant-2, cross-session invisibility).
- **Open questions / decisions for stakeholders:** none expected.
- **Depends on:** Epic 11, Epic 12, Epic 13.
- **Implementation notes:** _none yet_
