import { useCallback, useRef, useState } from "react";
import type { ComponentType, SVGProps } from "react";
import { Calendar, ClockRotateRight } from "iconoir-react";
import Button from "./Button.tsx";
import { useFocusTrap } from "./useFocusTrap.ts";
import { runAepSweep, runAnniversarySweep } from "../api";
import type { RenewalSweepResult } from "../api";

// The Platform-Admin renewal-sweep control (P2.4 Epic 6/8) — a masthead affordance
// that runs one renewal sweep over the visitor's OWN demo session in its
// currently-selected tenant, then reports the {generated, skipped} counts. There are
// two of them in the masthead right cluster beside WorkspaceResetControl (the Masthead
// gates both on Platform Admin): the AEP sweep and the anniversary sweep. They differ
// only in their copy, their endpoint, and their glyph — everything else is shared — so
// this is ONE component driven by a `variant`, rendered twice, rather than two
// near-identical components. Each variant's `key` prefixes every element id so the two
// live instances never collide (the repo's unique-id rule).
//
// It mirrors WorkspaceResetControl's SELF-CONTAINED popover idiom: each instance owns
// its own open flag, its own sweep call, and all of its own feedback, so the Masthead
// stays props-only. The surface is the Guide §6.2 anchored, focus-trapped popover
// (reusing the popover-root / popover-surface aesthetic and useFocusTrap) rather than a
// scrim modal — a sweep is a light, non-destructive operational action. A single Run
// button drives the call; the result and the error each announce through their own
// aria-live region, and the surface stays open on either outcome so the admin can read
// the counts or retry.

// The iconoir glyph a variant renders — typed to the props this control passes.
type SweepIcon = ComponentType<SVGProps<SVGSVGElement>>;

/** Everything that distinguishes one sweep control from the other. */
export interface RenewalSweepVariant {
  /** Short key prefixing every element id (e.g. `"aep"`, `"anniversary"`). */
  key: string;
  /** The trigger button's `aria-label` + `title`. */
  triggerLabel: string;
  /** The popover heading. */
  title: string;
  /** The explanatory sentence under the heading. */
  description: string;
  /** The api call this variant fires. */
  runSweep: () => Promise<RenewalSweepResult>;
  /** The masthead glyph. */
  Icon: SweepIcon;
}

/** The AEP (Medicare Advantage) renewal-sweep variant — P2.4 Epic 6. */
export const AEP_SWEEP_VARIANT: RenewalSweepVariant = {
  key: "aep",
  triggerLabel: "Run AEP renewal sweep",
  title: "Run AEP renewal sweep",
  description:
    "Generates renewal opportunities for this tenant's active Medicare Advantage " +
    "policies in your demo session. Running it again is safe — already-renewed " +
    "policies are skipped.",
  // A thunk, not the bare reference, so the api binding is read only when a sweep
  // actually runs — module-eval stays free of it (partial `../api` test mocks that
  // never trigger a sweep don't need to stub these functions).
  runSweep: () => runAepSweep(),
  Icon: Calendar,
};

/** The anniversary renewal-sweep variant — P2.4 Epic 8. */
export const ANNIVERSARY_SWEEP_VARIANT: RenewalSweepVariant = {
  key: "anniversary",
  triggerLabel: "Run anniversary renewal sweep",
  title: "Run anniversary renewal sweep",
  description:
    "Generates renewal opportunities for this tenant's active anniversary-line " +
    "policies reaching their 60-day renewal window in your demo session. Running it " +
    "again is safe — already-renewed policies are skipped.",
  runSweep: () => runAnniversarySweep(),
  Icon: ClockRotateRight,
};

// What the sweep call is currently doing, so the idle / pending / success / error
// branches render exactly once and never overlap (the WorkspaceResetControl idiom).
type SweepState =
  | { kind: "idle" }
  | { kind: "pending" }
  | { kind: "success"; result: RenewalSweepResult }
  | { kind: "error"; message: string };

/** Human sentence for a completed sweep — e.g. "Generated 1 renewal, skipped 0." */
function resultSentence(result: RenewalSweepResult): string {
  const renewalWord = result.generated === 1 ? "renewal" : "renewals";
  return `Generated ${result.generated} ${renewalWord}, skipped ${result.skipped}.`;
}

export default function RenewalSweepControl({
  variant,
}: {
  variant: RenewalSweepVariant;
}) {
  const { key, triggerLabel, title, description, runSweep, Icon } = variant;

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
      const result = await runSweep();
      setSweepState({ kind: "success", result });
    } catch {
      setSweepState({
        kind: "error",
        message: "Could not run the sweep. Please try again.",
      });
    }
  }, [runSweep]);

  // Every id is prefixed by the variant key so the two live instances never collide.
  const rootId = `app-masthead-${key}-sweep`;
  const buttonId = `${rootId}-button`;
  const surfaceId = `${rootId}-surface`;
  const titleId = `${key}-renewal-sweep-title`;
  const descriptionId = `${key}-renewal-sweep-description`;
  const resultId = `${key}-renewal-sweep-result`;
  const errorId = `${key}-renewal-sweep-error`;
  const actionsId = `${key}-renewal-sweep-actions`;
  const closeId = `${key}-renewal-sweep-close`;
  const runId = `${key}-renewal-sweep-run`;

  return (
    <span id={rootId} className="popover-root">
      <button
        id={buttonId}
        ref={triggerRef}
        type="button"
        className={`masthead-icon-button masthead-${key}-sweep-button`}
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        aria-controls={isOpen ? surfaceId : undefined}
        aria-label={triggerLabel}
        title={triggerLabel}
        onClick={toggleSurface}
      >
        <Icon
          id={`${key}-renewal-sweep-glyph`}
          width={18}
          height={18}
          aria-hidden="true"
          className={`masthead-${key}-sweep-glyph`}
        />
      </button>

      {isOpen && (
        <div
          id={surfaceId}
          ref={surfaceRef}
          className="popover-surface renewal-sweep-surface"
          role="dialog"
          aria-labelledby={titleId}
          aria-describedby={descriptionId}
          tabIndex={-1}
        >
          <h2 id={titleId} className="renewal-sweep-title">
            {title}
          </h2>
          <p id={descriptionId} className="renewal-sweep-description">
            {description}
          </p>

          {/* The success result — its own aria-live region so a screen reader
              announces the counts in place. Rendered empty otherwise so a re-run
              re-announces cleanly. */}
          <p
            id={resultId}
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
            id={errorId}
            className="renewal-sweep-error"
            role="status"
            aria-live="polite"
          >
            {sweepState.kind === "error" ? sweepState.message : ""}
          </p>

          <div id={actionsId} className="renewal-sweep-actions">
            <Button
              id={closeId}
              variant="text"
              onClick={closeSurface}
              disabled={sweepState.kind === "pending"}
            >
              Close
            </Button>
            <Button
              id={runId}
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
