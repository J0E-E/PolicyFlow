import { useEffect, useRef } from "react";
import { Xmark, List } from "iconoir-react";
import { STEPPER_STEPS } from "./stepperSteps.ts";
import { useGuidedDocketContext } from "./GuidedDocketContext.ts";
import GuidedDocketStep from "./GuidedDocketStep.tsx";

// The floating guided-walkthrough docket (Guide §6.6 — "a persistent, dismissible
// docket … a numbered table-of-contents overlay (01–21) tracking walkthrough
// progress"). Mounted shell-wide in AppShell at --z-stepper, it persists over every
// /app surface and reads its ONE shared state from GuidedDocketContext.
//
// Two shapes from the same state:
//   OPEN     — the floating panel: a labelled header (title + "X / 21" progress + a
//              dismiss control), then the scrolling list of 21 step rows.
//   DISMISSED — a small pinned corner tab ("Guided walkthrough") that reopens the panel
//              from any /app screen.
//
// CONTRACT (mirrors the Epic 9 Popover): non-modal, NO scrim — it never blocks the
// workspace. It is a labelled region (role="region" + aria-label), NOT a modal dialog,
// so there is no focus trap; focus order is natural DOM order. Meaning is carried by
// text, never icon/color alone (Guide §7) — the dismiss/reopen controls and the
// checkmarks all have text labels. Every element gets a unique descriptive id (CLAUDE.md).
export default function GuidedDocket() {
  const {
    isOpen,
    openRequestCount,
    activeStepNumber,
    completedStepNumbers,
    completedCount,
    totalSteps,
    open,
    dismiss,
    setActiveStep,
    markActiveStepDoneAndAdvance,
  } = useGuidedDocketContext();

  // Move focus into the panel when it is opened explicitly (the corner tab or the
  // demo-home opener) so keyboard users land on it — but NOT on the initial mount,
  // which would steal focus from the page. The opener bumps `openRequestCount` on
  // every open (even when already open), so we focus whenever that count advances.
  const panelRef = useRef<HTMLElement | null>(null);
  const lastFocusedRequestCount = useRef(0);
  useEffect(() => {
    if (
      isOpen &&
      openRequestCount > 0 &&
      openRequestCount !== lastFocusedRequestCount.current
    ) {
      lastFocusedRequestCount.current = openRequestCount;
      panelRef.current?.focus();
    }
  }, [isOpen, openRequestCount]);

  // Dismissed: the collapsed corner reopen tab. A real button so it is keyboard
  // reachable and announces its purpose; reopening works on any /app screen because
  // the docket is mounted in the shell, not on one page.
  if (!isOpen) {
    return (
      <button
        id="guided-docket-reopen"
        type="button"
        className="guided-docket-reopen"
        onClick={open}
      >
        <List
          width={18}
          height={18}
          aria-hidden="true"
          className="guided-docket-reopen-icon"
        />
        <span
          id="guided-docket-reopen-label"
          className="guided-docket-reopen-label"
        >
          Guided walkthrough
        </span>
      </button>
    );
  }

  return (
    <section
      id="guided-docket"
      className="guided-docket"
      aria-labelledby="guided-docket-title"
      ref={panelRef}
      tabIndex={-1}
    >
      <header id="guided-docket-header" className="guided-docket-header">
        <div
          id="guided-docket-heading-group"
          className="guided-docket-heading-group"
        >
          <h2 id="guided-docket-title" className="guided-docket-title">
            Guided walkthrough
          </h2>
          {/* Polite live region (Guide §7): marking a step done changes the count
              with no navigation, so announce "Progress: X / 21" as a whole unit
              (aria-atomic) for screen-reader users. */}
          <p
            id="guided-docket-progress"
            className="guided-docket-progress"
            aria-live="polite"
            aria-atomic="true"
          >
            <span className="guided-docket-visually-hidden">Progress: </span>
            {completedCount} / {totalSteps}
          </p>
        </div>
        <button
          id="guided-docket-dismiss"
          type="button"
          className="guided-docket-dismiss"
          onClick={dismiss}
        >
          <Xmark
            width={18}
            height={18}
            aria-hidden="true"
            className="guided-docket-dismiss-icon"
          />
          <span className="guided-docket-visually-hidden">
            Dismiss the guided walkthrough
          </span>
        </button>
      </header>

      <ol id="guided-docket-list" className="guided-docket-list">
        {STEPPER_STEPS.map((step) => (
          <GuidedDocketStep
            key={step.number}
            id={`guided-docket-step-${step.number}`}
            step={step}
            isCompleted={completedStepNumbers.has(step.number)}
            isActive={step.number === activeStepNumber}
            onActivate={() => setActiveStep(step.number)}
            onMarkDone={markActiveStepDoneAndAdvance}
          />
        ))}
      </ol>
    </section>
  );
}
