import { useCallback, useRef, useState } from "react";
import { Calendar } from "iconoir-react";
import Button from "./Button.tsx";
import { useFocusTrap } from "./useFocusTrap.ts";
import { runAepSweep } from "../api";
import type { AepSweepResult } from "../api";

// The Platform-Admin AEP renewal-sweep control (P2.4 Epic 6) — a masthead
// affordance that runs `POST /api/renewals/aep-sweep` over the visitor's OWN demo
// session in its currently-selected tenant, then reports the {generated, skipped}
// counts. It sits in the masthead right cluster beside WorkspaceResetControl (the
// Masthead gates both on Platform Admin), and mirrors that control's SELF-CONTAINED
// popover idiom: it owns its own open flag, its own sweep call, and all of its own
// feedback, so the Masthead stays props-only.
//
// The surface is the Guide §6.2 anchored, focus-trapped popover (reusing the
// popover-root / popover-surface aesthetic and useFocusTrap) rather than a scrim
// modal — the sweep is a light, non-destructive operational action, not a
// destructive confirm. A single Run button drives the call; the result and the
// error each announce through their own aria-live region, and the surface stays
// open on either outcome so the admin can read the counts or retry.

// What the sweep call is currently doing, so the idle / pending / success / error
// branches render exactly once and never overlap (the WorkspaceResetControl idiom).
type SweepState =
  | { kind: "idle" }
  | { kind: "pending" }
  | { kind: "success"; result: AepSweepResult }
  | { kind: "error"; message: string };

/** Human sentence for a completed sweep — e.g. "Generated 1 renewal, skipped 0." */
function resultSentence(result: AepSweepResult): string {
  const renewalWord = result.generated === 1 ? "renewal" : "renewals";
  return `Generated ${result.generated} ${renewalWord}, skipped ${result.skipped}.`;
}

export default function RenewalSweepControl() {
  const [isOpen, setIsOpen] = useState<boolean>(false);
  const [sweepState, setSweepState] = useState<SweepState>({ kind: "idle" });

  const triggerRef = useRef<HTMLButtonElement>(null);
  const surfaceRef = useRef<HTMLDivElement>(null);

  const openSurface = useCallback(() => {
    setSweepState({ kind: "idle" });
    setIsOpen(true);
  }, []);

  const closeSurface = useCallback(() => {
    setIsOpen(false);
  }, []);

  const toggleSurface = useCallback(() => {
    if (isOpen) {
      closeSurface();
    } else {
      openSurface();
    }
  }, [isOpen, openSurface, closeSurface]);

  // useFocusTrap calls this on Esc / outside click; the argument (whether to
  // restore focus to the trigger) is irrelevant here — closing is enough.
  const handleRequestClose = useCallback(() => {
    closeSurface();
  }, [closeSurface]);

  useFocusTrap({
    isOpen,
    surfaceRef,
    triggerRef,
    onRequestClose: handleRequestClose,
  });

  const handleRunSweep = useCallback(async () => {
    setSweepState({ kind: "pending" });
    try {
      const result = await runAepSweep();
      setSweepState({ kind: "success", result });
    } catch {
      setSweepState({
        kind: "error",
        message: "Could not run the sweep. Please try again.",
      });
    }
  }, []);

  return (
    <span id="app-masthead-aep-sweep" className="popover-root">
      <button
        id="app-masthead-aep-sweep-button"
        ref={triggerRef}
        type="button"
        className="masthead-icon-button masthead-aep-sweep-button"
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        aria-controls={isOpen ? "app-masthead-aep-sweep-surface" : undefined}
        aria-label="Run AEP renewal sweep"
        title="Run AEP renewal sweep"
        onClick={toggleSurface}
      >
        <Calendar
          width={18}
          height={18}
          aria-hidden="true"
          className="masthead-aep-sweep-glyph"
        />
      </button>

      {isOpen && (
        <div
          id="app-masthead-aep-sweep-surface"
          ref={surfaceRef}
          className="popover-surface renewal-sweep-surface"
          role="dialog"
          aria-labelledby="renewal-sweep-title"
          aria-describedby="renewal-sweep-description"
          tabIndex={-1}
        >
          <h2 id="renewal-sweep-title" className="renewal-sweep-title">
            Run AEP renewal sweep
          </h2>
          <p id="renewal-sweep-description" className="renewal-sweep-description">
            Generates renewal opportunities for this tenant's active Medicare
            Advantage policies in your demo session. Running it again is safe —
            already-renewed policies are skipped.
          </p>

          {/* The success result — its own aria-live region so a screen reader
              announces the counts in place. Rendered empty otherwise so a re-run
              re-announces cleanly. */}
          <p
            id="renewal-sweep-result"
            className="renewal-sweep-result"
            role="status"
            aria-live="polite"
          >
            {sweepState.kind === "success"
              ? resultSentence(sweepState.result)
              : ""}
          </p>

          {/* The inline failure notice — its own aria-live region; the surface stays
              open so the Run button below is a ready retry. */}
          <p
            id="renewal-sweep-error"
            className="renewal-sweep-error"
            role="status"
            aria-live="polite"
          >
            {sweepState.kind === "error" ? sweepState.message : ""}
          </p>

          <div id="renewal-sweep-actions" className="renewal-sweep-actions">
            <Button
              id="renewal-sweep-close"
              variant="text"
              onClick={closeSurface}
              disabled={sweepState.kind === "pending"}
            >
              Close
            </Button>
            <Button
              id="renewal-sweep-run"
              variant="filled"
              onClick={handleRunSweep}
              isPending={sweepState.kind === "pending"}
            >
              Run sweep
            </Button>
          </div>
        </div>
      )}
    </span>
  );
}
