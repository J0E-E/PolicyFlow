// "Simulated" official-notice copy catalog (Epic 20) — the JSX-free data behind
// every SimulatedBadge popover, mirroring explainerContent.ts (Epic 19).
//
// The Guide §6.3 "Simulated" stamp opens an "official notice" card with three
// ruled small-caps sections — WHAT IS MOCKED / WHAT IS REAL / THE ADAPTER SEAM —
// with mechanism / adapter names set in `--font-mono`. Keeping the copy here
// (data, not JSX) means a new simulated surface adds an entry, never a new
// component (the seam Epic 21's "How it's built" legend and the P1.7 simulated
// surfaces — quotes, enrichment, CRM records & sync, outbox — build on).
//
// A section body is a list of "runs" so mechanism / API terms render in
// `--font-mono` (the Guide's mono register) without any JSX in this data file:
// SimulatedBadge walks the runs and wraps the mono ones in <code>. A run is
// either a plain string or `{ mono: "outbox" }` — the exact "runs" model
// explainerContent.ts uses.

/** One span of section-body text: a plain string, or a mono mechanism/API term. */
export type SimulatedRun = string | { mono: string };

/** The three fixed sections of the official notice (Guide §6.3). */
export interface SimulatedNotice {
  /** "WHAT IS MOCKED" — the outside systems that return canned answers. */
  whatIsMocked: SimulatedRun[];
  /** "WHAT IS REAL" — the PolicyFlow engine that is real, working code. */
  whatIsReal: SimulatedRun[];
  /** "THE ADAPTER SEAM" — the small adapter interface every external system
   *  sits behind, and the drop-in swap to a real client. */
  theAdapterSeam: SimulatedRun[];
}

/** The fixed section order + their small-caps labels (Guide §6.3). The popover
 *  renders these three sections in this order. */
export const SIMULATED_NOTICE_SECTION_LABELS = {
  whatIsMocked: "WHAT IS MOCKED",
  whatIsReal: "WHAT IS REAL",
  theAdapterSeam: "THE ADAPTER SEAM",
} as const;

// ---- The foundational, reusable notice (confirmed copy, Epic 20 plan) ----
// The base text every later simulated surface adapts; mono term in `code`.

/** The default official notice — the reusable, foundational text every later
 *  simulated surface (Epic 21 legend, the P1.7 surfaces) adapts. */
export const defaultSimulatedNotice: SimulatedNotice = {
  whatIsMocked: [
    "The outside systems PolicyFlow reaches — carrier quoting, data enrichment, and the external CRM — return canned, deterministic answers. Nothing leaves the demo: no real network call is made and no real person is ever contacted.",
  ],
  whatIsReal: [
    "The PolicyFlow engine driving them is real, working code. The transactional ",
    { mono: "outbox" },
    ", the in-process event bus, per-consumer retries, and dead-letter handling all run end to end, exactly as they would in production.",
  ],
  theAdapterSeam: [
    "Every external system sits behind one small adapter interface. The demo wires in a simulated adapter; pointing it at a real carrier or CRM client is a drop-in swap, with no change to the engine that calls it.",
  ],
};
