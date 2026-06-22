// Explainer copy catalog (Epic 19) — the JSX-free data behind every ExplainerPopover.
//
// The Guide §6.2 explainer is a margin-note popover with four fixed small-caps
// sections — PATTERN / HOW POLICYFLOW DOES IT / REAL VS SIMULATED / CRM PARALLEL —
// the last omitted when a surface supplies no copy for it. Keeping the copy here
// (data, not JSX) means a new surface adds an entry, never a new component
// (the seam Epic 20's "Simulated" badge and Epic 24's surface-toggle explainer
// build on).
//
// A section body is a list of "runs" so mechanism / API terms render in
// `--font-mono` (the Guide's mono register) without any JSX in this data file:
// ExplainerPopover walks the runs and wraps the mono ones in <code>. A run is
// either a plain string or `{ mono: "outbox" }`.

/** One span of section-body text: a plain string, or a mono mechanism/API term. */
export type ExplainerRun = string | { mono: string };

/** The four fixed sections (Guide §6.2). CRM PARALLEL is optional per surface. */
export interface ExplainerContent {
  /** "PATTERN" — the general pattern this surface demonstrates. */
  pattern: ExplainerRun[];
  /** "HOW POLICYFLOW DOES IT" — the real mechanism (mono terms). */
  how: ExplainerRun[];
  /** "REAL VS SIMULATED" — what is working code vs demo data / stub. */
  realVsSimulated: ExplainerRun[];
  /** "CRM PARALLEL" — the real-world CRM equivalent. Omitted when absent. */
  crmParallel?: ExplainerRun[];
}

/** The fixed section order + their small-caps labels (Guide §6.2). The popover
 *  renders these in order, skipping CRM PARALLEL when a surface omits it. */
export const EXPLAINER_SECTION_LABELS = {
  pattern: "PATTERN",
  how: "HOW POLICYFLOW DOES IT",
  realVsSimulated: "REAL VS SIMULATED",
  crmParallel: "CRM PARALLEL",
} as const;

// ---- The four seeded surfaces (confirmed copy, Epic 19 plan) ----

/** Landing → event-driven operations (anchored at the lede). */
export const landingExplainer: ExplainerContent = {
  pattern: [
    "Event-driven operations: work moves as a chain of recorded events, not one big save. A new lead emits an event; enrichment, quoting, and CRM sync each react in turn.",
  ],
  how: [
    "A transactional ",
    { mono: "outbox" },
    " + an in-process event bus: each state change writes its event in the same database transaction as the data, then a dispatcher delivers it to consumers with per-consumer retry.",
  ],
  realVsSimulated: [
    "The outbox, event bus, retries, and dead-letter handling are real, working code. The outside systems those events reach — carrier quoting, data enrichment, the external CRM — are simulated behind an adapter seam.",
  ],
  crmParallel: [
    "Salesforce ",
    { mono: "Platform Events" },
    " + async Apex/Flow: publish a fact, let subscribers react.",
  ],
};

/** Tenant-switch "Why two tenants?" → multi-tenant isolation. */
export const tenantSwitchExplainer: ExplainerContent = {
  pattern: [
    "Multi-tenant isolation: many separate customers (here, two agencies) run on one platform, and none can ever see another's data.",
  ],
  how: [
    { mono: "schema-per-tenant" },
    ": each tenant's records live in their own Postgres schema, selected per request from the signed-in identity. There is no shared customer table to leak across.",
  ],
  realVsSimulated: [
    "The isolation is real — separate schemas and per-request scoping enforce it. The tenants, brands, and seeded records are demo data.",
  ],
  crmParallel: [
    "A separate Salesforce ",
    { mono: "org" },
    " per customer (and its sharing model): hard data boundaries between tenants.",
  ],
};

/** Role switcher → role-based access control. */
export const roleSwitcherExplainer: ExplainerContent = {
  pattern: [
    "Role-based access control: what you can see and do follows your role (Agent, Tenant Admin, Read-Only, Platform Admin), not the screen you're on.",
  ],
  how: [
    "Switching personas re-mints your session as a real seeded user via ",
    { mono: "assume-persona" },
    "; the server returns that user's ",
    { mono: "capability matrix" },
    " and enforces every action against it. The accent color is only a cue — the gate is server-side.",
  ],
  realVsSimulated: [
    "The RBAC enforcement is real and server-side. The passwordless one-click persona switch is a demo convenience; a real deployment requires a proper login per user.",
  ],
  crmParallel: [
    "Salesforce Profiles + ",
    { mono: "Permission Sets" },
    ": permissions travel with the identity, not the page.",
  ],
};

/** Session model → demo-session sandboxing (no CRM PARALLEL — a stretch here). */
export const sessionModelExplainer: ExplainerContent = {
  pattern: [
    "A sandboxed demo session: your visit is isolated so you can explore freely without affecting anyone else's demo or the starting data.",
  ],
  how: [
    "You enter passwordlessly into a server session (a ",
    { mono: "pf_session" },
    " cookie); switching personas re-mints it as a different seeded user.",
  ],
  realVsSimulated: [
    "Passwordless entry, the server session, and the live countdown are real today. ",
    { mono: "session-scoped" },
    " record overlays and one-click reset arrive later in P1.8.",
  ],
};

/** Surface toggle → the two-surface model (Epic 24). The "demo convenience" copy:
 *  one app split into a public storefront and a staff-only workspace; the one-click
 *  toggle changes surface, NOT identity / NOT a role. */
export const surfaceToggleExplainer: ExplainerContent = {
  pattern: [
    "Two surfaces for two audiences: a public storefront where customers shop, and an internal workspace where staff work. In production these are genuinely separate front ends.",
  ],
  how: [
    "Here both surfaces are one app split into two route zones — the public ",
    { mono: "/site" },
    " storefront and the staff-only ",
    { mono: "/app" },
    " workspace, guarded by a real server session. Toggling just navigates between them, and the ",
    { mono: "pf_session" },
    " cookie rides along so you stay signed in.",
  ],
  realVsSimulated: [
    "The split between a public customer surface and a private staff surface is real architecture. The one-click toggle that carries you across — and the fact that flipping surface never changes who you are — is a demo convenience: a real deployment would be two separate front ends with their own sign-ins. It changes surface, not identity, and never a role.",
  ],
  crmParallel: [
    "Salesforce ",
    { mono: "Experience Cloud" },
    " — a public community/storefront site — beside the internal CRM org: one platform and dataset, two distinct front ends for customers versus staff.",
  ],
};
