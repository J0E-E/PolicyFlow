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

## Epic 4 — Application state machine
- **Goal:** The pure, framework-free application lifecycle machine — the single source of truth for valid status transitions — landed and tested before any code creates an application.
- **Rough scope:** A pure `applications/state.py` mirroring the opportunities precedent: `ApplicationStatus` (`Draft`, `Submitted`, `Approved`, `Declined`, `Superseded`), the transition rules, the *Active* set, and a framework-free invalid-transition error; unit tests. No DB, no endpoints.
- **Open questions / decisions for stakeholders:** none expected — states and transitions fixed in TDD §5.2/D5.
- **Depends on:** none.
- **Implementation notes:** _none yet_

## Epic 5 — Quote selection → Application (Draft) [UI]
- **Goal:** Selecting an attached quote creates a `Draft` Application (carrier/product/coverage/premium copied from the quote), advances the opportunity to *Application Started*, and updates its estimated annual premium.
- **Rough scope:** `applications` table (minimal columns) in migration 0016; the select endpoint; the **internal stage-setter** mechanism (writes the opportunity stage directly + emits, bypassing the manual machine) introduced here for the *Application Started* move; `application.started` emission; minimal UI to select a quote and see the Application created.
- **Open questions / decisions for stakeholders:** none expected — selection + premium-update behavior locked (TDD §5.5/D6).
- **Depends on:** Epic 3, Epic 4.
- **Implementation notes:** _none yet_

## Epic 6 — Product-specific application step [UI]
- **Goal:** Capture the product-specific step on a Draft application — beneficiary details or health questions, chosen by the product line — so the application carries what submission needs.
- **Rough scope:** The update endpoint capturing `beneficiary` / `health_answers` (jsonb) per the product line's `application_step`; the agent-workspace step form. (Medicare-ID capture is Epic 11.)
- **Open questions / decisions for stakeholders:** the **content** of the step — the exact beneficiary fields and the 3–5 health questions per product line (TDD R4/D10, deliberately left for epic time).
- **Depends on:** Epic 5.
- **Implementation notes:** _none yet_

