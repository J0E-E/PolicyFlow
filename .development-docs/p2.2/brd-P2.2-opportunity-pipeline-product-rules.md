# Opportunity Pipeline & Product Rules (P2.2) — Business Requirements

## 1. Overview
PolicyFlow needs a canonical, server-enforced **opportunity pipeline** so agents can
advance a converted opportunity through its sales lifecycle. P2.2 delivers the stage
state machine with per-tenant configuration (relabel stages, toggle the optional ones),
the **Medicare eligibility gate** that protects MA/Part D opportunities, and the display
of each opportunity's pipeline value fields. It also makes the two demo tenants look
visibly different on the same screens — itself a demo requirement.

## 2. Background & Problem
P2.1 creates opportunities (born at *New*) but they cannot move. There is no enforced
lifecycle, no way for the two tenants to differ in their pipeline, and no rule stopping an
ineligible Medicare opportunity from advancing toward a quote. Without the stage machine,
the rest of M2 (quotes → application → policy, renewals) has nothing to couple to. This is
the next hard-sequential step (P2.1 → **P2.2** → P2.3), and the walkthrough's step 8 and the
isolation proof in step 18 both depend on it.

## 3. Objectives
- Agents can **move an opportunity through the pipeline**, with every invalid transition
  rejected server-side (no client-only enforcement).
- Each tenant's pipeline is **configurable from seed**: stage display labels renamed, the
  optional *Quoted* / *Approved* stages toggled on/off; the four anchor stages always present.
- **Medicare (MA/Part D) opportunities cannot reach *Quoted*** (nor request quotes) unless
  the customer is age ≥ 65; the enrichment eligibility flag never gates.
- Each opportunity's **value fields** (`estimated_annual_premium`, `target_close_date`) are
  visible on the pipeline.
- Stage changes **emit domain events** (`opportunity.stage_changed`, plus `opportunity.lost`).
- The **two demo tenants are visibly different** on the same pipeline screens (stage labels,
  enabled stages).

## 4. Scope
Everything below is bounded to the opportunity stage lifecycle and its per-tenant
presentation; quotes, applications, and policies are later phases.

- **In scope:**
  - Canonical stage machine: `New → Qualified → Quoted → Application Started → Submitted →
    Approved → Policy Active`; `(any active stage) → Lost`. *Lost* is terminal.
  - **Manual, agent-driven** stage transitions on the pipeline board, validated server-side.
  - Per-tenant (seed-driven) config: rename stage labels; toggle optional *Quoted* /
    *Approved*. Anchors fixed: *New*, *Application Started*, *Policy Active*, *Lost*.
  - Disabled-stage **skip semantics**: a disabled optional stage is not a valid target; the
    next enabled stage is reachable directly.
  - Medicare (MA/Part D) **eligibility gate** (age ≥ 65 from stored DOB / derived age band)
    blocking entry to *Quoted* and blocking quote requests, with a clear rejection reason.
  - Pipeline board UI grouped by stage, rendering per-tenant labels/toggles read-only and
    showing `estimated_annual_premium` + `target_close_date` per opportunity.
  - Events: `opportunity.stage_changed`, `opportunity.lost`.
- **Out of scope (deferred):**
  - Application-status → stage **auto-advance coupling**, quotes, applications, policy
    issuance → **P2.3**.
  - Beneficiary / health-question steps → **P2.3** (they live on the Application).
  - Auto-update of `estimated_annual_premium` to the selected quote's premium → **P2.3**.
  - Pipeline-value **sorting** and value-by-stage rollups → **M4 [SHOULD]**.
  - Editing value fields after creation; reopening a *Lost* opportunity.

## 5. Users & Stakeholders
- **Agents** — move their owned opportunities through the pipeline; experience the
  eligibility gate and the per-tenant stage labels.
- **Tenant Admins** — may change stages / mark *Lost*; own the per-tenant stage config
  (delivered via seed in this phase, not a live editor).
