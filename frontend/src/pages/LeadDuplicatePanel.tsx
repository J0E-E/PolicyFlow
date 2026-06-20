import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { WarningTriangle } from "iconoir-react";
import Button from "../components/Button.tsx";
import StampTag from "../components/StampTag.tsx";
import { leadStatusStamp } from "../components/leadStatusStamp.ts";
import { getLead, resolveDuplicate } from "../api";
import type { MaskedLead, ResolveDuplicateAction } from "../api";
import { isUnresolvedDuplicate } from "./leadsListPresentation.ts";
import { leadDate } from "./leadDetailPresentation.ts";

// The "Possible duplicate" panel at the top of the lead detail page (Epic 21).
// It renders whenever the lead points at a matched prior lead
// (`duplicate_of_lead_id` set) — both while unresolved AND after a `link`
// resolution (a `new` resolution clears the pointer, so the panel vanishes; a
// `reject` keeps the pointer but the lead is now terminal `Rejected`).
//
// The panel fetches the matched lead via `getLead(duplicate_of_lead_id)` — its own
// small loading / error — and shows its name + status stamp + created date + a View
// link to that lead's detail page. When the flag is still UNRESOLVED and the viewer
// holds `create_edit_records`, three resolve controls appear:
//   - Link — confirm the same person (records the linkage, keeps the pointer)
//   - Keep as new — clear the flag (this is a different person)
//   - Reject — discard this lead as a duplicate (a `New` lead only; → Rejected)
// On success `onLeadChange` lifts the updated lead to the page so the panel and the
// status stamp re-derive. Resolved flags read as a light note instead of controls.

/** What the matched-lead fetch is doing — its own small lifecycle. */
type MatchLoadState =
  | { kind: "loading" }
  | { kind: "loaded"; match: MaskedLead }
  | { kind: "error" };

/** Which resolve action is mid-flight (so its button spins), or none. */
type PendingResolve = ResolveDuplicateAction | null;

interface LeadDuplicatePanelProperties {
  /** The flagged lead (its `duplicate_of_lead_id` is non-null). */
  lead: MaskedLead;
  /** Whether the viewer may resolve the flag (`create_edit_records`). */
  canEdit: boolean;
  /** Lift the updated masked lead to the page after a resolve. */
  onLeadChange: (lead: MaskedLead) => void;
}

