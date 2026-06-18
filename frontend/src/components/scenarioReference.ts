// The scenario-reference catalog (Guide §6.9 — "a reference panel listing every
// magic input, Platform-Admin demo control, and demo time control, each with its
// trigger and expected outcome"). The substance is the demo's scripted scenarios
// from the requirements; the wording is the established demo voice.
//
// This file holds NO JSX — just data — so it stays a clean Vite fast-refresh
// boundary, mirroring stepperSteps.ts / navSections.ts / roleLabels.ts. The panel
// component (ScenarioReferencePanel) reads these groups and renders the cards.
//
// MARKING — each entry carries a neutral StampTag naming the walkthrough STEP it is
// demonstrated in (e.g. "STEP 03"), with a "DEMO CONTROL" fallback for the two that
// have no single step (Session reset, Anniversary job). NO internal build-phase IDs
// are ever surfaced to the visitor (the Epic 12 / Epic 17 rule). Nothing is wired in
// P1.6 — every entry becomes live as the named steps ship in later phases; the panel
// intro states this plainly so the catalog reads as a forward-looking reference.
//
// SCOPE — ~8 entries in three categories. The not-yet-designed "simulated inbound CRM
// change" (a Phase-4 [SHOULD]) is deliberately deferred. The renewal/AEP sweep is
// listed ONCE, under time controls — not duplicated under Platform-Admin controls.

/** One scenario entry — a magic input, demo control, or time control. */
export interface ScenarioEntry {
  /** Stable slug; drives the entry's row ids (CLAUDE.md unique-id rule). */
  slug: string;
  /** The scenario's short name — what this entry triggers. */
  title: string;
  /** How the visitor triggers it (the "magic input" or control action). */
  trigger: string;
  /** What the demo does in response — the observable outcome. */
  outcome: string;
  /** The neutral marker: the walkthrough step ("STEP 03") or "DEMO CONTROL". */
  marker: string;
}

/** A titled group of scenario entries (one of the three catalog categories). */
export interface ScenarioCategory {
  /** Stable slug; drives the group's section/heading ids. */
  slug: string;
  /** The category heading. */
  title: string;
  /** A one-line description of what kind of scenario this category holds. */
  description: string;
  /** The entries in this category. */
  entries: ScenarioEntry[];
}

/** The panel's intro — states the catalog is forward-looking (nothing wired in P1.6). */
export const SCENARIO_REFERENCE_INTRO =
  "A forward-looking reference to every scripted demo scenario — the magic inputs, the Platform-Admin demo controls, and the demo time controls — each with its trigger, its expected outcome, and the walkthrough step where it becomes live. Nothing here is wired up in this preview; each scenario starts working as the step it is marked with ships.";

export const SCENARIO_CATEGORIES: ScenarioCategory[] = [
  {
    slug: "magic-inputs",
    title: "Magic inputs",
    description:
      "Lead-intake prefills that steer the pipeline down a specific path. Each fills the intake form with an identity engineered to produce the named outcome.",
    entries: [
      {
        slug: "typical-lead",
        title: "Typical lead",
        trigger:
          "Submit the intake form with the “typical lead” prefill (or any ordinary applicant).",
        outcome:
          "The happy-path intake: the lead is created, enrichment runs, and a quality score and enriched details appear on the record.",
        marker: "STEP 03",
      },
      {
        slug: "duplicate-scenario",
        title: "Duplicate scenario",
        trigger:
          "Use the duplicate-bait prefill — Margaret Chen, mchen@example.com — already present in the seeded data.",
        outcome:
          "A blind-index match flags the likely duplicate without exposing the PII; you resolve it by linking to the existing record, creating a new one, or rejecting it.",
        marker: "STEP 05",
      },
      {
        slug: "declined-application",
        title: "Declined application",
        trigger:
          "Use a prefill whose email contains “deny” (e.g. deny@example.com).",
        outcome:
          "The application is declined (application.declined), the Opportunity returns to Quoted, and selecting a different quote creates a superseding Application that keeps the prior one for history.",
        marker: "STEP 12",
      },
      {
        slug: "crm-sync-failure",
        title: "CRM sync failure",
        trigger:
          "Use a prefill whose email contains “fail” (e.g. fail@example.com).",
        outcome:
          "That record’s CRM sync events simulate a failure: retries run with backoff, the exhausted message lands in the dead-letter queue, and a replay re-drives it through the same consumer.",
        marker: "STEP 14",
      },
    ],
  },
  {
    slug: "platform-admin-controls",
    title: "Platform-Admin demo controls",
    description:
      "Session-scoped controls available to the Platform-Admin persona. They affect only your own demo session — the shared seed is never touched.",
    entries: [
      {
        slug: "session-reset",
        title: "Session reset",
        trigger:
          "Run “Session reset” from the Platform-Admin demo controls.",
        outcome:
          "Purges only the records your session created; the seeded data survives, so the demo returns to a clean starting point for you alone.",
        marker: "DEMO CONTROL",
      },
      {
        slug: "simulated-crm-outage",
        title: "Simulated CRM outage",
        trigger:
          "Run “Simulated CRM outage” from the Platform-Admin demo controls.",
        outcome:
          "Tenant-wide CRM sync failures: every record’s sync retries, exhausted messages move to the dead-letter queue, and you replay them once the outage is cleared.",
        marker: "STEP 14",
      },
    ],
  },
  {
    slug: "time-controls",
    title: "Demo time controls",
    description:
      "Controls that fast-forward the calendar so time-driven, scheduled work can be observed on demand instead of waiting for real dates.",
    entries: [
      {
        slug: "renewal-aep-sweep",
        title: "Renewal / AEP sweep",
        trigger:
          "Run the renewal sweep, modelling the seasonal Annual Enrollment Period window (Oct 15 – Dec 7).",
        outcome:
          "Generates an “AEP Review” renewal Opportunity for each active policy plus a follow-up Task for the agent — time-driven work alongside the event-driven pipeline.",
        marker: "STEP 15",
      },
      {
        slug: "anniversary-renewal-job",
        title: "Anniversary renewal job",
        trigger:
          "Run the daily anniversary job (the 60-day policy anniversary, non-Medicare products).",
        outcome:
          "Generates renewal work for policies reaching their 60-day anniversary, showing the recurring scheduled job distinct from the seasonal sweep.",
        marker: "DEMO CONTROL",
      },
    ],
  },
];
