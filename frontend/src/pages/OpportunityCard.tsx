import Button from "../components/Button.tsx";
import Card from "../components/Card.tsx";
import StampTag from "../components/StampTag.tsx";
import OpportunityValueFields from "./OpportunityValueFields.tsx";
import type { OpportunityRow } from "../api";

interface OpportunityCardProperties {
  /** The opportunity to render. */
  opportunity: OpportunityRow;
  /** Whether the caller may change stages (holds `create_edit_records`). */
  canAdvance: boolean;
  /** Whether a stage change for this card is in flight (its buttons spin). */
  isChanging: boolean;
  /** Advance this opportunity to its next enabled stage. */
  onAdvance: (opportunity: OpportunityRow) => void;
  /** Mark this opportunity Lost. */
  onMarkLost: (opportunity: OpportunityRow) => void;
  /** Map a canonical stage key to the tenant's display label (Advance target). */
  labelForStage: (stageKey: string) => string;
}

const EM_DASH = "—";

// One opportunity card: the contact name (heading), product-line label, value
// fields, owner, a Medicare-eligibility marker, and the Advance / Mark Lost
// actions. A focused component (Frontend Philosophy) the board's columns render;
// every element gets a unique id derived from the opportunity id.
export default function OpportunityCard({
  opportunity,
  canAdvance,
  isChanging,
  onAdvance,
  onMarkLost,
  labelForStage,
}: OpportunityCardProperties) {
  const id = `opportunity-card-${opportunity.id}`;
  const nextStage = opportunity.next_stage;
  const isTerminal = nextStage === null && !opportunity.can_mark_lost;

  const firstName = opportunity.contact_first_name ?? "";
  const lastName = opportunity.contact_last_name ?? "";
  const contactName = `${firstName} ${lastName}`.trim() || EM_DASH;

  const footer = isTerminal ? (
    <p id={`${id}-terminal`} className="opportunity-card-terminal">
      No further stage
    </p>
  ) : canAdvance ? (
    <div id={`${id}-actions`} className="opportunity-card-actions">
      {nextStage !== null && (
        <Button
          id={`opportunity-advance-${opportunity.id}`}
          variant="filled"
          isPending={isChanging}
          onClick={() => onAdvance(opportunity)}
        >
          {`Advance to ${labelForStage(nextStage)}`}
        </Button>
      )}
      {opportunity.can_mark_lost && (
        <Button
          id={`opportunity-mark-lost-${opportunity.id}`}
          variant="outlined"
          isPending={isChanging}
          onClick={() => onMarkLost(opportunity)}
        >
          Mark Lost
        </Button>
      )}
    </div>
  ) : undefined;

  return (
    <Card id={id} title={contactName} headingLevel={3} footer={footer}>
      <p id={`${id}-product-line`} className="opportunity-card-product-line">
        {opportunity.product_line_label}
      </p>
      <OpportunityValueFields
        id={`${id}-values`}
        premium={opportunity.estimated_annual_premium}
        closeDate={opportunity.target_close_date}
      />
      <p id={`${id}-owner`} className="opportunity-card-owner">
        {`Owner: ${opportunity.owner_username ?? EM_DASH}`}
      </p>
      {opportunity.eligibility.medicare_gated && (
        <div
          id={`${id}-eligibility-row`}
          className="opportunity-card-eligibility"
        >
          <StampTag
            id={`${id}-eligibility`}
            status={opportunity.eligibility.age_eligible ? "success" : "warning"}
          >
            {opportunity.eligibility.age_eligible
              ? "Medicare · 65+ eligible"
              : "Medicare · 65+ required"}
          </StampTag>
        </div>
      )}
    </Card>
  );
}
