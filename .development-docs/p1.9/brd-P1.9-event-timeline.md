# Per-record Event Timeline (P1.9) — Business Requirements

## 1. Overview

A live-updating **event timeline** on the lead detail view that makes PolicyFlow's
event-driven processing visible. For a given lead it shows, in one chronological
stream, each **domain event** in the lead's journey and each **sidecar reaction** to
those events — with a status and timestamp on every row — updating in near-real-time
as new activity arrives. It is the visible payoff for the event-bus investment and a
first-class part of the self-explaining demo, directly serving walkthrough step 4
("watch the lead's event timeline update live as enrichment runs").

## 2. Background & Problem

A lead already moves through intake → assignment → qualification, firing domain events
that stub sidecars react to (enrichment, sync-logger). Today **none of that is visible
in the UI** — the event bus, the fan-out to consumers, and the reactions all happen
off-screen. For a platform whose whole pitch is "production-minded, event-driven, and
self-explaining," invisible async work is a missed point: the requirements explicitly
class per-record visibility as a *requirement, not polish*. This phase surfaces it.

## 3. Objectives

- Make a lead's event-driven activity **observable on its detail page** — every domain
  event and every sidecar reaction, with status and timestamp.
- Deliver the signature live moment: a viewer watches enrichment **advance and complete
  on-screen without refreshing** (walkthrough step 4).
- Reinforce the demo's honesty + teaching contract — clearly mark simulated work and
  explain the mechanism behind the timeline.
- Add **no new visibility**: the timeline only reads activity the viewer is already
  permitted to see, preserving the tenant + demo-session isolation invariant.

## 4. Scope

This phase is a *read/visibility surface* over events that already exist — it adds no
new domain events and no workflow behavior.

- **In scope:**
  - A timeline on the **lead detail** view, showing domain events **and** sidecar
    reactions as **sibling rows** in one chronological stream.
  - Per-row **status + timestamp**; reaction rows also show a one-line **result
    summary** (e.g. enrichment quality score).
  - **Live updating** so new rows/status changes appear near-instantly while the page
    is open; **full history shown on open**.
  - A **"Simulated" badge** on stub-reaction rows and **one explainer** describing the
    outbox/event-bus mechanism behind the timeline.
  - **Seeded plausible history** so historical/baseline leads also show a coherent,
    populated timeline.
- **Out of scope:**
  - Timeline on opportunities/policies and the correlation-ID end-to-end trace view → **P2.5**.
  - Real sidecars; the reactions shown are P1.5 **stubs** → **M3** (the `Failed` status
    is defined but dormant until then).
  - Retry / dead-letter / replay visibility and any integration-health dashboard → **M3/M4**.

## 5. Users & Stakeholders

- **Demo viewer** (the primary audience — a prospective employer/evaluator), embodied
  in the seeded **Agent** working a lead; the timeline is where they *see the engineering*.
- **Any authenticated role** that can open lead detail sees the timeline (it adds no
  new access).
- **Program owner** — for whom this is the visible proof that the event bus does
  something, and a teaching surface for the "How it's built" narrative.

## 6. Functional Requirements

1. On a lead's detail view, show a timeline of that lead's activity: each **domain
   event** (e.g. created, assigned, qualified/rejected) and each **sidecar reaction**
   (enrichment stub, sync-logger stub) as a **sibling row**.
2. Each row shows a **status** and a **timestamp**. Domain-event rows are factual
   ("occurred"); reaction rows carry a status that advances **Pending → Processing →
   Done**, with **Failed** defined but unused in P1.
3. Reaction rows also show a **one-line result summary** (e.g. the enrichment quality
   score) so cause-and-effect reads in one place.
4. The timeline **updates live** — new rows and status changes appear near-instantly
   (target ~1–2s) **without a manual refresh** while the page is open.
5. On opening a lead, the timeline shows its **complete history** already populated,
   then continues to update live.
6. Rows are ordered **oldest-first (chronological)**; timestamps display as a
   **relative label** with the **absolute time on hover**.
7. **Stub-reaction rows carry the "Simulated" badge**, and the timeline carries **one
   explainer** describing the outbox + event-bus mechanism that feeds it.
8. **Historical/seed leads** show a coherent, pre-populated timeline (no empty
   timelines on pre-seeded leads).
9. Timeline reads are confined to the record's **tenant** and the viewer's **demo
   session** — a viewer never sees another tenant's or session's activity.

## 7. Constraints & Non-Functional Needs

- **Liveness:** near-instant refresh target (~1–2s); ~5–10s is an acceptable fallback
  if the chosen mechanism makes the tighter target costly (mechanism deferred to TDD).
- **Isolation invariant (standing):** tenant + demo-session scoping must hold on this
  new surface and be re-proven by test.
- **No raw PII** surfaces on the timeline beyond what the lead's masked view already
  permits; rows describe *what happened*, not sensitive values.
- **Tests ship with the slice** behind the pre-commit gate (standing program rule).
- **Forward-compatible vocabulary:** the `Pending/Processing/Done/Failed` status set
  and the events+reactions stream should extend cleanly into M3 (real sidecars,
  failures) and P2.5 (opportunities/policies + correlation trace) without rework.

## 8. Assumptions

- The domain events and stub reactions needed already exist from P1.5/P1.7; this phase
  reads and presents them rather than creating new ones.
- The "Simulated" badge and explainer/popover components exist from P1.6 and are reused.
- The lead detail view, masked-read layer, and demo-session scoping from P1.7/P1.8 are
  the substrate this builds on.
- Stub reactions complete near-instantly; the live-status motion is shown honestly
  within that reality (how to surface a distinct "Processing" state is a TDD concern).

## 9. Success Criteria / Acceptance

1. **Live moment (headline):** opening a freshly-created lead, the viewer watches the
   enrichment reaction row advance `Pending → Processing → Done` and its quality-score
   summary appear within the near-instant target — **no manual refresh** (walkthrough
   step 4). *(MUST — the signature moment.)*
2. **Full history on open:** opening any lead (live or historical-seed) shows its
   complete chronological event + reaction trail with statuses and timestamps — **no
   empty timelines**.
3. **Both row kinds present:** domain events and both sidecar stub reactions appear as
   sibling rows.
4. **Honesty + teaching:** stub-reaction rows show the "Simulated" badge; the timeline
   carries one explainer of the outbox/event-bus mechanism.
5. **Isolation holds:** the timeline reads only within the record's tenant and the
   viewer's demo session, re-proven by test.

## 10. Open Questions

- **Live-update mechanism** (polling vs websocket) and the cadence that meets the
  ~1–2s target — deferred to `2-requirements-to-tdd`.
- **Data source & model** for the timeline (how domain events + reaction records are
  read per-lead, and how a distinct "Processing" state is represented for
  near-instant stubs) — deferred to the TDD.
- **Exact event/reaction set** to render for P1.9 and the precise shape of seeded
  historical timelines — settled at TDD/epic-plan time against what's already emitted.
