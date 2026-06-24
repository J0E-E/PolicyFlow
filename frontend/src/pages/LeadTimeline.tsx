import { useEffect, useRef, useState } from "react";
import StampTag from "../components/StampTag.tsx";
import { ApiError, getLeadTimeline } from "../api";
import type { TimelineRow } from "../api";
import LeadTimelineRow from "./LeadTimelineRow.tsx";
import LeadTimelineReactionRow from "./LeadTimelineReactionRow.tsx";

// The live-poll cadence while armed (P1.9 Epic 4). 1500 ms is inside the TDD's 1–2s
// band but tighter than the ~2s example, so the ~1s relay's narrow `processing` window
// is usually caught on a freshly created lead — the watchable moment.
const POLL_INTERVAL_MS = 1500;

interface LeadTimelineProperties {
  /** Required so every rendered element is uniquely targetable (CLAUDE.md). The
   *  overline, list, and the four state notes derive their ids from it. */
  id: string;
  /** The lead whose own domain events the console shows. */
  leadId: string;
  /** A re-arm key (the lead's `updated_at`). A successful qualify/reject bumps it via the
   *  page's in-place `setLead`, restarting the idle poll so the new event's reaction
   *  visibly advances (P1.9 Epic 4). A lead-id change / remount also arms. Optional so a
   *  bare `<LeadTimeline>` (a non-action context) still polls on mount. */
  reArmKey?: string;
  /** Fired when a poll `404`s — the lead read is gone for this session. The poll stops
   *  either way; the page decides what to do with it via the existing Epic 12
   *  `shouldShowExpiryGate`: a non-active (expired) session → the page-level
   *  `DemoSessionGate`; an active session (a genuine delete) → the page stays and this
   *  console falls back to its calm note (P1.9 Epic 4). */
  onSessionExpired?: () => void;
}

// A reaction is still in flight while `pending` or `processing`; `done`/`failed` are
// terminal (event rows are always terminal). The poll stays armed while any reaction is
// non-terminal and idle-stops once every reaction has settled (P1.9 Epic 4).
function hasPendingReaction(rows: TimelineRow[]): boolean {
  return rows.some(
    (row) =>
      row.kind === "reaction" &&
      (row.status === "pending" || row.status === "processing"),
  );
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
export default function LeadTimeline({
  id,
  leadId,
  reArmKey,
  onSessionExpired,
}: LeadTimelineProperties) {
  const [load, setLoad] = useState<TimelineLoadState>({ kind: "loading" });

  // Hold the expiry callback in a ref so the poll effect never re-runs (and never
  // re-arms) just because the page passed a fresh closure — only `leadId` / `reArmKey`
  // arm the loop. The poll reads the latest callback through the ref when a 404 lands.
  const onSessionExpiredRef = useRef(onSessionExpired);
  onSessionExpiredRef.current = onSessionExpired;

  // The armed live poll (P1.9 Epic 4). On mount (or lead-id change) the console fetches
  // once, then re-fetches every POLL_INTERVAL_MS while a reaction is still advancing.
  // Once every reaction is terminal it idle-stops — no wasted requests on a settled
  // timeline. A live qualify/reject restarts the loop (Phase 2 re-arm key).
  useEffect(() => {
    setLoad({ kind: "loading" });
    let isActive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = () => {
      getLeadTimeline(leadId)
        .then((rows) => {
          if (!isActive) {
            return;
          }
          setLoad({ kind: "loaded", rows });
          // Re-arm only while a reaction is still in flight; otherwise idle-stop.
          if (hasPendingReaction(rows)) {
            timer = setTimeout(poll, POLL_INTERVAL_MS);
          }
        })
        .catch((error: unknown) => {
          if (!isActive) {
            return;
          }
          // A `404` means the lead read is gone for this session (expired session, or a
          // genuine delete). Stop the poll — no re-arm — and hand the decision to the
          // page via `onSessionExpired`; the console itself falls back to its calm
          // empty note (an active-session delete keeps the page, this note is its rest
          // state). Any other failure stays the retryable error note.
          if (error instanceof ApiError && error.status === 404) {
            setLoad({ kind: "loaded", rows: [] });
            onSessionExpiredRef.current?.();
            return;
          }
          setLoad({ kind: "error" });
        });
    };

    poll();

    return () => {
      isActive = false;
      if (timer !== undefined) {
        clearTimeout(timer);
      }
    };
    // `reArmKey` (the lead's `updated_at`) restarts the loop after a qualify/reject so the
    // new event's reaction advances on screen; `leadId` re-arms on a lead change / remount.
  }, [leadId, reArmKey]);

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

  // Each row dispatches on its `kind`: an event row renders the neutral OCCURRED
  // headline, a reaction row renders an indented sibling with a bright status stamp.
  // The list key is composite — reactions share their parent's `event_id`, so the
  // key folds in `kind` and (for reactions) the `consumer_name` to stay unique.
  return (
    <ol id={`${id}-list`} className="lead-timeline-list">
      {load.rows.map((row) =>
        row.kind === "reaction" ? (
          <LeadTimelineReactionRow
            key={`reaction-${row.event_id}-${row.consumer_name}`}
            id={`${id}-reaction-${row.event_id}-${row.consumer_name}`}
            row={row}
          />
        ) : (
          <LeadTimelineRow
            key={`event-${row.event_id}`}
            id={`${id}-row-${row.event_id}`}
            row={row}
          />
        ),
      )}
    </ol>
  );
}
