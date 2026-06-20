import { useState } from "react";
import Button from "../components/Button.tsx";
import { qualifyLead, rejectLead } from "../api";
import type { MaskedLead } from "../api";

// The status-gated qualify / reject actions on the lead detail page (Epic 21).
// Both transitions are `Working → terminal`, so this section ONLY renders for a
// `Working` lead AND only for a holder of `create_edit_records` (the page decides
// whether to render it at all; non-Working / no-permission shows nothing). Claim
// is deliberately omitted — a `New` unflagged lead is claimed from the Epic 20
// queue first, so the detail page never claims.
//
//   - Qualify is a filled primary action (the happy outcome).
//   - Reject is outlined; activating it reveals an inline optional reason textarea
//     (≤1000 chars, mirroring the backend cap) + Confirm / Cancel. A reason-less
//     reject is allowed (the server defaults the reason kind).
//
// On success each call returns the updated masked lead; `onLeadChange` lifts it to
// the page so the header stamp flips and this section disappears (the new status is
// no longer `Working`). A failure surfaces a non-destructive inline error.

/** The free-text reject reason cap — mirrors the backend `RejectLeadRequest`. */
const REJECT_REASON_MAX_LENGTH = 1000;

/** Which action is mid-flight (so its button shows the spinner), or none. */
type PendingAction = "qualify" | "reject" | null;

interface LeadActionsSectionProperties {
  /** The (Working) lead these actions transition. */
  lead: MaskedLead;
  /** Lift the updated masked lead to the page after a successful transition. */
  onLeadChange: (lead: MaskedLead) => void;
}

export default function LeadActionsSection({
  lead,
  onLeadChange,
}: LeadActionsSectionProperties) {
  // Whether the inline reject form (reason textarea + Confirm/Cancel) is open.
  const [isRejecting, setIsRejecting] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [pendingAction, setPendingAction] = useState<PendingAction>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const runQualify = () => {
    setErrorMessage(null);
    setPendingAction("qualify");
    qualifyLead(lead.id)
      .then((updated) => onLeadChange(updated))
      .catch(() => {
        setErrorMessage(
          "We couldn't qualify this lead. Please try again.",
        );
      })
      .finally(() => setPendingAction(null));
  };

  const runReject = () => {
    setErrorMessage(null);
    setPendingAction("reject");
    // An empty textarea sends no reason (a reason-less reject is allowed).
    const trimmedReason = rejectReason.trim();
    rejectLead(lead.id, { reason: trimmedReason === "" ? null : trimmedReason })
      .then((updated) => onLeadChange(updated))
      .catch(() => {
        setErrorMessage("We couldn't reject this lead. Please try again.");
      })
      .finally(() => setPendingAction(null));
  };

  const cancelReject = () => {
    setIsRejecting(false);
    setRejectReason("");
    setErrorMessage(null);
  };

  return (
    <section
      id="lead-detail-actions"
      className="lead-detail-actions"
      aria-label="Lead actions"
    >
      <h2 id="lead-detail-actions-title" className="lead-detail-actions-title">
        Actions
      </h2>

      {errorMessage !== null && (
        <p
          id="lead-detail-actions-error"
          className="lead-detail-actions-error"
          role="alert"
        >
          {errorMessage}
        </p>
      )}

      <div id="lead-detail-actions-buttons" className="lead-detail-actions-buttons">
        <Button
          id="lead-detail-qualify-button"
          variant="filled"
          isPending={pendingAction === "qualify"}
          disabled={isRejecting}
          onClick={runQualify}
        >
          Qualify
        </Button>
        {!isRejecting && (
          <Button
            id="lead-detail-reject-button"
            variant="outlined"
            onClick={() => {
              setErrorMessage(null);
              setIsRejecting(true);
            }}
          >
            Reject
          </Button>
        )}
      </div>

      {/* The inline reject form — an optional reason, then Confirm / Cancel. */}
      {isRejecting && (
        <div id="lead-detail-reject-form" className="lead-detail-reject-form">
          <label
            id="lead-detail-reject-reason-label"
            className="lead-detail-reject-reason-label"
            htmlFor="lead-detail-reject-reason"
          >
            Reason (optional)
          </label>
          <textarea
            id="lead-detail-reject-reason"
            className="lead-detail-reject-reason"
            value={rejectReason}
            maxLength={REJECT_REASON_MAX_LENGTH}
            rows={3}
            onChange={(event) => setRejectReason(event.target.value)}
          />
          <div
            id="lead-detail-reject-form-actions"
            className="lead-detail-reject-form-actions"
          >
            <Button
              id="lead-detail-reject-confirm-button"
              variant="filled"
              isPending={pendingAction === "reject"}
              onClick={runReject}
            >
              Confirm reject
            </Button>
            <Button
              id="lead-detail-reject-cancel-button"
              variant="text"
              onClick={cancelReject}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}
