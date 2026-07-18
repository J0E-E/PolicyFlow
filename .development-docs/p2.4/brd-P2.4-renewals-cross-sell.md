# P2.4 — Renewals & Cross-sell — Business Requirements

## 1. Overview

Build the two "post-policy opportunity generation" workflows: per-product renewal generation
(seasonal AEP sweep + daily anniversary job) and the Household cross-sell prompt, plus the
agent task queue that surfaces the generated work. Together they show the platform working
*after* a policy is issued — the system creates follow-up business without an agent having to
remember anything (walkthrough step 15).

## 2. Background & Problem

Through P2.3 the demo ends at policy issuance; nothing demonstrates ongoing account
management. Per-product renewal divergence (seasonal vs anniversary vs none) is a core domain
signal the demo must showcase, and renewals/cross-sell are the natural source of the recurring
revenue story a CRM buyer expects. Tasks exist as a thin entity with no agent-facing surface.

## 3. Objectives

- Renewal generation observable live in any demo session, per product line's real-world rule.
- Every generated renewal lands as concrete agent work: Renewal Opportunity + assigned Task.
- Cross-sell openings visible on households without agent effort, gone when coverage is full.
- Agents get a working task queue: what's due, when, linked to the record it's about.
- Shared seeded data provably untouched by any of it.

## 4. Scope

All generated records are tenant-scoped and demo-session-tagged.

- **In scope:**
  - Per-product renewal rules — MA/Part D: seasonal AEP sweep over all active policies;
    Hospital Indemnity/LTC: daily anniversary job, 60 days before policy anniversary;
    Life/Annuities: no renewals.
  - Each renewal: Renewal Opportunity (`origin = renewal`, linked to the policy, target close
    date = renewal/AEP deadline), renewal-review Task assigned to the policy's owning agent,
    `policy.renewal_due` published.
  - Platform-Admin "run renewal sweep now" / "run AEP sweep now" workspace actions, scoped to
    the visitor's demo session.
  - Session-scoped *Renewal Due* overlay for seeded policies; real `Active → Renewal Due`
    status writes only on session-created policies.
  - Cross-sell prompt on the Household page (live coverage check; one-click Opportunity).
  - Task enrichment (due dates, routing) + agent task queue UI (view + complete).
- **Out of scope:**
  - Real notification delivery (M3; renewal/cross-sell effects surface as UI records only).
  - Issuing a policy from a Renewal Opportunity (`policy.renewed` reuses the P2.3 path).
  - Lapse/cancel behavior beyond what the policy state machine already defines.
  - Task snooze, reassignment, due-date edits, manual task creation.

## 5. Users & Stakeholders

- **Agent** — receives renewal Tasks and Renewal Opportunities; works their own task queue;
  accepts cross-sell suggestions on households they serve.
- **Tenant Admin** — oversees all agents' tasks (filterable by assignee) and may complete them.
- **Read-Only** — observes the task queue and prompts; no actions.
- **Platform Admin (demo persona)** — triggers the on-demand sweeps for the visitor's session.
- **Demo visitor / prospective buyer** — the audience; must see step 15 work in one sitting.

## 6. Functional Requirements

1. The AEP sweep generates a renewal for every active MA/Part D policy in scope; the
   anniversary sweep for every active Hospital Indemnity/LTC policy within 60 days of its
   anniversary; Life/Annuities policies never generate renewals.
2. Each generated renewal creates a Renewal Opportunity (`origin = renewal`, policy-linked)
   and a renewal-review Task assigned to the policy's owning agent, and publishes
   `policy.renewal_due`.
3. Renewal generation is idempotent: at most one Renewal Opportunity per policy per renewal
   cycle; re-runs skip covered policies and report generated/skipped counts (ADR 0001).
4. Platform Admin can run either sweep on demand; effects are confined to the visitor's demo
   session. Acceptance relies on these controls only — the per-product schedule semantics are
   modeled and test-verified, but no scheduled firing needs to be observed in-session.
5. Seeded policies are never mutated: their *Renewal Due* status appears via a session-scoped
   overlay; session-created policies get the real status transition.
6. A Household with ≥1 active policy and ≥1 uncovered tenant product line shows one cross-sell
   suggestion per uncovered line, computed live from current coverage — seeded households
   included; suppressed when every line is covered (ADR 0002).
7. Accepting a cross-sell suggestion creates, in one click, an Opportunity for the household's
   contact owned by the triggering policy's owning agent.
8. Agents see their own open tasks in a task queue (due date, type, link to the related
   record; overdue flagged) and can mark them complete. Tenant Admin sees and may complete all
   agents' tasks; Read-Only views only.

## 7. Constraints & Non-Functional Needs

- Multi-visitor safety: concurrent demo sessions never see each other's generated records or
  overlays; the shared `NULL` baseline is never written.
- Renewal-generated records follow the established event conventions (tenant + session stamped;
  a renewal starts a new linked `correlation_id`).
- Demo pacing: each acceptance thread must complete in seconds — no waiting on schedules.

## 8. Assumptions

- Seed data guarantees at least one active MA/Part D policy and one Hospital Indemnity or LTC
  policy inside its 60-day anniversary window per tenant, so both sweeps visibly generate.
- Seed data includes at least one partially covered household per tenant so the cross-sell
  prompt shows on first browse.
- P2.3 policies, P2.1 Task entity, and the P1.8 scheduler + session layering exist as built.

## 9. Success Criteria / Acceptance

Three required threads, each demonstrable end-to-end in a fresh demo session:

1. **AEP sweep** — Platform Admin runs it; a Renewal Opportunity and assigned Task appear for
   a seeded MA policy; the policy shows *Renewal Due* (overlay); re-running generates nothing
   new and says so.
2. **Anniversary sweep** — same observed for a seeded Hospital Indemnity/LTC policy inside its
   window; a Life/Annuities policy generates nothing (test-verified).
3. **Cross-sell** — a partially covered household shows the prompt; one click creates the
   Opportunity owned by the policy's agent; a fully covered household shows none.

Plus: the owning agent's task queue lists the generated renewal Tasks with due dates and links,
and completing one clears it. Seeded rows in the database are byte-identical after all of it.

## 10. Open Questions

For `2-requirements-to-tdd`:

- What defines an "AEP cycle" for idempotency (calendar year?) and how the demo's frozen/fake
  date interacts with the Oct 15 – Dec 7 window and 60-day anniversary math.
- Overlay mechanics: how the session-scoped *Renewal Due* presentation reuses the P1.8
  baseline+session layering.
- Whether the in-process scheduler actually ticks in the background for session-created
  policies, or sweeps are on-demand-only internally.
- Task routing specifics ("routing" beyond assignee: queue ordering, due-date defaults).
- Renewal Opportunity pipeline entry stage and how the P2.3 automation-owned-stage lockdown
  applies to it.
- Event payloads for `policy.renewal_due` and the cross-sell-created Opportunity.
