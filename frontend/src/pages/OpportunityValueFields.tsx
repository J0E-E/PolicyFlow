interface OpportunityValueFieldsProperties {
  /** Required so every rendered element is uniquely targetable (CLAUDE.md). */
  id: string;
  /** The estimated annual premium as a decimal string, or `null`. */
  premium: string | null;
  /** The target close date as an ISO date string, or `null`. */
  closeDate: string | null;
}

// The em-dash shown for a value field that has no value yet. P2.2 leaves both
// fields null at conversion (a quote populates them in P2.3 — D7 / Risk R2), so
// the board renders an em-dash rather than an empty gap.
const EM_DASH = "—";

// The opportunity card's value fields (estimated annual premium + target close
// date), rendered as a small definition list. A focused leaf component (Frontend
// Philosophy) so the card stays readable and the em-dash rule lives in one place.
export default function OpportunityValueFields({
  id,
  premium,
  closeDate,
}: OpportunityValueFieldsProperties) {
  return (
    <dl id={id} className="opportunity-value-fields">
      <div id={`${id}-premium`} className="opportunity-value-field">
        <dt id={`${id}-premium-label`} className="opportunity-value-label">
          Est. annual premium
        </dt>
        <dd id={`${id}-premium-value`} className="opportunity-value-amount">
          {premium !== null ? `$${premium}` : EM_DASH}
        </dd>
      </div>
      <div id={`${id}-close-date`} className="opportunity-value-field">
        <dt id={`${id}-close-date-label`} className="opportunity-value-label">
          Target close
        </dt>
        <dd id={`${id}-close-date-value`} className="opportunity-value-amount">
          {closeDate !== null ? closeDate : EM_DASH}
        </dd>
      </div>
    </dl>
  );
}