- **Demo viewer / prospect** — sees the two tenants differ on the same screens (sales proof).
- **Downstream phases (P2.3+)** — consume the stage machine and its events as the spine for
  quotes, applications, policies, and renewals.

## 6. Functional Requirements
1. The system shall let an authorized agent **change an opportunity's stage**, accepting only
   transitions allowed by the canonical machine for that tenant's enabled stages.
2. The system shall **reject invalid transitions server-side** with a clear reason, leaving
   the opportunity unchanged.
3. The system shall let an opportunity be **marked *Lost* from any active stage**; *Lost* is
   terminal.
4. The system shall apply **per-tenant stage configuration** from seed: renamed display
   labels and enabled/disabled optional stages (*Quoted*, *Approved*), with the four anchor
   stages always present.
5. When an optional stage is disabled, the system shall treat it as **not a valid target** and
   allow advancing to the next enabled stage directly.
6. For **Medicare Advantage / Part D** opportunities, the system shall **block entry to
   *Quoted* and block quote requests** unless the customer is age ≥ 65 (from stored DOB /
   age band), showing why; the enrichment eligibility flag is advisory only and never gates.
7. The system shall **display** each opportunity's `estimated_annual_premium` and
   `target_close_date` on the pipeline.
8. The system shall **publish `opportunity.stage_changed`** on every stage change and
   **`opportunity.lost`** when an opportunity is marked *Lost*.
9. The pipeline UI shall present opportunities **grouped by stage**, using the tenant's
   configured labels and enabled stages.

## 7. Constraints & Non-Functional Needs
- **Tenant isolation:** stage config and opportunities are tenant-scoped and
  demo-session-tagged; the two tenants must differ visibly in labels/toggles on shared screens.
- **Server-side authority:** transition validity and the eligibility gate are enforced on the
  server; the UI must not be the only guard.
- **Auditability / traceability:** stage-change events carry `tenant_id` + `demo_session_id`
  and honor the M2 `correlation_id` invariant (copied forward, stamped on publish).
- **Demo determinism:** behavior must be repeatable for the scripted walkthrough.

## 8. Assumptions
- P2.1 opportunities exist, are owned by the converting agent, and carry `estimated_annual_premium`,
  `target_close_date`, stored DOB / derived age band, and `correlation_id`.
- The per-tenant stage configuration is supplied by **seed data** in this phase (no live config
  editor).
- The event bus / outbox (P1.5) and tenant scoping (P1.2) are in place.
- A customer's age is derivable from stored DOB / age band captured at intake (P1.7).

## 9. Success Criteria / Acceptance
- **Walkthrough step 8:** an agent advances an opportunity `New → Qualified → … → Policy
  Active`; can mark it *Lost* from an active stage; invalid transitions are refused
  server-side. For **Tenant 1**, a Medicare opportunity with an under-65 customer is blocked
  from reaching *Quoted* with a visible reason, and is allowed once eligible.
- Each tenant's pipeline shows its **own stage labels** and only its **enabled stages**;
  disabled-stage skip behaves as specified.
- `estimated_annual_premium` and `target_close_date` are visible per opportunity.
- Stage changes are observable as `opportunity.stage_changed` / `opportunity.lost` events.
- **Walkthrough step 18 (isolation proof):** switching tenants shows different stage labels /
  enabled stages on the same screen, and Tenant 1's opportunities are absent for Tenant 2.

## 10. Open Questions
- **Lost reason capture:** does P2.2 record an optional reason on *Lost*, or defer that to the
  renewals/reporting work? (Leaning defer unless cheap.) — for `2-requirements-to-tdd`.
- **Manual reach of automation-owned stages:** P2.2 allows manual entry to *Submitted* /
  *Approved* / *Policy Active* to demo the full machine before P2.3's coupling exists; confirm
  this manual path is acceptable as an interim or should be visibly gated. — for design.
