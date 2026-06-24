import StampTag from "../components/StampTag.tsx";
import type { TimelineReactionRow } from "../api";
import { reactionStatusStamp } from "./leadDetailPresentation.ts";

interface LeadTimelineReactionRowProperties {
  /** Required so every rendered element is uniquely targetable (CLAUDE.md). The
   *  connector / consumer name / stamp ids all derive from it. */
  id: string;
  /** One reaction sibling row from the timeline read. */
  row: TimelineReactionRow;
}

// One reaction sibling row in the lead timeline ink console (P1.9 Epic 2, Guide §6.1).
// A sidecar reaction indents under its parent event, joined by a mono `└─` box-drawing
// connector (aria-hidden — decoration, the consumer name carries the meaning). The
// consumer name renders in mono — a system actor / trace token, deliberately distinct
// from the event's Public Sans name, reinforcing the parent/child split beyond the
// connector. A bright on-ink status stamp (vs. the event's neutral OCCURRED) carries the
// derived status; the `processing` stamp adds the inline spinner (reusing `.button-spinner`,
// frozen under reduced motion by base.css). When the reaction carries a `result_summary`
// (the enrichment quality score — sync.logger's is always null), it renders as an indented
// mono sub-line under the consumer name (`--on-ink-variant`, Guide §6.1 trace style); a null
// summary omits the line entirely — the status stamp already disambiguates the state (P1.9
// Epic 3).
export default function LeadTimelineReactionRow({
  id,
  row,
}: LeadTimelineReactionRowProperties) {
  const stamp = reactionStatusStamp(row.status);

  return (
    <li id={id} className="lead-timeline-reaction-row">
      <span
        id={`${id}-connector`}
        className="lead-timeline-reaction-connector"
        aria-hidden="true"
      >
        └─
      </span>
      <span
        id={`${id}-consumer-name`}
        className="lead-timeline-reaction-consumer"
      >
        {row.consumer_name}
      </span>
      <StampTag
        id={`${id}-status`}
        status={stamp.status}
        icon={
          stamp.isProcessing ? (
            <span
              id={`${id}-status-spinner`}
              className="button-spinner"
              aria-hidden="true"
            />
          ) : undefined
        }
      >
        {stamp.label}
      </StampTag>
      {row.result_summary !== null && (
        <span
          id={`${id}-summary`}
          className="lead-timeline-reaction-summary"
        >
          {row.result_summary}
        </span>
      )}
    </li>
  );
}
