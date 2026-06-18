import { Fragment } from "react";
import Popover from "./Popover.tsx";
import ExplainerIcon from "./ExplainerIcon.tsx";
import {
  EXPLAINER_SECTION_LABELS,
  type ExplainerContent,
  type ExplainerRun,
} from "./explainerContent.ts";

interface ExplainerPopoverProperties {
  /** Required so every rendered element is uniquely targetable (CLAUDE.md).
   *  The wrapped Popover derives `${id}-trigger` / `${id}-surface` from this. */
  id: string;
  /** A short name for the surface being explained (e.g. "event-driven
   *  operations"). Forms the trigger's accessible name and the panel's label. */
  surfaceLabel: string;
  /** The four-section copy for this surface (from explainerContent.ts). */
  content: ExplainerContent;
  /** Optional extra class on the trigger button — Masthead passes its on-ink-aware
   *  trigger styling so the focus ring stays visible under the Platform-Admin
   *  inversion (Epic 11's --focus-ring-on-ink). */
  triggerClassName?: string;
}

// The Guide §6.2 explainer popover: an info-icon that opens a dismissible
// margin-note with four fixed small-caps sections — PATTERN / HOW POLICYFLOW
// DOES IT / REAL VS SIMULATED / CRM PARALLEL — the last omitted when a surface
// supplies no copy. It wraps the Epic 9 Popover primitive (which owns the trigger
// button, open state, focus trap, and Esc/outside-click close), supplying only
// the info-icon trigger and the rendered sections. Mechanism / API terms set in
// `--font-mono` via <code> — driven by the "runs" model in explainerContent.ts,
// so the copy stays JSX-free data. Renders identically for every role. This is
// the template every later explainer follows (Epic 20 badge, Epic 24 toggle).
export default function ExplainerPopover({
  id,
  surfaceLabel,
  content,
  triggerClassName,
}: ExplainerPopoverProperties) {
  // The four sections in fixed order; CRM PARALLEL drops out when absent.
  const sections: { key: keyof typeof EXPLAINER_SECTION_LABELS; runs: ExplainerRun[] }[] =
    [
      { key: "pattern", runs: content.pattern },
      { key: "how", runs: content.how },
      { key: "realVsSimulated", runs: content.realVsSimulated },
    ];
  if (content.crmParallel) {
    sections.push({ key: "crmParallel", runs: content.crmParallel });
  }

  return (
    <Popover
      id={id}
      trigger={<ExplainerIcon id={`${id}-icon`} />}
      triggerLabel={`Explain: ${surfaceLabel}`}
      triggerClassName={
        triggerClassName ? `explainer-trigger ${triggerClassName}` : "explainer-trigger"
      }
      surfaceLabel={`How this works: ${surfaceLabel}`}
    >
      <div id={`${id}-sections`} className="explainer-sections">
        {sections.map((section) => (
          <section
            key={section.key}
            id={`${id}-section-${section.key}`}
            className="explainer-section"
          >
            <h3
              id={`${id}-label-${section.key}`}
              className="explainer-section-label"
            >
              {EXPLAINER_SECTION_LABELS[section.key]}
            </h3>
            <p id={`${id}-body-${section.key}`} className="explainer-section-body">
              {section.runs.map((run, runIndex) =>
                typeof run === "string" ? (
                  <Fragment key={runIndex}>{run}</Fragment>
                ) : (
                  <code
                    key={runIndex}
                    id={`${id}-mono-${section.key}-${runIndex}`}
                    className="explainer-mono"
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
