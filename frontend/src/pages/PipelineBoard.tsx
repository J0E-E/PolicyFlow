import PipelineColumn from "./PipelineColumn.tsx";
import type { OpportunityBoard, OpportunityRow } from "../api";

interface PipelineBoardProperties {
  /** The board payload — the tenant's pipeline columns + the opportunity rows. */
  board: OpportunityBoard;
  /** Whether the caller may change stages (holds `create_edit_records`). */
  canAdvance: boolean;
  /** The id of the opportunity whose stage change is in flight, or `null`. */
  changingId: string | null;
  onAdvance: (opportunity: OpportunityRow) => void;
  onMarkLost: (opportunity: OpportunityRow) => void;
}

// The stage-grouped board: one column per the tenant's enabled stage (under its
// label), plus a Lost lane for the off-spine `Lost` cards (shown only when there
// are any). Groups the opportunity rows into their columns by `stage` and threads
// the per-card handlers down. Pure presentation — the page owns the state.
export default function PipelineBoard({
  board,
  canAdvance,
  changingId,
  onAdvance,
  onMarkLost,
}: PipelineBoardProperties) {
  const { pipeline, opportunities } = board;
  const labelForStage = (stageKey: string): string =>
    pipeline.stages.find((stage) => stage.key === stageKey)?.label ?? stageKey;
  const lostOpportunities = opportunities.filter(
    (opportunity) => opportunity.stage === "Lost",
  );

  return (
    <div id="opportunities-board" className="opportunities-board">
      {pipeline.stages.map((stage) => (
        <PipelineColumn
          key={stage.key}
          id={`pipeline-column-${stage.key}`}
          label={stage.label}
          cards={opportunities.filter(
            (opportunity) => opportunity.stage === stage.key,
          )}
          canAdvance={canAdvance}
          changingId={changingId}
          onAdvance={onAdvance}
          onMarkLost={onMarkLost}
          labelForStage={labelForStage}
        />
      ))}

      {lostOpportunities.length > 0 && (
        <PipelineColumn
          id="pipeline-column-lost"
          label="Lost"
          cards={lostOpportunities}
          canAdvance={canAdvance}
          changingId={changingId}
          onAdvance={onAdvance}
          onMarkLost={onMarkLost}
          labelForStage={labelForStage}
          headingClassName="pipeline-column-lost-heading"
        />
      )}
    </div>
  );
}
