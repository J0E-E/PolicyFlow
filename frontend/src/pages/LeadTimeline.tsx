import { useEffect, useState } from "react";
import StampTag from "../components/StampTag.tsx";
import { getLeadTimeline } from "../api";
import type { TimelineRow } from "../api";
import LeadTimelineRow from "./LeadTimelineRow.tsx";

interface LeadTimelineProperties {
  /** Required so every rendered element is uniquely targetable (CLAUDE.md). The
   *  overline, list, and the four state notes derive their ids from it. */
  id: string;
  /** The lead whose own domain events the console shows. */
  leadId: string;
}

// What the single timeline fetch is doing. Each state renders once inside the always-
// present console (the empty case is `loaded` with no rows — never a hidden console).
type TimelineLoadState =
  | { kind: "loading" }
  | { kind: "loaded"; rows: TimelineRow[] }
  | { kind: "error" };

// The per-lead EVENT TIMELINE ink console (P1.9 Epic 1, the tracer slice; Guide §6.1).
// An inverted `--surface-ink` card titled with a stamp overline ("EVENT TIMELINE"),
// carrying the lead's own domain events oldest-first as rows on a vertical hairline
// with per-row tick markers (LeadTimelineRow owns one row). It sits at the very bottom
// of the lead detail page, after the actions section.
//
// One fetch on open (no polling yet — that is Epic 4). The console ALWAYS renders: a
// calm on-ink note covers loading, error, and the empty timeline (a lead with no events
// yet — seed leads are empty until Epic 5 seeds their trails). Reaction sibling rows,
// the Simulated badge, and live slide-in arrive in later epics onto this same console.
//
// Tokens only, AA on ink (Guide §7); the ink-console treatment lives in
// styles/lead-timeline.css, mirroring the ArchitectureConsole / how-its-built.css
// pattern — the Guide wins all conflicts (no new aesthetic).
export default function LeadTimeline({ id, leadId }: LeadTimelineProperties) {
  const [load, setLoad] = useState<TimelineLoadState>({ kind: "loading" });

  // Single fetch on open: load the lead's events once when the console mounts (or the
  // lead id changes). No polling — live updates are Epic 4.
  useEffect(() => {
    setLoad({ kind: "loading" });
    let isActive = true;
    getLeadTimeline(leadId)
      .then((rows) => {
        if (isActive) {
          setLoad({ kind: "loaded", rows });
        }
      })
      .catch(() => {
        if (isActive) {
          setLoad({ kind: "error" });
        }
      });
    return () => {
      isActive = false;
    };
  }, [leadId]);

  return (
    <section
      id={id}
      className="lead-timeline-console"
      aria-labelledby={`${id}-overline`}
    >
      <StampTag id={`${id}-overline`} variant="overline">
        Event timeline
      </StampTag>
      <LeadTimelineBody id={id} load={load} />
    </section>
  );
}

// The console body — one of the four states. Loading / error / empty render a calm
// on-ink note; loaded-with-rows renders the hairline list of event rows.
function LeadTimelineBody({
  id,
  load,
}: {
  id: string;
  load: TimelineLoadState;
}) {
  if (load.kind === "loading") {
    return (
      <p
        id={`${id}-loading`}
        className="lead-timeline-note"
        role="status"
        aria-live="polite"
      >
        Loading events…
      </p>
    );
  }

  if (load.kind === "error") {
    return (
      <p id={`${id}-error`} className="lead-timeline-note" role="status">
        We couldn't load this lead's events.
      </p>
    );
  }

  if (load.rows.length === 0) {
    return (
      <p id={`${id}-empty`} className="lead-timeline-note">
        No events recorded for this lead yet.
      </p>
    );
  }

  return (
    <ol id={`${id}-list`} className="lead-timeline-list">
      {load.rows.map((row) => (
        <LeadTimelineRow
          key={row.event_id}
          id={`${id}-row-${row.event_id}`}
          row={row}
        />
      ))}
    </ol>
  );
}
