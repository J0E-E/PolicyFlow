import { useCallback, useMemo, useState } from "react";
import { STEPPER_STEPS } from "./stepperSteps.ts";

// The in-memory state machine behind the guided docket (Guide §6.6 — "tracking
// walkthrough progress with checkmarks"). It owns three things: which steps are
// completed (a Set of step numbers), which one step is active/expanded, and whether
// the docket panel is open or dismissed to its corner tab.
//
// IN-MEMORY ONLY, deliberately (TDD Decision 9): progress resets on reload. This hook
// is the SEAM P1.8 swaps for durable, session-aware persistence — its actions are the
// contract a persisted version must keep, so callers (the docket, the demo-home opener)
// never change. No JSX here, so it stays its own clean Vite fast-refresh module,
// mirroring the api/ and session/ splits.

const FIRST_STEP_NUMBER = STEPPER_STEPS[0].number;
const TOTAL_STEPS = STEPPER_STEPS.length;
const LAST_STEP_NUMBER = STEPPER_STEPS[TOTAL_STEPS - 1].number;

/** The docket's state plus the actions that change it (a learner's-readable surface). */
export interface GuidedDocketState {
  /** Whether the floating panel is open (true) or dismissed to its corner tab (false). */
  isOpen: boolean;
  /** The step number currently expanded (accordion — exactly one at a time). */
  activeStepNumber: number;
  /** The set of completed step numbers (checkmarked). */
  completedStepNumbers: ReadonlySet<number>;
  /** How many steps are done — the "X" in the "X / 21" progress readout. */
  completedCount: number;
  /** The total step count — the "21" in "X / 21". */
  totalSteps: number;
  /**
   * Increments on every `open()` call. The panel watches this (not just `isOpen`) so
   * the demo-home opener can move focus to the docket even when it is already open —
   * a re-open while open changes no boolean but does bump this counter.
   */
  openRequestCount: number;
  /** Open the panel (from the corner tab or the demo-home opener) and focus it. */
  open: () => void;
  /** Dismiss the panel to its corner reopen tab. */
  dismiss: () => void;
  /** Make a step the active (expanded) one — the accordion toggle. */
  setActiveStep: (stepNumber: number) => void;
  /** Mark the active step done and advance the active pointer to the next step. */
  markActiveStepDoneAndAdvance: () => void;
}

/**
 * The docket state hook. Starts OPEN on the first step with nothing completed —
 * a visitor lands in the workspace with the tour ready to begin (Guide §6.6).
 */
export function useGuidedDocket(): GuidedDocketState {
  const [isOpen, setIsOpen] = useState(true);
  const [openRequestCount, setOpenRequestCount] = useState(0);
  const [activeStepNumber, setActiveStepNumber] = useState(FIRST_STEP_NUMBER);
  const [completedStepNumbers, setCompletedStepNumbers] = useState<
    ReadonlySet<number>
  >(() => new Set<number>());

  const open = useCallback(() => {
    setIsOpen(true);
    setOpenRequestCount((previous) => previous + 1);
  }, []);
  const dismiss = useCallback(() => setIsOpen(false), []);
  const setActiveStep = useCallback(
    (stepNumber: number) => setActiveStepNumber(stepNumber),
    [],
  );

  const markActiveStepDoneAndAdvance = useCallback(() => {
    setCompletedStepNumbers((previous) => {
      const next = new Set(previous);
      next.add(activeStepNumber);
      return next;
    });
    // Advance the active pointer to the next step; the last step stays active
    // (there is nowhere further to go — it just gets its checkmark).
    if (activeStepNumber < LAST_STEP_NUMBER) {
      setActiveStepNumber(activeStepNumber + 1);
    }
  }, [activeStepNumber]);

  return useMemo(
    () => ({
      isOpen,
      activeStepNumber,
      completedStepNumbers,
      completedCount: completedStepNumbers.size,
      totalSteps: TOTAL_STEPS,
      openRequestCount,
      open,
      dismiss,
      setActiveStep,
      markActiveStepDoneAndAdvance,
    }),
    [
      isOpen,
      openRequestCount,
      activeStepNumber,
      completedStepNumbers,
      open,
      dismiss,
      setActiveStep,
      markActiveStepDoneAndAdvance,
    ],
  );
}
