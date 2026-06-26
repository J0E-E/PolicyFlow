# P2.3 — Quotes → Application → Policy — Business Requirements

## 1. Overview

Build the opportunity-to-policy spine: turn a *Qualified* opportunity into carrier
quotes, a selected quote into an Application, walk that Application through
product-specific steps and a simulated carrier decision, and issue a Policy. This is the
demo's core money-path (walkthrough steps 9–12) and the part that demonstrates real
business-process orchestration — a lifecycle state machine with attributable decision
points and a modeled failure/recovery path.

## 2. Background & Problem

Earlier phases get a lead to a *Qualified* opportunity (P2.1 conversion, P2.2 stage
machine + Medicare eligibility gate), but the journey dead-ends there: there is no way to
quote, apply, decide, or issue a policy. Without this spine the demo cannot show the
outcome the whole product exists to produce — a sold policy — nor the orchestration,
state-machine, and secure-PII showcase goals that ride on it. P2.2 deliberately deferred
three behaviours to this phase: the application-status→stage auto-advance coupling, the
auto-update of `estimated_annual_premium` to the selected quote, and the
beneficiary/health steps (which belong on the Application). P2.3 delivers them.

## 3. Objectives

- Let an agent take a *Qualified* opportunity all the way to an **issued Policy**, with
  every transition watchable in the demo.
- Prove the **lifecycle state machine** end-to-end, including the **decline → supersession
  → re-apply** recovery path — not just a linear happy path.
- Make the **carrier quote round-trip observable** (request → pending → completed) as a
  visible event-driven interaction.
- Couple application/policy status to the opportunity stage so the pipeline advances
  itself, removing the manual reach into automation-owned stages that P2.2 allowed as an
  interim.
- Reinforce the **secure-PII** showcase: a Tenant-1 Medicare ID that is encrypted, masked
  by default, and revealed only through an audited action.
- Preserve **multi-tenant isolation** and **demo-session isolation** for every new record
  and event.

## 4. Scope

All work is tenant-scoped and demo-session-tagged; seeded reference data is never mutated.

- **In scope:**
  - Carrier + product-catalog **reference data** (tenant-scoped seed).
  - **Carrier Quote stub** doing a real broker round-trip: `quote.requested` →
    pending→completed → `quote.completed`, returning **2–3 deterministic canned options**
    per request (carrier, product, coverage, premium shown monthly + annualized).
  - **Quote / Application / Policy** entities and their lifecycle.
  - Quote attach → opportunity *Quoted*; **selecting a quote creates the Application**
    (`Draft`), advances the opportunity to *Application Started* (`application.started`),
    and updates `estimated_annual_premium` to the quote's annualized premium.
  - **Product-specific Application steps:** **beneficiary** (Life) and **health
    questions** (LTC, 3–5 mock). Captured on the Application.
  - **Submission** (`application.submitted`) → inline simulated **carrier decision**
    (approved by default; applicant email containing `deny` forces declined) →
    `application.approved` / `application.declined`.
  - **Application↔Opportunity coupling:** application/policy status auto-advances the
    opportunity stage; once shipped, the automation-owned stages become lifecycle-driven
    (manual transitions into them disabled).
  - **Decline → supersession:** a declined application is retained as read-only history
    (marked superseded), the opportunity returns to *Quoted*/*Qualified*, and selecting a
    different attached quote creates a new active Application.
  - **Policy issuance** on approval (`policy.created`) with a human-readable policy number.
  - **Tenant-1 Medicare ID** on the Application: encrypted, masked by default, audited
    click-to-reveal (reusing P1.3).
  - Quote-list/selection, application-steps, and policy **UIs**.
- **Out of scope:**
  - Real Carrier Quote service → **M3** (behind identical events).
  - Cross-sell prompt + renewals → **P2.4**.
  - CRM sync of the new records → **P3**.
  - A "pending / manual review" carrier outcome (decision is binary this phase).
  - Editing/managing the carrier or product catalog in-app (seed-driven).

## 5. Users & Stakeholders

- **Owning agent** — primary actor: requests quotes, selects a quote, completes the
  product step, submits, reveals the Medicare ID, and drives the decline/re-apply path.
- **Tenant Admin** — may drive the same flow; cares about audit of reveals.
- **Read-Only role** — observes the full flow with PII masked, no reveal, no actions.
- **Demo viewer / stakeholder** — the audience the walkthrough is built for; cares that
  every step is visibly watchable.

## 6. Functional Requirements

1. From an opportunity at *Qualified*, the owning agent can **request carrier quotes**;
   the system shows the request go **pending → completed** and returns 2–3 options.
2. Returned quotes **attach** to the opportunity and move it to **Quoted**; each option
   shows carrier, product, coverage, and premium (monthly + annualized).
3. **Selecting a quote creates an Application** in `Draft`, moves the opportunity to
   *Application Started*, and sets `estimated_annual_premium` to that quote's annualized
   premium.
4. The Application captures its **product-specific step**: beneficiary for Life, 3–5 mock
   **health questions** for LTC; other product lines need no extra step.
5. The agent can **submit** the Application; the system returns a **carrier decision** —
   approved by default, or **declined** when the applicant email contains `deny`.
6. On **approval**, a **Policy is issued** with a policy number, carrying the carrier,
   product, coverage, and premium from the selected quote.
7. **Application/policy status auto-advances the opportunity stage**; the automation-owned
   stages can no longer be reached by manual agent action.
8. On **decline**, the opportunity returns to *Quoted*/*Qualified*, the declined
   Application is retained as read-only (superseded), and the agent can **select a
   different attached quote to create a superseding Application**. Only one active
   Application exists per opportunity at a time.
