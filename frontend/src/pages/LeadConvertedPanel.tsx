import { useEffect, useState } from "react";
import Card from "../components/Card.tsx";
import StampTag from "../components/StampTag.tsx";
import { getConversion } from "../api";
import type { ConversionSummary, ProductLine } from "../api";

// The "Converted to" panel on a frozen (Converted) lead detail (P2.1 Epic 7). It
// proves the conversion produced a real customer without building detail pages: the
// new contact's name, its household's name, and the opportunities opened (each by its
// product-line label + stage). It does its own single fetch of
// `GET /api/leads/{id}/conversion` on mount — the page renders it only for a
// `Converted` lead, so the read is always for a converted lead (the endpoint 409s a
// non-converted one). The product-line key is mapped to its human label via the
// tenant's registry; an unknown key falls back to the raw key.

type LoadState =
  | { kind: "loading" }
  | { kind: "loaded"; summary: ConversionSummary }
  | { kind: "error" };

interface LeadConvertedPanelProperties {
  /** The converted lead whose summary to show. */
  leadId: string;
  /** The tenant's product lines, for mapping an opportunity's key to its label. */
  productLines: ProductLine[];
}

export default function LeadConvertedPanel({
  leadId,
  productLines,
}: LeadConvertedPanelProperties) {
  const [loadState, setLoadState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    let isActive = true;
    getConversion(leadId)
      .then((summary) => {
        if (isActive) {
          setLoadState({ kind: "loaded", summary });
        }
      })
      .catch(() => {
        if (isActive) {
          setLoadState({ kind: "error" });
        }
      });
    return () => {
      isActive = false;
    };
  }, [leadId]);

  const labelForProductLine = (key: string) =>
    productLines.find((productLine) => productLine.key === key)?.label ?? key;

  return (
    <Card id="lead-converted-panel" title="Converted to">
      {loadState.kind === "loading" && (
        <p
          id="lead-converted-loading"
          className="lead-converted-status"
          role="status"
          aria-live="polite"
        >
          Loading…
        </p>
      )}

      {loadState.kind === "error" && (
        <p id="lead-converted-error" className="lead-converted-status" role="status">
          We couldn't load the conversion summary.
        </p>
      )}

      {loadState.kind === "loaded" && (
        <div id="lead-converted-summary" className="lead-converted-summary">
          <dl id="lead-converted-entities" className="lead-converted-entities">
            <div className="lead-converted-row">
              <dt id="lead-converted-contact-label">Contact</dt>
              <dd id="lead-converted-contact-name">
                {loadState.summary.contact.first_name}{" "}
                {loadState.summary.contact.last_name}
              </dd>
            </div>
            <div className="lead-converted-row">
              <dt id="lead-converted-household-label">Household</dt>
              <dd id="lead-converted-household-name">
                {loadState.summary.household.name}
              </dd>
            </div>
          </dl>

          <h3
            id="lead-converted-opportunities-title"
            className="lead-converted-opportunities-title"
          >
            Opportunities
          </h3>
          <ul
            id="lead-converted-opportunities"
            className="lead-converted-opportunities"
          >
            {loadState.summary.opportunities.map((opportunity) => (
              <li
                id={`lead-converted-opportunity-${opportunity.id}`}
                key={opportunity.id}
                className="lead-converted-opportunity"
              >
                <span
                  id={`lead-converted-opportunity-${opportunity.id}-line`}
                  className="lead-converted-opportunity-line"
                >
                  {labelForProductLine(opportunity.product_line)}
                </span>
                <StampTag
                  id={`lead-converted-opportunity-${opportunity.id}-stage`}
                  status="neutral"
                >
                  {opportunity.stage}
                </StampTag>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}
