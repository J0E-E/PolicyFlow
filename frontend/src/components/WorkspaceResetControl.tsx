import { useCallback, useRef, useState } from "react";
import { RefreshDouble } from "iconoir-react";
import Button from "./Button.tsx";
import { useFocusTrap } from "./useFocusTrap.ts";
import { resetDemoSession } from "../api";

// The Platform-Admin workspace reset control (P1.8 Epic 11) — a destructive
// masthead affordance that wipes the visitor's OWN demo session back to a clean
// slate, keeping the session, cookie, and countdown alive. It lives in the
// masthead right cluster beside the DEMO SESSION countdown, the session UI it
// resets, and renders ONLY for Platform Admin (the Masthead gates it).
//
// It is SELF-CONTAINED in the RoleSwitcher / DemoSessionCountdown idiom: it owns
// its own modal-open flag, its own `POST /api/demo/session/reset` call, and all of
// its own feedback, so the Masthead stays props-only and gains no new prop.
//
// The confirm step is a true modal (the Guide §5 Dialog pattern, the same idiom as
// ScenarioReferencePanel): a full-viewport scrim (--scrim) centring a paper dialog
// sheet (--surface-2 at --radius-lg + --elevation-3 — the Epic 6 token set stops at
// --surface-3, so the sheet uses --surface-2, the Guide's "cards, sheets" surface
// the existing dialog already uses; the plan named --surface-4), with focus trapped
// inside it (reusing useFocusTrap) and focus restored to the opener on close.
//
// Feedback is self-contained (the RoleSwitcher idiom): the Reset button shows a
// pending spinner during the call; on success the dialog body swaps to a brief
// confirmation nudging the visitor to switch to Agent to see their fresh queue,
// then closes after a beat; on failure an inline aria-live error shows and the
// dialog stays open to retry.

// How long the success confirmation lingers before the dialog auto-closes.
const SUCCESS_CLOSE_DELAY_MS = 2_200;

// What the reset call is currently doing, so the confirm / pending / success /
// error branches render exactly once and never overlap (the LoadState idiom).
type ResetState =
  | { kind: "confirm" }
  | { kind: "pending" }
  | { kind: "success" }
  | { kind: "error"; message: string };

export default function WorkspaceResetControl() {
  const [isOpen, setIsOpen] = useState<boolean>(false);
  const [resetState, setResetState] = useState<ResetState>({ kind: "confirm" });

  const triggerRef = useRef<HTMLButtonElement>(null);
  const surfaceRef = useRef<HTMLDivElement>(null);
  // The pending auto-close timer, cleared if the dialog is dismissed first so a
  // late timer never re-closes a reopened dialog.
  const closeTimerRef = useRef<number | null>(null);

  const clearCloseTimer = useCallback(() => {
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
  }, []);

  const openDialog = useCallback(() => {
    clearCloseTimer();
    setResetState({ kind: "confirm" });
    setIsOpen(true);
  }, [clearCloseTimer]);

  const closeDialog = useCallback(() => {
    clearCloseTimer();
    setIsOpen(false);
  }, [clearCloseTimer]);

  // useFocusTrap calls this on Esc / outside click; the dialog cannot be dismissed
  // mid-flight (no focusable controls show while pending), so a close here is always
  // a user cancel or a post-result dismissal.
  const handleRequestClose = useCallback(() => {
    closeDialog();
  }, [closeDialog]);

  useFocusTrap({
    isOpen,
    surfaceRef,
    triggerRef,
    onRequestClose: handleRequestClose,
  });

  const handleConfirmReset = useCallback(async () => {
    setResetState({ kind: "pending" });
    try {
      await resetDemoSession();
      setResetState({ kind: "success" });
      // Linger on the confirmation, then close — focus returns to the opener via
      // the trigger (the masthead button stays mounted across the reset).
      closeTimerRef.current = window.setTimeout(() => {
        closeTimerRef.current = null;
        setIsOpen(false);
      }, SUCCESS_CLOSE_DELAY_MS);
    } catch {
      setResetState({
        kind: "error",
        message: "Could not reset your session. Please try again.",
      });
    }
  }, []);

  return (
    <>
      <button
        id="app-masthead-reset-button"
        ref={triggerRef}
        type="button"
        className="masthead-icon-button masthead-reset-button"
        aria-haspopup="dialog"
        aria-label="Reset demo session"
        title="Reset demo session"
        onClick={openDialog}
      >
        <RefreshDouble
          width={18}
          height={18}
          aria-hidden="true"
          className="masthead-reset-glyph"
        />
      </button>

      {isOpen && (
        <div id="workspace-reset-scrim" className="workspace-reset-scrim">
          <div
            id="workspace-reset-dialog"
            ref={surfaceRef}
            className="workspace-reset-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="workspace-reset-title"
            aria-describedby="workspace-reset-description"
            tabIndex={-1}
          >
            <h2 id="workspace-reset-title" className="workspace-reset-title">
              Reset your demo session
            </h2>

            {resetState.kind === "success" ? (
              <div
                id="workspace-reset-success"
                className="workspace-reset-success"
                role="status"
                aria-live="polite"
              >
                <p
                  id="workspace-reset-success-message"
                  className="workspace-reset-success-message"
                >
                  Your session is reset to a clean slate.
                </p>
                <p
                  id="workspace-reset-success-nudge"
                  className="workspace-reset-success-nudge"
                >
                  Switch to Agent to see your fresh queue.
                </p>
              </div>
            ) : (
              <>
                <p
                  id="workspace-reset-description"
                  className="workspace-reset-description"
                >
                  This clears every lead you have created or worked in this demo
                  session, across all tenants. Your session and its countdown stay
                  alive — switching to Agent will hand you a fresh queue.
                </p>

                {/* One status line — the inline failure notice (aria-live so a
                    screen reader announces it in place). Always rendered while not
                    on the success screen so a retry announces cleanly. */}
                <p
                  id="workspace-reset-error"
                  className="workspace-reset-error"
                  role="status"
                  aria-live="polite"
                >
                  {resetState.kind === "error" ? resetState.message : ""}
                </p>

                <div
                  id="workspace-reset-actions"
                  className="workspace-reset-actions"
                >
                  <Button
                    id="workspace-reset-cancel"
                    variant="text"
                    onClick={closeDialog}
                    disabled={resetState.kind === "pending"}
                  >
                    Cancel
                  </Button>
                  <Button
                    id="workspace-reset-confirm"
                    variant="filled"
                    onClick={handleConfirmReset}
                    isPending={resetState.kind === "pending"}
                  >
                    Reset session
                  </Button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
