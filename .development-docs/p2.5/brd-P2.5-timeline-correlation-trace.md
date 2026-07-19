# P2.5 — Timeline + Correlation Trace Extension — Business Requirements

## 1. Overview

Extend the P1.9 per-record event timeline to opportunity and policy detail views, and add
a correlation-trace view that renders one lead's end-to-end journey (lead →
contact/household → opportunity → quote → application → policy) from the events sharing
its `correlation_id`. Read/UI only — no new event emission; the value is making the
event-driven story visible everywhere it happens, culminating in walkthrough step 20.

## 2. Background & Problem

P1.9 shipped the live timeline on lead detail only; opportunities and policies (built in
P2.1–P2.4) emit events nobody can see on their own pages, and there is no single surface
showing a journey's whole causal story. Step 20 of the walkthrough — "every event from
`lead.created` to `crm.sync.completed`, tied by `correlation_id`" — has no home until
this ships. M2 is otherwise complete, making this its closing phase.

## 3. Objectives

- Opportunity and policy detail views show a live-updating per-record event timeline.
- A correlation-trace view tells one journey's complete, ordered story, live-updating
  while the journey is in progress.
- Original and renewal journeys are causally linked and walkable in both directions.
- No timeline or trace surface ever renders empty for baseline (seeded) records.

## 4. Scope

- **In scope:** generalized timeline on opportunity + policy detail; correlation-trace
  view reachable via "view full trace" links on every per-record timeline (lead, opp,
  policy) and the walkthrough stepper deep-link; bidirectional causation links between an
  original journey's trace and its renewal's trace; seeded plausible event history for
  baseline opportunities and policies (ADR 0007); reuse of P1.9 polling and "Simulated"
  badge treatment.
- **Out of scope:** per-record timelines on quotes/applications (their events appear only
  in the trace); a standalone journey-list page; push transport (polling only);
  Notification/Metrics reactions (M3/M4 — only Quote + CRM-Sync reactions render); any
  new event emission or schema change to what P2.1–P2.4 emit.

## 5. Users & Stakeholders

Demo visitors (recruiters, engineers) walking or free-roaming the showcase; the author,
whose event-driven architecture claim this surface proves. Any role that can open a
record's detail view sees its timeline; the trace adds no new visibility.

## 6. Functional Requirements

1. Opportunity and policy detail views each show a live-updating event timeline for that
   record, matching P1.9's behavior (chronological, relative timestamps, reaction status,
   result summaries, "Simulated" badges, one mechanism explainer).
2. Every per-record timeline (lead, opportunity, policy) links to the full correlation
   trace of that record's journey.
3. The trace view shows all events and reactions sharing the journey's `correlation_id`,
   ordered, spanning the full lifecycle, and updates live while the journey progresses —
   partial (in-progress) journeys render gracefully.
4. A trace whose journey spawned a renewal links out to the renewal's trace; a renewal's
   trace links back to its originating journey's trace.
5. Baseline (seeded) opportunities and policies carry seeded plausible event history so
   their timelines and traces are populated (ADR 0007).

## 7. Constraints & Non-Functional Needs

- Tenant-isolation / PII invariant: no new visibility; events key on references, never
  values; trace and timeline reads stay tenant- and demo-session-scoped.
- "Live" matches the P1.9 bar: near-instant (~1–2 s target, 5–10 s acceptable).
- Trace view follows the UI/UX guide §6.11 (ink-console surface, §6.1 timeline anatomy,
  prominent mono `correlation_id`).
- Tests ship with the slice behind the pre-commit gate (standing program rule).

## 8. Assumptions

- P2.1–P2.4 honored `correlation_id` propagation end-to-end and renewals carry causal
  parentage to their originating journey — no emission fixes belong to this phase.
- P1.9's timeline derivation, polling, and badge treatment generalize by entity type
  without redesign.

## 9. Success Criteria / Acceptance

1. **Signature:** with the trace view open, drive a lead through convert → quote → bind
   and watch events append live, no refresh, through `crm.sync.completed` (walkthrough
   step 20).
2. Opportunity and policy detail timelines update live during their record's activity.
3. From a lead, opportunity, or policy detail view, the full journey trace is one click.
4. From an original journey's trace, the renewal trace is reachable and vice versa.
5. Baseline opportunities and policies show populated timelines; their journeys show
   populated traces.

## 10. Open Questions

- Trace presentation detail (grouping by entity vs flat stream within §6.11's anatomy),
  the trace read/data model, and how renewal causal parentage is queried — for the TDD.
- Shape and depth of seeded plausible history for baseline opps/policies — for the TDD.