## Epic 7 — Submit + inline carrier decision [UI]
- **Goal:** Submitting an application runs the deterministic inline carrier decision (approved by default; declined when the contact's email contains `deny`) and couples the outcome to the opportunity stage.
- **Rough scope:** The submit endpoint (`Draft → Submitted`, opportunity → *Submitted*, `application.submitted`); the inline decision (decrypt the contact email, `deny` substring → declined, value never logged/returned); on approve → `application.approved` + opportunity advance via the internal stage-setter; on decline → `application.declined`. (Policy issuance is Epic 8; the full decline → supersession loop is Epic 10.)
- **Open questions / decisions for stakeholders:** none expected — the decision rule is locked (TDD §5.6/D7).
- **Depends on:** Epic 6.
- **Implementation notes:** _none yet_

## Epic 8 — Policy issuance [UI]
- **Goal:** On approval, an issued Policy lands atomically in the same transaction with a human-readable number, and the opportunity reaches *Policy Active* — the customer-visible end of the happy path.
- **Rough scope:** `policies` table (follow-on migration); auto-issue on approval (create the row + `policy.created`); deterministic policy number derived from the application; opportunity → *Approved* → *Policy Active* via the internal stage-setter; the agent-workspace policy view.
- **Open questions / decisions for stakeholders:** none expected — issuance + number scheme locked (TDD §5.5/D8).
- **Depends on:** Epic 7.
- **Implementation notes:** _none yet_

## Epic 9 — Application↔Opportunity coupling lockdown [UI]
- **Goal:** Make automation-owned stages unreachable by the manual machine — the manual stage endpoint rejects them and the board never offers an Advance that would fail — and migrate the pre-existing P2.2 stage tests that this breaks.
- **Rough scope:** `AUTOMATION_OWNED_STAGES`; the manual `POST /opportunities/{id}/stage` endpoint rejects any target in the set (422); the board suppresses its Advance control when the next stage is automation-owned; **update the affected P2.2 stage/pipeline tests** that previously advanced manually into those stages (TDD R2). The internal stage-setter itself already exists (Epic 5) — this epic is the manual-side lockdown only.
- **Open questions / decisions for stakeholders:** confirm the lockdown is **purely additive** to the automation path — nothing in Epics 5–8 reaches a stage via the manual endpoint in a way this lockdown would retro-break (reviewer's check; expected clean since the automation path uses the internal setter).
- **Depends on:** Epic 8.
- **Implementation notes:** _none yet_

## Epic 10 — Decline → supersession [UI]
- **Goal:** A declined application is retained read-only and returns the opportunity to *Quoted* (else *Qualified*); selecting a different attached quote creates a fresh Draft and marks the prior declined application Superseded — with one active application per opportunity enforced.
- **Rough scope:** Decline-path opportunity return; supersession on re-selection (`Declined → Superseded`, link the superseding application); service-level one-active enforcement plus the partial unique index backstop; the UI for re-selecting after a decline.
- **Open questions / decisions for stakeholders:** none expected — supersession + return-target rules locked (TDD §5.5/D11/C3).
- **Depends on:** Epic 7 (decline path), Epic 8 (issuance reused on re-approval).
- **Implementation notes:** _none yet_

## Epic 11 — Medicare ID (Tenant-1) [UI]
- **Goal:** For Tenant 1, the agent enters a Medicare ID during the application step; it is encrypted at rest, masked by default on Application and Policy reads, and revealed only through an audited capability-gated endpoint. Tenant 2 never sees the field.
- **Rough scope:** Encrypt on capture (reusing the P1.3 field encryption); masked render on Application + Policy; the reveal endpoint mirroring the leads-reveal pattern (capability → decrypt → audit seam → return); field presence gated by `collects_medicare_id`; the masked + click-to-reveal UI.
- **Open questions / decisions for stakeholders:** none expected — the reveal pattern + registry gating are locked (TDD §5.7/D9).
- **Depends on:** Epic 6 (the step that captures it), Epic 8 (Policy read masking).
- **Implementation notes:** _none yet_

## Epic 12 — Demo-session isolation
- **Goal:** Every new record and the quote stub respect demo-session isolation — a visitor never sees or mutates another session's quotes, applications, or policies, and the stub propagates the session through the round-trip.
- **Rough scope:** `demo_session_id` on all four tables; `visible_to_session` reads and the foreign-404 / seed-409 mutation guards applied across the new endpoints (the opportunities-router trio); the `carrier.quote` stub propagating `demo_session_id` (and `correlation_id`) from the envelope.
- **Open questions / decisions for stakeholders:** none expected — the isolation trio is reused verbatim (TDD §5 / D13).
- **Depends on:** Epic 8 (all four record types exist), Epic 3 (the stub).
- **Implementation notes:** _none yet_

## Epic 13 — Seed
- **Goal:** Seed coherent quote/application/policy demo data plus the prerequisite contact whose decrypted email contains `deny`, so both the happy path and the decline thread are demoable and the acceptance suite has its fixtures.
- **Rough scope:** Per-tenant + per-session seed for the new record types fitting the existing shared-baseline / per-session story; the `deny@…` decline contact (contacts have no email-edit path, so this is seed-only — TDD R3/C4).
- **Open questions / decisions for stakeholders:** which tenant/persona carries the `deny@…` contact, and how much seeded quote/app/policy depth the demo wants (content, not design).
- **Depends on:** Epic 8 (records to seed), Epic 10 (decline thread).
- **Implementation notes:** _none yet_

## Epic 14 — Acceptance suite
- **Goal:** A named acceptance suite proving both threads end-to-end on the real Postgres + RabbitMQ substrate — happy path to issued Policy and decline → supersession → re-approval — plus the coupling and tenant/session isolation proofs.
- **Rough scope:** The end-to-end happy-path and decline/supersession threads; the coupling proof (status moves advance the opportunity, manual reach into automation-owned stages rejected); the isolation proofs (Tenant-1 records absent in Tenant-2, no Medicare field in Tenant-2, cross-session invisibility).
- **Open questions / decisions for stakeholders:** none expected.
- **Depends on:** Epic 11, Epic 12, Epic 13.
- **Implementation notes:** _none yet_
