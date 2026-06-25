import { useState } from "react";
import Button from "../components/Button.tsx";
import { convertLead } from "../api";
import type { MaskedLead } from "../api";

// The convert affordance on the lead detail page (P2.1 Epic 5). It renders ONLY for
// a `Qualified` lead the caller both holds (`owner_user_id === the caller`) and may
// edit (`create_edit_records`), and never for a read-only shared seed row — the page
// decides whether to render it at all. Converting is owner-only on the backend, so
// the holder gate keeps the affordance honest.
//
// This is the *minimal* confirm (Epic 5): a single "Convert lead" primary action
// reveals a short inline explainer + Confirm / Cancel, then calls `convertLead` with
// the lead's own product lines (the common case — the richer review-and-confirm
// screen that lets the agent choose lines is Epic 6). On success the call returns the
// frozen masked lead; `onLeadChange` lifts it to the page so the header stamp flips to
// `Converted` and this section (gated on `Qualified`) disappears — the mutating
// actions are hidden on the now-frozen lead. A failure surfaces an inline error and
// leaves the lead untouched (the backend transaction rolled back).

interface LeadConvertSectionProperties {
  /** The (Qualified, held) lead this affordance converts. */
  lead: MaskedLead;
  /** Lift the frozen masked lead to the page after a successful conversion. */
  onLeadChange: (lead: MaskedLead) => void;
}

export default function LeadConvertSection({
  lead,
  onLeadChange,
}: LeadConvertSectionProperties) {
  // Whether the inline confirm (explainer + Confirm/Cancel) is open.
  const [isConfirming, setIsConfirming] = useState(false);
  const [isConverting, setIsConverting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const runConvert = () => {
    setErrorMessage(null);
    setIsConverting(true);
    convertLead(lead.id, {
      household: { mode: "new" },
      product_lines: lead.product_lines_of_interest,
    })
      .then((updated) => onLeadChange(updated))
      .catch(() => {
        setErrorMessage("We couldn't convert this lead. Please try again.");
      })
      .finally(() => setIsConverting(false));
  };

  return (
    <section
      id="lead-detail-convert"
      className="lead-detail-actions"
      aria-label="Convert lead"
    >
      <h2 id="lead-detail-convert-title" className="lead-detail-actions-title">
        Convert
      </h2>

      {errorMessage !== null && (
        <p
          id="lead-detail-convert-error"
          className="lead-detail-actions-error"
          role="alert"
        >
          {errorMessage}
        </p>
      )}

      {!isConfirming && (
        <div
          id="lead-detail-convert-buttons"
          className="lead-detail-actions-buttons"
        >
          <Button
            id="lead-detail-convert-button"
            variant="filled"
            onClick={() => {
              setErrorMessage(null);
              setIsConfirming(true);
            }}
          >
            Convert lead
          </Button>
        </div>
      )}

      {/* The inline confirm — a short explainer, then Confirm / Cancel. */}
      {isConfirming && (
        <div id="lead-detail-convert-confirm" className="lead-detail-reject-form">
          <p
            id="lead-detail-convert-explainer"
            className="lead-detail-convert-explainer"
          >
            Converting creates a household, a contact, and an opportunity for each
            product line, then freezes this lead. This can't be undone.
          </p>
          <div
            id="lead-detail-convert-confirm-actions"
            className="lead-detail-reject-form-actions"
          >
            <Button
              id="lead-detail-convert-confirm-button"
              variant="filled"
              isPending={isConverting}
              onClick={runConvert}
            >
              Confirm conversion
            </Button>
            <Button
              id="lead-detail-convert-cancel-button"
              variant="text"
              disabled={isConverting}
              onClick={() => {
                setIsConfirming(false);
                setErrorMessage(null);
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}
