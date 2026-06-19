import StampTag from "./StampTag.tsx";
import SimulatedBadge from "./SimulatedBadge.tsx";
import { architectureConsoleContent } from "../pages/howItsBuiltContent.ts";

interface ArchitectureConsoleProperties {
  /** Required so every rendered element is uniquely targetable (CLAUDE.md).
   *  Derives the overline, note, and legend ids. */
  id: string;
}

// The "How it's built" ink-console panel (Epic 21, Guide §6 / §2.1). An inverted
// `--surface-ink` card titled with a stamp overline ("ARCHITECTURE"), carrying the
// architecture-diagram placeholder note and the real-vs-simulated legend. The
// annotated box-and-arrow diagram itself arrives with the P1.7 showcase surfaces;
// today the console states the one distinction that runs through the demo:
//
//   - Real engine — a solid ink-token swatch beside "outbox, event bus, retries,
//     DLQ (working code)".
//   - Simulated — the Epic 20 SimulatedBadge (its own surface label + official
//     notice popover) beside "carrier / enrichment / CRM adapters".
//
// This is the FIRST ink-console usage, so the scoped on-ink Simulated-badge variant
// (the dashed warning stamp in `--state-warning-on-ink`, the variant Epic 20
// earmarked for here) lives in styles/how-its-built.css, scoped under the
// `.architecture-console` class — an additive CSS override, no SimulatedBadge change.
// Tokens only; AA on ink (Guide §7). Composes only — copy lives in
// howItsBuiltContent.ts.
export default function ArchitectureConsole({
  id,
}: ArchitectureConsoleProperties) {
  return (
    <section id={id} className="architecture-console" aria-labelledby={`${id}-overline`}>
      <StampTag id={`${id}-overline`} variant="overline">
        {architectureConsoleContent.overline}
      </StampTag>

      <p id={`${id}-note`} className="architecture-console-note">
        {architectureConsoleContent.placeholderNote}
      </p>

      <dl id={`${id}-legend`} className="architecture-console-legend">
        <div id={`${id}-legend-real`} className="architecture-console-legend-row">
          <dt
            id={`${id}-legend-real-term`}
            className="architecture-console-legend-term"
          >
            <span
              id={`${id}-legend-real-swatch`}
              className="architecture-console-swatch"
              aria-hidden="true"
            />
            <span
              id={`${id}-legend-real-label`}
              className="architecture-console-legend-label"
            >
              {architectureConsoleContent.realLabel}
            </span>
          </dt>
          <dd
            id={`${id}-legend-real-description`}
            className="architecture-console-legend-description"
          >
            {architectureConsoleContent.realDescription}
          </dd>
        </div>

        <div
          id={`${id}-legend-simulated`}
          className="architecture-console-legend-row"
        >
          <dt
            id={`${id}-legend-simulated-term`}
            className="architecture-console-legend-term"
          >
            <SimulatedBadge
              id={`${id}-legend-simulated-badge`}
              surfaceLabel="the external adapters"
            />
          </dt>
          <dd
            id={`${id}-legend-simulated-description`}
            className="architecture-console-legend-description"
          >
            {architectureConsoleContent.simulatedDescription}
          </dd>
        </div>
      </dl>
    </section>
  );
}