9. For **Tenant 1**, the Application carries a **Medicare ID** rendered **masked**;
   authorized roles can **click to reveal** it and the reveal is **audited**.
10. Every quote/application/policy action **publishes its domain event** carrying
    `tenant_id` + `demo_session_id`, observable in the per-record timeline.

## 7. Constraints & Non-Functional Needs

- **Watchability:** the quote round-trip and each status transition must be visible in the
  demo without a manual refresh (consistent with the P1.9 live-timeline expectation).
- **Tenant isolation:** carrier/catalog reference data, quotes, applications, and policies
  are tenant-scoped; the two tenants differ visibly (Tenant 1 has the Medicare-ID field;
  Tenant 2 does not).
- **Demo-session isolation:** all new records are demo-session-tagged; seeded reference
  data is never mutated by a session.
- **Determinism:** quote options and the carrier decision are deterministic (no
  randomness) so the demo is repeatable.
- **PII handling:** the Medicare ID is encrypted at rest, masked by default, and revealed
  only through an audited action (reuse P1.3 — no new PII mechanism).
- **Eligibility:** the P2.2 Medicare (MA/Part D, age ≥ 65) gate already blocks reaching
  *Quoted* and quote requests; P2.3 does not relax it.

## 8. Assumptions

- P2.2 stage machine + per-tenant stage config + eligibility gate are in place; P2.1
  opportunities exist (owned, with value fields, DOB/age band, `correlation_id`); P1.3 PII
  primitives and P1.5 outbox/events are available.
- The Carrier Quote interaction is a **stub** in this phase but uses the **same events**
  the real M3 service will, so M3 swaps in behind an unchanged contract.
- The carrier decision being inline (not a separate sidecar/service) is acceptable for the
  demo's purposes this phase.
- One product line per opportunity (per P2.1 conversion: one opportunity per product line).

## 9. Success Criteria / Acceptance

Both threads are **required** to ship:

- **Happy path (steps 9–11):** from a *Qualified* opportunity, request quotes → watch
  pending→completed → review options → select one → Application created, opportunity at
  *Application Started*, premium updated → complete the product step → submit → see it
  approved → Policy issued with a policy number; for Tenant 1 the Medicare ID renders
  masked and click-to-reveal works and is audited.
- **Decline + supersession (step 12):** submit an application whose applicant email
  contains `deny` → observe `application.declined`, the opportunity returning to
  *Quoted*, and selecting a different quote creating a superseding Application that can be
  carried to approval.
- **Coupling proof:** moving an application/policy through its statuses visibly advances
  the opportunity stage with no manual stage change; manual reach into automation-owned
  stages is no longer possible.
- **Isolation proof:** the quotes/applications/policies created in Tenant 1 are absent in
  Tenant 2, which also lacks the Medicare-ID field (consistent with walkthrough step 18).

## 10. Open Questions

For `2-requirements-to-tdd` (technical) and `4-plan-epic` (lockdown):

- **Phase split:** this is Size L with "split likely" — the natural seams (e.g. quotes +
  catalog / application lifecycle + decision / policy issuance + Medicare ID) are a
  TDD/epic-plan decision.
- Exact **event names/payloads** for the quote, application, and policy lifecycle (the
  stub↔M3 contract) — TDD.
- Whether the Medicare ID is **agent-entered during the application step** or **seeded** on
  the relevant Tenant-1 fixtures — leaning entered-during-step for demo value; TDD/epic.
- Exact **health-question set** (3–5) and **beneficiary** fields — content decision for the
  epic plan.
- Policy-number **format** and which fields the Policy surfaces — TDD/epic.
- Whether a **re-quote** (new `quote.requested`) is offered alongside selecting an existing
  attached quote on the decline path, or only re-selection — leaning re-selection only for
  the acceptance, re-quote optional; epic plan to confirm.
