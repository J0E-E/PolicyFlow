import { Check, NavArrowRight } from "iconoir-react";
import type { StepperStep } from "./stepperSteps.ts";

interface GuidedDocketStepProperties {
  /** Base id for this row; every rendered element derives a unique id (CLAUDE.md). */
  id: string;
  /** The step this row renders (number, title, the two notes, optional route). */
  step: StepperStep;
  /** Whether this step is checkmarked done. */
  isCompleted: boolean;
  /** Whether this step is the active (expanded) one — exactly one row is active. */
  isActive: boolean;
  /** Make this step the active/expanded one (the accordion toggle). */
  onActivate: () => void;
  /** Mark this (active) step done and advance to the next. */
  onMarkDone: () => void;
}

// One row in the guided docket (Guide §6.6). Collapsed it shows just the number, a
// checkmark when done, and the title as an accordion toggle button. Active (expanded),
// it also shows the two notes ("what you're seeing / how it's built"), the deep link,
// and a primary "Mark done & next" action.
//
// ACCORDION: the title is a <button aria-expanded> that activates this row; exactly one
// row is active at a time (the parent owns that). The completed checkmark is an
// aria-hidden iconoir glyph in tenant --primary (Guide §6.6) — meaning is carried by
// the row's accessible state text, never by the icon/color alone (Guide §7).
//
// DEEP LINK: rendered live ONLY when the step has a `to` route; otherwise it is the
// inert "available in a later step" affordance (the Epic 12 coming-later voice), with
// no internal phase ID surfaced. No step has a `to` in this phase, so every link is
// inert; a later phase fills `to` and the live branch lights up with no change here.
export default function GuidedDocketStep({
  id,
  step,
  isCompleted,
  isActive,
  onActivate,
  onMarkDone,
}: GuidedDocketStepProperties) {
  // "01"–"21" — zero-padded, ACORD-form style (Guide §6.6 / §6.9).
  const stepLabel = String(step.number).padStart(2, "0");
  const rowClassName = [
    "guided-docket-step",
    isActive ? "guided-docket-step-active" : "",
    isCompleted ? "guided-docket-step-completed" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <li id={id} className={rowClassName}>
      <button
        id={`${id}-toggle`}
        type="button"
        className="guided-docket-step-toggle"
        aria-expanded={isActive}
        // Only reference the detail node while it is actually rendered (this row is
        // active); a collapsed row has no `${id}-detail` in the DOM, so pointing at
        // it would be a dangling reference. `aria-expanded` carries the state either way.
        aria-controls={isActive ? `${id}-detail` : undefined}
        onClick={onActivate}
      >
        <span
          id={`${id}-marker`}
          className="guided-docket-step-marker"
          aria-hidden="true"
        >
          {isCompleted ? (
            <Check
              width={16}
              height={16}
              className="guided-docket-step-check"
            />
          ) : (
            <span className="guided-docket-step-number">{stepLabel}</span>
          )}
        </span>
        <span id={`${id}-title`} className="guided-docket-step-title">
          {step.title}
        </span>
        {/* Status text carries the completion meaning for assistive tech — not the
            checkmark color (Guide §7). Visually hidden; the glyph reads for sighted
            users. */}
        <span id={`${id}-status`} className="guided-docket-visually-hidden">
          {isCompleted ? "Completed." : "Not yet completed."}
        </span>
      </button>

      {isActive && (
        <div id={`${id}-detail`} className="guided-docket-step-detail">
          <p id={`${id}-seeing`} className="guided-docket-step-note">
            <span className="guided-docket-step-note-label">
              What you're seeing
            </span>
            {step.seeing}
          </p>
          <p id={`${id}-built`} className="guided-docket-step-note">
            <span className="guided-docket-step-note-label">
              How it's built
            </span>
            {step.built}
          </p>

          {step.to ? (
            <a
              id={`${id}-link`}
              className="guided-docket-step-link"
              href={step.to}
            >
              Go to this step
            </a>
          ) : (
            <span
              id={`${id}-link`}
              className="guided-docket-step-link guided-docket-step-link-inert"
              aria-disabled="true"
            >
              Available in a later step
            </span>
          )}

          <button
            id={`${id}-mark-done`}
            type="button"
            className="button button-filled guided-docket-step-mark-done"
            onClick={onMarkDone}
          >
            <span
              id={`${id}-mark-done-label`}
              className="guided-docket-step-mark-done-label"
            >
              Mark done &amp; next
            </span>
            <NavArrowRight
              width={16}
              height={16}
              aria-hidden="true"
              className="guided-docket-step-mark-done-icon"
            />
          </button>
        </div>
      )}
    </li>
  );
}
