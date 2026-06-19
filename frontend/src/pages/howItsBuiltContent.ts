// "How it's built" content catalog (Epic 21) — the JSX-free data behind the public
// /how-its-built page, mirroring explainerContent.ts (Epic 19) and simulatedNotice.ts
// (Epic 20). Keeping the editorial copy here (data, not JSX) means a later phase adds
// a pattern entry as data, never a new component — the page's growth seam (P1.7+ adds
// a showcase entry per pattern as those surfaces ship).
//
// A pattern-card body is a list of "runs" so mechanism / API terms render in
// `--font-mono` (the Guide's mono register) without any JSX in this data file:
// PatternCard walks the runs and wraps the mono ones in <code>. A run is either a
// plain string or `{ mono: "schema-per-tenant" }` — the exact "runs" model
// explainerContent.ts uses, reused here as the shared `ExplainerRun` type.

import type { ExplainerRun } from "../components/explainerContent.ts";

/** One pattern in the showcase index — a real P1.1–P1.5 backend pattern, deep-linked
 *  to its real source directory on GitHub. */
export interface PatternEntry {
  /** Stable, unique key — drives the card's ids and React key. */
  key: string;
  /** The pattern's human title (the card heading). */
  title: string;
  /** The card body as runs, so mechanism terms set in `--font-mono` via <code>. */
  body: ExplainerRun[];
  /** The real source directory under the repo root (e.g. "core/app/auth"); the card
   *  composes the full GitHub tree URL from it. */
  githubPath: string;
}

/** The repo's GitHub tree URL prefix — coarse directory links to the real source on
 *  `main` (all five paths verified to exist). A card's href is this + its githubPath. */
export const GITHUB_TREE_BASE =
  "https://github.com/J0E-E/PolicyFlow/tree/main/";

/** The motivation editorial ("Why PolicyFlow") carried by the hero. */
export const howItsBuiltMotivation =
  "PolicyFlow is a working portrait of the engineering a regulated industry actually " +
  "demands — not a slide deck describing it, but the real thing you can click through. " +
  "Insurance operations need tenant data kept rigorously apart, customer records " +
  "encrypted, every action audited, and a lot of asynchronous work that has to survive " +
  "failure. PolicyFlow builds those patterns end to end and puts them on screen, so the " +
  "machinery is the thing you see, not a footnote to it.";

/** The five real P1.1–P1.5 backend patterns, in showcase order. Each deep-links to its
 *  real source directory on GitHub (Epic 21 decision 2; coarse directory links). */
export const howItsBuiltPatterns: PatternEntry[] = [
  {
    key: "auth",
    title: "Authentication & role-based access",
    body: [
      "You sign in to a real server session; what you can see and do follows your role's ",
      { mono: "capability matrix" },
      ", enforced on the server for every action — never by hiding buttons on the screen.",
    ],
    githubPath: "core/app/auth",
  },
  {
    key: "tenancy",
    title: "Multi-tenant isolation",
    body: [
      "Two agencies run on one platform and neither can ever see the other's data. Each " +
        "tenant's records live in their own Postgres schema (",
      { mono: "schema-per-tenant" },
      "), selected per request from the signed-in identity — there's no shared customer " +
        "table to leak across.",
    ],
    githubPath: "core/app/tenancy",
  },
  {
    key: "pii",
    title: "Encrypted customer records",
    body: [
      "Sensitive customer fields are sealed with per-record keys (",
      { mono: "envelope encryption" },
      "). A separate ",
      { mono: "blind index" },
      " lets the app find a record by an encrypted value — e.g. an email — without ever " +
        "storing that value in the clear.",
    ],
    githubPath: "core/app/pii",
  },
  {
    key: "audit",
    title: "Append-only audit trail",
    body: [
      "Every meaningful action writes an immutable record — who did what, when, and " +
        "whether it succeeded — to an ",
      { mono: "append-only" },
      " log that can be added to but never edited or deleted.",
    ],
    githubPath: "core/app/audit",
  },
  {
    key: "events",
    title: "Event-driven engine",
    body: [
      "A state change writes its event in the same database transaction as the data (a " +
        "transactional ",
      { mono: "outbox" },
      "), then an in-process event bus delivers it to consumers with per-consumer retry " +
        "and dead-letter handling.",
    ],
    githubPath: "core/app/events",
  },
];

/** The ink-console architecture placeholder + real-vs-simulated legend copy. The
 *  annotated diagram itself arrives with the P1.7 showcase surfaces; today the console
 *  carries this placeholder note and the legend. */
export const architectureConsoleContent = {
  /** The stamp overline titling the ink console (Guide §6 — console title register). */
  overline: "Architecture",
  /** The placeholder note — the diagram grows with the P1.7 showcase surfaces. */
  placeholderNote:
    "The annotated architecture diagram arrives as the showcase surfaces ship (P1.7+). " +
    "Until then, this legend states the one distinction that runs through the whole " +
    "demo: which machinery is real, and which outside systems are simulated.",
  /** The "Real engine" legend row — the working code (solid ink-token swatch). */
  realLabel: "Real engine",
  realDescription: "outbox, event bus, retries, DLQ (working code)",
  /** The "Simulated" legend row description (the SimulatedBadge supplies the stamp). */
  simulatedDescription: "carrier / enrichment / CRM adapters",
} as const;
