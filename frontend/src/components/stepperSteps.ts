// The 21-step guided-walkthrough catalog (Guide §6.6 — "a numbered table-of-contents
// overlay (01–21) … a 'what you're seeing / how it's built' note per step"). The
// substance is transcribed from the requirements walkthrough (PolicyFlow_Requirements.md
// → "Walkthrough", steps 1–21); the wording is the established demo voice, faithful to
// that source.
//
// This file holds NO JSX — just data — so it stays a clean Vite fast-refresh boundary,
// mirroring navSections.ts / roleLabels.ts. The docket components (GuidedDocket /
// GuidedDocketStep) read this list and render the rows.
//
// DEEP LINKS — the navSections.ts pattern, deliberately: each step carries an OPTIONAL
// `to` route. A row renders a live link ONLY when its `to` is set; otherwise it shows
// the inert "available in a later step" affordance (the Guide §6.6 deep link, the Epic
// 12 coming-later voice). In this phase NONE are set, so every one of the 21 is inert —
// their destinations are P1.7+ surfaces that do not exist yet. A later phase flips a
// step live simply by filling its `to` (P1.7 does this for the lead-intake step when
// the intake form lands), with no rework here. No internal phase IDs are ever surfaced
// to the visitor (Epic 12's nav decision) — the inert copy is uniform.

/** One step in the guided walkthrough. */
export interface StepperStep {
  /** 1-based step number; drives the rendered "01"–"21" label and the row ids. */
  number: number;
  /** The step's short title — what this stop in the tour is about. */
  title: string;
  /** "What you're seeing" — the visitor-facing description of the screen/beat. */
  seeing: string;
  /** "How it's built" — the engineering note (the real machinery behind the beat). */
  built: string;
  /**
   * The route this step deep-links to. Set ONLY when the destination surface exists;
   * a step is rendered inert ("available in a later step") whenever this is unset.
   * None are set in this phase — every destination is a later-phase surface.
   */
  to?: string;
}

