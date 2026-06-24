import StampTag from "../components/StampTag.tsx";
import type { TimelineRow } from "../api";
import {
  leadEventAbsoluteUtc,
  leadEventRelativeTime,
} from "./leadDetailPresentation.ts";

interface LeadTimelineRowProperties {
  /** Required so every rendered element is uniquely targetable (CLAUDE.md). The
   *  tick / name / id / time / stamp ids all derive from it. */
  id: string;
  /** One domain-event row from the timeline read. */
  row: TimelineRow;
}

// One event row in the lead timeline ink console (P1.9 Epic 1, Guide §6.1). A single
// tick marker on the vertical hairline, the raw dotted event name in Public Sans, the
// `event_id` in mono `--on-ink-variant`, a full-words relative time (absolute UTC on
// hover via the `title`), and a NEUTRAL "OCCURRED" stamp — a domain event is a fact,
// not a state signal (Guide §2.2 "information is not a signal"), so the stamp is the
// on-ink-variant neutral tone, never a state bright. Reaction sibling rows + their
// `└─` connectors are a later epic; this renders the event row only.
export default function LeadTimelineRow({ id, row }: LeadTimelineRowProperties) {
  return (
    <li id={id} className="lead-timeline-row">
      <span
        id={`${id}-tick`}
        className="lead-timeline-tick"
        aria-hidden="true"
      />
      <div id={`${id}-body`} className="lead-timeline-row-body">
        <div id={`${id}-headline`} className="lead-timeline-row-headline">
          <span id={`${id}-event-type`} className="lead-timeline-event-type">
            {row.event_type}
          </span>
          <StampTag id={`${id}-status`} status="neutral">
            Occurred
          </StampTag>
        </div>
        <div id={`${id}-meta`} className="lead-timeline-row-meta">
          <time
            id={`${id}-time`}
            className="lead-timeline-time"
            dateTime={row.occurred_at}
            title={leadEventAbsoluteUtc(row.occurred_at)}
          >
            {leadEventRelativeTime(row.occurred_at)}
          </time>
          <span id={`${id}-event-id`} className="lead-timeline-event-id">
            {row.event_id}
          </span>
        </div>
      </div>
    </li>
  );
}
