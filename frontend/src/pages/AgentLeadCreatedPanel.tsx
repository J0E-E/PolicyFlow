import { Link } from "react-router-dom";
import Button from "../components/Button.tsx";
import StampTag from "../components/StampTag.tsx";
import type { MaskedLead, ProductLine } from "../api";

interface AgentLeadCreatedPanelProperties {
  /** The masked lead the agent just created (the `createLead` result). */
  lead: MaskedLead;
  /** The tenant's product lines — maps the lead's selected keys to their labels. */
  productLines: ProductLine[];
  /** Start a fresh blank intake (resets the form on the page). */
  onCreateAnother: () => void;
}

// The inline created-lead confirmation that replaces the form on a successful
// agent submit (Epic 19 — "lands the agent on the new lead", interim until the
// Epic 21 detail page exists). Shows the created MASKED lead: the agent only
// ever sees the masked shape the server returns (email/phone arrive pre-masked),
// so nothing here unmasks anything. A `Working` stamp + "owned by you" reflect
// that an agent-entered lead is born Working and assigned to the entering agent.
// Styling lives in styles/agent-intake.css. Epic 21 later adds an "Open lead
// detail" link onto this panel.
export default function AgentLeadCreatedPanel({
  lead,
  productLines,
  onCreateAnother,
}: AgentLeadCreatedPanelProperties) {
  // Map each selected product-line key to its human label via the tenant
  // registry; an unknown key (registry drift) falls back to the raw key so the
  // agent still sees something rather than a blank.
  const labelForKey = new Map(
    productLines.map((productLine) => [productLine.key, productLine.label]),
  );
  const productLineLabels = lead.product_lines_of_interest.map(
    (key) => labelForKey.get(key) ?? key,
  );

  return (
    <div
      id="agent-intake-created"
      className="agent-intake-created"
      role="status"
      aria-live="polite"
    >
      <div
        id="agent-intake-created-header"
        className="agent-intake-created-header"
      >
        <h2
          id="agent-intake-created-title"
          className="agent-intake-created-title"
        >
          Lead created
        </h2>
        <StampTag id="agent-intake-created-status" status="pending">
          Working
        </StampTag>
      </div>

      <p
        id="agent-intake-created-name"
        className="agent-intake-created-name"
      >
        {lead.first_name} {lead.last_name}
      </p>
      <p
        id="agent-intake-created-ownership"
        className="agent-intake-created-ownership"
      >
        Owned by you
      </p>

      <dl id="agent-intake-created-details" className="agent-intake-created-details">
        <div
          id="agent-intake-created-email-row"
          className="agent-intake-created-row"
        >
          <dt
            id="agent-intake-created-email-label"
            className="agent-intake-created-label"
          >
            Email
          </dt>
          <dd
            id="agent-intake-created-email-value"
            className="agent-intake-created-value"
          >
            {lead.email}
          </dd>
        </div>
        <div
          id="agent-intake-created-phone-row"
          className="agent-intake-created-row"
        >
          <dt
            id="agent-intake-created-phone-label"
            className="agent-intake-created-label"
          >
            Phone
          </dt>
          <dd
            id="agent-intake-created-phone-value"
            className="agent-intake-created-value"
          >
            {lead.phone}
          </dd>
        </div>
        <div
          id="agent-intake-created-age-band-row"
          className="agent-intake-created-row"
        >
          <dt
            id="agent-intake-created-age-band-label"
            className="agent-intake-created-label"
          >
            Age band
          </dt>
          <dd
            id="agent-intake-created-age-band-value"
            className="agent-intake-created-value"
          >
            {lead.age_band}
          </dd>
        </div>
        <div
          id="agent-intake-created-zip-code-row"
          className="agent-intake-created-row"
        >
          <dt
            id="agent-intake-created-zip-code-label"
            className="agent-intake-created-label"
          >
            ZIP code
          </dt>
          <dd
            id="agent-intake-created-zip-code-value"
            className="agent-intake-created-value"
          >
            {lead.zip_code}
          </dd>
        </div>
        <div
          id="agent-intake-created-product-lines-row"
          className="agent-intake-created-row"
        >
          <dt
            id="agent-intake-created-product-lines-label"
            className="agent-intake-created-label"
          >
            Coverage interests
          </dt>
          <dd
            id="agent-intake-created-product-lines-value"
            className="agent-intake-created-value"
          >
            {productLineLabels.join(", ")}
          </dd>
        </div>
      </dl>

      <div
        id="agent-intake-created-actions"
        className="agent-intake-created-actions"
      >
        <Button
          id="agent-intake-created-create-another"
          variant="filled"
          onClick={onCreateAnother}
        >
          Create another lead
        </Button>
        <Link
          id="agent-intake-created-home-link"
          className="text-link"
          to="/app"
        >
          Back to demo home
        </Link>
      </div>
    </div>
  );
}