export const STEPPER_STEPS: StepperStep[] = [
  {
    number: 1,
    title: "Land in the agent workspace",
    seeing:
      "Start on the orientation page — what PolicyFlow is, why it was built, and what is simulated — choose the full walkthrough or the 5-minute highlights, pick a demo tenant by its specialization, and land in the Agent workspace signed in as a seeded Agent with this guided docket active. The surface toggle (Shopper site ↔ Agent workspace) and the staff role switcher are both introduced here.",
    built:
      "A passwordless demo entry assumes a real seeded Agent and mints a session; RBAC is enforced because you genuinely are that user. The role switcher re-mints the session as a different seeded persona, and the surface toggle changes surface, not identity.",
  },
  {
    number: 2,
    title: "See the tenant's branding and products",
    seeing:
      "View the tenant-specific branding and product lines — the wordmark, seal mark, letterhead rule, and brand color all reflect the agency you picked, and the catalog shows that agency's products.",
    built:
      "Brand color comes from the registry and theming is declarative — a data-attribute on the app root drives the token ramps — so the same screens re-skin per tenant with no conditional markup.",
  },
  {
    number: 3,
    title: "Choose how the lead enters",
    seeing:
      "Choose how the lead enters and run one route (the other can be run afterward): self-service — toggle to the Shopper site and submit the lead yourself as the prospective buyer (or use a prefill button), landing it unassigned; or agent-entered — stay in the workspace and enter the lead as if taking the prospect's call, landing it owned by you.",
    built:
      "Either route emits the same lead.created event onto the message broker, so one downstream pipeline drives both paths; the only difference is the initial owner.",
  },
  {
    number: 4,
    title: "Watch the event timeline run live",
    seeing:
      "Watch the lead's event timeline update live as enrichment runs, then see the enrichment results and a quality score appear on the lead.",
    built:
      "A sidecar consumer reacts to lead.created, and the per-record timeline reflects each domain event and sidecar reaction with status and timestamps as the work completes.",
  },
  {
    number: 5,
    title: "Resolve the duplicate scenario",
    seeing:
      "Run the duplicate scenario and resolve it — link to the existing record, create a new one, or reject it.",
    built:
      "A blind-index lookup detects the likely duplicate without exposing the underlying PII, and your resolution is recorded against the record.",
  },
  {
    number: 6,
    title: "Take ownership and qualify",
    seeing:
      "Take ownership and qualify — a self-service lead is claimed from the unassigned queue in one click, while an agent-entered lead is already yours, so go straight to qualifying. Then qualify or reject.",
    built:
      "Ownership and the qualify/reject transition are guarded by the active role's capabilities; every state change is written to the append-only audit log.",
  },
  {
    number: 7,
    title: "Convert the lead",
    seeing:
      "Convert the lead into a Contact, a Household, and one Opportunity per product line.",
    built:
      "The conversion creates the linked records in a single transaction, so the Contact, Household, and Opportunities are always consistent with one another.",
  },
  {
    number: 8,
    title: "Progress the opportunity",
    seeing:
      "Progress an opportunity through the pipeline stages; for the Medicare-focused tenant, observe the eligibility gate that blocks an ineligible stage.",
    built:
      "Pipeline stage labels and gating rules are tenant-configured, so the same opportunity model presents the right stages and guards for each agency.",
  },
  {
    number: 9,
    title: "Request carrier quotes",
    seeing:
      "Request carrier quotes and review the returned options.",
    built:
      "Quotes come back through a mock carrier adapter behind the same seam a real carrier integration would plug into; the surface is marked Simulated so a mock is never mistaken for the real thing.",
  },
  {
    number: 10,
    title: "Select a quote and submit the application",
    seeing:
      "Select a quote — observe it create the Application — complete the product-specific step, and submit.",
    built:
      "Selecting a quote creates the Application record and the submission emits an event the downstream consumers pick up, continuing the same pipeline.",
  },
  {
    number: 11,
    title: "See the policy created, with masked PII",
    seeing:
      "See the application approved and the Policy created, with the policy number and a mock Medicare ID rendered masked; try click-to-reveal and note that the reveal is audited.",
    built:
      "Sensitive fields are stored with envelope encryption and shown masked by default; a reveal decrypts on demand and writes an audit entry — the access is recorded, not the raw value.",
  },
  {
    number: 12,
    title: "Run the decline scenario",
    seeing:
      "Run the decline scenario — intake with the 'simulate a declined application' prefill, fast-track to submission, and observe the decline, the Opportunity returning to Quoted, and selecting a different Quote creating a superseding Application.",
    built:
      "A publish-time flag on the prefilled lead steers the mock decision to a decline; the superseding Application keeps the prior one for history rather than overwriting it.",
  },
  {
    number: 13,
    title: "Inspect CRM sync mapping",
    seeing:
      "Observe CRM sync activity for the new records — open the mock CRM record viewer's side-by-side mapping view (internal record → mapping rules → CRM-style payload) and note the external record ID with Create-versus-Update labeling.",
    built:
      "The same internal record maps to a visibly different payload under each tenant's field-mapping rules, demonstrating per-tenant CRM mappings against one shared model.",
  },
  {
    number: 14,
    title: "Trigger a sync failure and replay it",
    seeing:
      "Trigger a simulated CRM outage — or use the 'simulate a CRM sync failure' prefill for a single-record failure — watch retries execute, see the event land in the dead-letter queue, and (as Tenant Admin) replay it.",
    built:
      "Per-consumer retries run with backoff; an exhausted message moves to the dead-letter queue, and a replay re-drives it through the same consumer — the real broker machinery around a mocked integration.",
  },
  {
    number: 15,
    title: "Run the renewal sweep",
    seeing:
      "Run the renewal / annual-enrollment sweep and observe the generated Renewal Opportunity and the agent Task it creates.",
    built:
      "A scheduled sweep generates the renewal records and the follow-up task, showing time-driven work alongside the event-driven pipeline.",
  },
  {
    number: 16,
    title: "Open the notification center and outbox",
    seeing:
      "Open the notification center and the simulated outbox to see the rendered notifications.",
    built:
      "Notifications are produced through a transactional outbox, so a notification is written in the same transaction as the change that triggered it and never lost on a crash.",
  },
  {
    number: 17,
    title: "Switch roles to see masking and the audit log",
    seeing:
      "Switch to the Read-Only role and observe PII masking with no reveal; switch to Tenant Admin and view the audit log — conversions, reveals, and sync attempts, with no raw PII.",
    built:
      "The same screens enforce different capabilities per role because the switch re-mints the session as that seeded user; the audit log is append-only and records who and what, never the sensitive value.",
  },
  {
    number: 18,
    title: "Switch tenants to prove isolation",
    seeing:
      "Switch to the second tenant: different branding, product lines, stage labels, and field mappings on the same screens — and confirm the records you just created in the first tenant are absent. That absence is the isolation proof.",
    built:
      "Each tenant's data lives in its own schema, so a query in one tenant cannot reach another's records — the empty result is the isolation working, presented as a calm note rather than an error.",
  },
  {
    number: 19,
    title: "View the dashboards",
    seeing:
      "View the funnel and integration-health dashboards.",
    built:
      "The dashboards aggregate the tenant's own records and integration activity, scoped by the same per-tenant isolation as every other screen.",
  },
  {
    number: 20,
    title: "Open the end-to-end event trace",
    seeing:
      "Open the end-to-end event trace — every event from lead.created to the completed CRM sync, tied together by a correlation ID.",
    built:
      "Every event and sidecar reaction carries the same correlation ID, so the trace reconstructs one lead's whole story across the core and every sidecar.",
  },
  {
    number: 21,
    title: "End on the 'How it's built' page",
    seeing:
      "End on the 'How it's built' page — the annotated system diagram, the domain-model view, and an index of the showcase patterns that deep-link back into the app, plus links to the repository and the author.",
    built:
      "The page indexes the real patterns demonstrated through the tour — auth and RBAC, schema-per-tenant isolation, field-level encryption, the append-only audit, and the transactional outbox with its event bus — and grows richer each phase.",
  },
];
