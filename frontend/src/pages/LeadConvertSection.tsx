import { useNavigate } from "react-router-dom";
import Button from "../components/Button.tsx";
import type { MaskedLead } from "../api";

// The convert affordance on the lead detail page (P2.1 Epic 5, routed in Epic 6). It
// renders ONLY for a `Qualified` lead the caller both holds (`owner_user_id === the
// caller`) and may edit (`create_edit_records`), and never for a read-only shared seed
// row — the page decides whether to render it at all.
//
// Activating "Convert lead" navigates to the dedicated review-and-confirm screen at
// `/app/leads/:id/convert` (Epic 6), where the agent reviews the carried-over contact
// details, confirms or chooses the product lines, and commits. The page owns the
// `convertLead` call and the navigation back to the now-frozen lead — once converted,
// the `Qualified` gate no longer matches, so this section disappears and the frozen
// lead shows no mutating actions.

interface LeadConvertSectionProperties {
  /** The (Qualified, held) lead this affordance converts. */
  lead: MaskedLead;
}

export default function LeadConvertSection({
  lead,
}: LeadConvertSectionProperties) {
  const navigate = useNavigate();

  return (
    <section
      id="lead-detail-convert"
      className="lead-detail-actions"
      aria-label="Convert lead"
    >
      <h2 id="lead-detail-convert-title" className="lead-detail-actions-title">
        Convert
      </h2>
      <div
        id="lead-detail-convert-buttons"
        className="lead-detail-actions-buttons"
      >
        <Button
          id="lead-detail-convert-button"
          variant="filled"
          onClick={() => navigate(`/app/leads/${lead.id}/convert`)}
        >
          Convert lead
        </Button>
      </div>
    </section>
  );
}
