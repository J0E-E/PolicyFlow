import OpportunityCard from "./OpportunityCard.tsx";
import type { OpportunityRow } from "../api";

interface PipelineColumnProperties {
  /** The column's element id (e.g. `pipeline-column-New` / `pipeline-column-lost`). */
  id: string;
  /** The column heading — the tenant's stage label (or "Lost"). */
  label: string;
  /** The opportunities grouped into this column. */
  cards: OpportunityRow[];
  /** Whether the caller may change stages (holds `create_edit_records`). */
  canAdvance: boolean;
  /** The id of the opportunity whose stage change is in flight, or `null`. */
  changingId: string | null;
  onAdvance: (opportunity: OpportunityRow) => void;
  onMarkLost: (opportunity: OpportunityRow) => void;
  /** Map a canonical stage key to the tenant's display label. */
  labelForStage: (stageKey: string) => string;
  /** Optional extra class on the heading (the Lost lane's muted heading). */
  headingClassName?: string;
}

// One board column: a heading plus the cards grouped under it (or an empty
// marker). Reused for both the enabled stage columns and the off-spine Lost lane.
export default function PipelineColumn({
  id,
  label,
  cards,
  canAdvance,
  changingId,
  onAdvance,
  onMarkLost,
  labelForStage,
  headingClassName,
}: PipelineColumnProperties) {
  const headingClasses = headingClassName
    ? `pipeline-column-heading ${headingClassName}`
    : "pipeline-column-heading";
  return (
    <section
      id={id}
      className="pipeline-column"
      aria-labelledby={`${id}-heading`}
    >
      <h2 id={`${id}-heading`} className={headingClasses}>
        {label}
      </h2>
      <div id={`${id}-cards`} className="pipeline-column-cards">
        {cards.length === 0 ? (
          <p id={`${id}-empty`} className="pipeline-column-empty">
            No opportunities
          </p>
        ) : (
          cards.map((opportunity) => (
            <OpportunityCard
              key={opportunity.id}
              opportunity={opportunity}
              canAdvance={canAdvance}
              isChanging={changingId === opportunity.id}
              onAdvance={onAdvance}
              onMarkLost={onMarkLost}
              labelForStage={labelForStage}
            />
          ))
        )}
      </div>
    </section>
  );
}
