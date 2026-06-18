import { Fragment } from "react";
import { Flask } from "iconoir-react";
import Popover from "./Popover.tsx";
import StampTag from "./StampTag.tsx";
import {
  SIMULATED_NOTICE_SECTION_LABELS,
  defaultSimulatedNotice,
  type SimulatedNotice,
  type SimulatedRun,
} from "./simulatedNotice.ts";

interface SimulatedBadgeProperties {
  /** Required so every rendered element is uniquely targetable (CLAUDE.md).
   *  The wrapped Popover derives `${id}-trigger` / `${id}-surface` from this. */
  id: string;
  /** A short name for the simulated surface (e.g. "the demo overall", "carrier
   *  quoting") — forms the trigger's accessible name and the panel's label. */
  surfaceLabel: string;
  /** The three-section official notice for this surface. Defaults to the
   *  foundational reusable copy; later surfaces pass their own adapted entry. */
  notice?: SimulatedNotice;
}

// The Guide §6.3 "Simulated" stamp: a dashed-border warning stamp (flask icon +
// "SIMULATED" in Stamp type) that opens an "official notice" card with three
// ruled small-caps sections — WHAT IS MOCKED / WHAT IS REAL / THE ADAPTER SEAM.
// It wraps the Epic 9 Popover primitive (which owns the trigger button, open
// state, focus trap, and Esc/outside-click close) exactly as Epic 19's
// ExplainerPopover does, supplying only the dashed warning-stamp trigger and the
// rendered sections. The stamp reuses the Epic 8 StampTag warning styling; the
// 1px DASHED border (the Guide §6.3 "border law": dashed = not yet real, never to
// be confused with a solid real warning) is overridden in styles/simulated-badge.css.
// Mechanism / adapter terms set in `--font-mono` via <code> — driven by the
// "runs" model in simulatedNotice.ts, so the copy stays JSX-free data. Renders
// identically for every role. The seam every later simulated surface builds on
// (Epic 21 legend, the P1.7 simulated surfaces): a new surface adds a catalog
// entry, not a new component.
export default function SimulatedBadge({
  id,
  surfaceLabel,
  notice = defaultSimulatedNotice,
}: SimulatedBadgeProperties) {
  // The three sections in fixed order (Guide §6.3).
  const sections: {
    key: keyof typeof SIMULATED_NOTICE_SECTION_LABELS;
    runs: SimulatedRun[];
  }[] = [
    { key: "whatIsMocked", runs: notice.whatIsMocked },
    { key: "whatIsReal", runs: notice.whatIsReal },
    { key: "theAdapterSeam", runs: notice.theAdapterSeam },
  ];

  return (
    <Popover
      id={id}
      trigger={
        <StampTag
          id={`${id}-stamp`}
          status="warning"
          icon={<Flask width={14} height={14} aria-hidden="true" />}
        >
          Simulated
        </StampTag>
      }
      triggerLabel={`Simulated: ${surfaceLabel} — what is mocked vs real`}
      triggerClassName="simulated-badge-trigger"
      surfaceLabel={`Simulated: ${surfaceLabel}`}
    >
      <div id={`${id}-sections`} className="simulated-notice-sections">
        {sections.map((section) => (
          <section
            key={section.key}
            id={`${id}-section-${section.key}`}
            className="simulated-notice-section"
          >
            <h3
              id={`${id}-label-${section.key}`}
              className="simulated-notice-section-label"
            >
              {SIMULATED_NOTICE_SECTION_LABELS[section.key]}
            </h3>
            <p
              id={`${id}-body-${section.key}`}
              className="simulated-notice-section-body"
            >
              {section.runs.map((run, runIndex) =>
                typeof run === "string" ? (
                  <Fragment key={runIndex}>{run}</Fragment>
                ) : (
                  <code
                    key={runIndex}
                    id={`${id}-mono-${section.key}-${runIndex}`}
                    className="simulated-notice-mono"
                  >
                    {run.mono}
                  </code>
                ),
              )}
            </p>
          </section>
        ))}
      </div>
    </Popover>
  );
}
