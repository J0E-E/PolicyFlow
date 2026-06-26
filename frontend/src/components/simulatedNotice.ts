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

// ---- Lead-timeline reaction surface (P1.9 Epic 6) ----
// The per-row badge on each sidecar reaction (enrichment.stub, sync.logger) in the
// EVENT TIMELINE console. Scoped tightly to the consumer EFFECT — it marks the canned
// result, NOT the real domain event the reaction sits under (a console-level badge
// would wrongly imply the events are simulated too). Mono terms name the consumers /
// the real bus mechanism, matching the runs model and voice above.

/** The official notice for a stub reaction row: its canned effect is mocked; the
 *  event bus / outbox / relay / fan-out that drove it are real; M3 swaps in the
 *  real enrichment / sync sidecars at the adapter seam. */
export const reactionSimulatedNotice: SimulatedNotice = {
  whatIsMocked: [
    "Only this consumer's effect. ",
    { mono: "enrichment.stub" },
    " returns a canned, deterministic quality score and ",
    { mono: "sync.logger" },
    " writes a fixed log line — neither makes a real network call or contacts anyone.",
  ],
  whatIsReal: [
    "The machinery that drove this reaction is real, working code: the in-process event bus, the per-tenant transactional ",
    { mono: "outbox" },
    ", the relay that publishes each event, and the fan-out that delivers it to every consumer all run end to end.",
  ],
  theAdapterSeam: [
    "Each consumer sits behind one small adapter interface. The demo wires in these stub effects; M3 swaps in the real enrichment and sync sidecars as a drop-in, with no change to the bus that fans out to them.",
  ],
};

// ---- Opportunity board value fields (P2.2 Epic 8) ----
// Badges the card's value fields (premium, target close date), which a simulated
// carrier-quoting surface fills in P2.3. Scoped tightly to those fields — the
// pipeline, stages, transitions, gate, and events the board drives are all real, so
// a board-wide "simulated" claim would be wrong.

/** The official notice for the opportunity value fields: the quoted values are
 *  mocked (filled by simulated carrier quoting in P2.3); the pipeline engine is
 *  real; carrier quoting sits behind the shared adapter seam. */
export const opportunityValuesSimulatedNotice: SimulatedNotice = {
  whatIsMocked: [
    "Only the value fields — the estimated annual premium and target close date. A real carrier quote sets them (arriving in P2.3); until then they show an em-dash. No real carrier is ever quoted.",
  ],
  whatIsReal: [
    "The pipeline itself is real, working code: the per-tenant stage config, the server-validated stage transitions, the Medicare eligibility gate, and the ",
    { mono: "opportunity.stage_changed" },
    " / ",
    { mono: "opportunity.lost" },
    " events each move emits on the transactional ",
    { mono: "outbox" },
    ".",
  ],
  theAdapterSeam: [
    "Carrier quoting sits behind the same small adapter interface as the other external systems; pointing it at a real quoting client is a drop-in swap, with no change to the board or the stage machine.",
  ],
};