export default function LeadDuplicatePanel({
  lead,
  canEdit,
  onLeadChange,
}: LeadDuplicatePanelProperties) {
  const matchId = lead.duplicate_of_lead_id;
  const [matchLoad, setMatchLoad] = useState<MatchLoadState>({ kind: "loading" });
  const [pendingResolve, setPendingResolve] = useState<PendingResolve>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const isUnresolved = isUnresolvedDuplicate(lead);
  // The flag can only be rejected from a `New` lead (the backend guard); a flagged
  // `Working` lead is rejected through the ordinary Reject action instead.
  const canRejectDuplicate = isUnresolved && lead.status === "New";

  // Fetch the matched prior lead so the panel can name it + link to it.
  const loadMatch = useCallback(() => {
    if (matchId === null) {
      return;
    }
    setMatchLoad({ kind: "loading" });
    let isActive = true;
    getLead(matchId)
      .then((match) => {
        if (isActive) {
          setMatchLoad({ kind: "loaded", match });
        }
      })
      .catch(() => {
        if (isActive) {
          setMatchLoad({ kind: "error" });
        }
      });
    return () => {
      isActive = false;
    };
  }, [matchId]);

  useEffect(() => loadMatch(), [loadMatch]);

  const runResolve = (action: ResolveDuplicateAction) => {
    setErrorMessage(null);
    setPendingResolve(action);
    resolveDuplicate(lead.id, { action })
      .then((updated) => onLeadChange(updated))
      .catch(() => {
        setErrorMessage(
          "We couldn't resolve this duplicate. Please try again.",
        );
      })
      .finally(() => setPendingResolve(null));
  };

  return (
    <section
      id="lead-detail-duplicate-panel"
      className="lead-detail-duplicate-panel"
      aria-label="Possible duplicate"
    >
      <div
        id="lead-detail-duplicate-header"
        className="lead-detail-duplicate-header"
      >
        <span
          id="lead-detail-duplicate-icon"
          className="lead-detail-duplicate-icon"
          aria-hidden="true"
        >
          <WarningTriangle width={18} height={18} />
        </span>
        <h2
          id="lead-detail-duplicate-title"
          className="lead-detail-duplicate-title"
        >
          Possible duplicate
        </h2>
      </div>

      <p
        id="lead-detail-duplicate-message"
        className="lead-detail-duplicate-message"
      >
        {isUnresolved
          ? "This lead's email or phone matches an earlier lead. Review the match, then resolve."
          : "This lead was linked to an earlier matching lead."}
      </p>

      {/* The matched lead — its own small loading / error / loaded. */}
      <DuplicateMatch matchLoad={matchLoad} onRetry={loadMatch} />

      {/* Resolve controls — only while unresolved and only for a permitted user. */}
      {isUnresolved && canEdit && (
        <div
          id="lead-detail-duplicate-actions"
          className="lead-detail-duplicate-actions"
        >
          {errorMessage !== null && (
            <p
              id="lead-detail-duplicate-error"
              className="lead-detail-duplicate-error"
              role="alert"
            >
              {errorMessage}
            </p>
          )}
          <div
            id="lead-detail-duplicate-buttons"
            className="lead-detail-duplicate-buttons"
          >
            <Button
              id="lead-detail-duplicate-link-button"
              variant="tonal"
              isPending={pendingResolve === "link"}
              onClick={() => runResolve("link")}
            >
              Link to match
            </Button>
            <Button
              id="lead-detail-duplicate-new-button"
              variant="tonal"
              isPending={pendingResolve === "new"}
              onClick={() => runResolve("new")}
            >
              Keep as new
            </Button>
            {canRejectDuplicate && (
              <Button
                id="lead-detail-duplicate-reject-button"
                variant="outlined"
                isPending={pendingResolve === "reject"}
                onClick={() => runResolve("reject")}
              >
                Reject as duplicate
              </Button>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

// The matched prior lead — its name, status stamp, created date, and a View link
// to its own detail page.
function DuplicateMatch({
  matchLoad,
  onRetry,
}: {
  matchLoad: MatchLoadState;
  onRetry: () => void;
}) {
  if (matchLoad.kind === "loading") {
    return (
      <p
        id="lead-detail-duplicate-match-loading"
        className="lead-detail-duplicate-match-status"
        role="status"
        aria-live="polite"
      >
        Loading the matched lead…
      </p>
    );
  }

  if (matchLoad.kind === "error") {
    return (
      <div
        id="lead-detail-duplicate-match-error"
        className="lead-detail-duplicate-match-error"
      >
        <p
          id="lead-detail-duplicate-match-error-message"
          className="lead-detail-duplicate-match-status"
          role="status"
          aria-live="polite"
        >
          We couldn't load the matched lead.
        </p>
        <Button
          id="lead-detail-duplicate-match-retry-button"
          variant="text"
          onClick={onRetry}
        >
          Try again
        </Button>
      </div>
    );
  }

  const { match } = matchLoad;
  const statusStamp = leadStatusStamp(match.status);

  return (
    <div id="lead-detail-duplicate-match" className="lead-detail-duplicate-match">
      <span
        id="lead-detail-duplicate-match-name"
        className="lead-detail-duplicate-match-name"
      >
        {match.first_name} {match.last_name}
      </span>
      <StampTag
        id="lead-detail-duplicate-match-status"
        status={statusStamp.status}
      >
        {statusStamp.label}
      </StampTag>
      <span
        id="lead-detail-duplicate-match-created"
        className="lead-detail-duplicate-match-created"
      >
        Created {leadDate(match.created_at)}
      </span>
      <Link
        id="lead-detail-duplicate-match-view"
        className="text-link"
        to={`/app/leads/${match.id}`}
      >
        View
      </Link>
    </div>
  );
}
