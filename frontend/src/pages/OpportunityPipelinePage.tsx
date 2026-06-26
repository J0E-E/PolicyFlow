import { useCallback, useEffect, useRef, useState } from "react";
import Button from "../components/Button.tsx";
import ExplainerPopover from "../components/ExplainerPopover.tsx";
import SimulatedBadge from "../components/SimulatedBadge.tsx";
import { medicareGateExplainer } from "../components/explainerContent.ts";
import { opportunityValuesSimulatedNotice } from "../components/simulatedNotice.ts";
import PipelineBoard from "./PipelineBoard.tsx";
import { useCapability } from "../session";
import { ApiError, changeOpportunityStage, getOpportunityBoard } from "../api";
import type { OpportunityBoard, OpportunityRow } from "../api";

// The authenticated pipeline board at `/app/opportunities` (P2.2). It renders
// INSIDE the AppShell chrome (masthead + left nav), so it carries its OWN Guide §5
// page header (a Besley "Opportunities" headline + the Oxford double rule).
//
// The page is thin: it owns the fetch + the stage-change state (one change in
// flight, the inline action error) and renders the header + `PipelineBoard`. The
// board / columns / cards / value fields are their own focused components
// (Frontend Philosophy). A holder of `create_edit_records` advances a card to its
// next enabled stage or marks it Lost; on success the board refetches.

/** What the board fetch is doing — each branch renders once. */
type BoardLoadState =
  | { kind: "loading" }
  | { kind: "loaded"; board: OpportunityBoard }
  | { kind: "error" };

// The page header — the Besley headline + Oxford rule, with the Medicare-gate
// explainer and the "simulated values" badge beside the title.
function OpportunitiesHeader() {
  return (
    <header id="opportunities-header" className="opportunities-header">
      <div id="opportunities-header-row" className="opportunities-header-row">
        <h1 id="opportunities-title" className="opportunities-title">
          Opportunities
        </h1>
        <ExplainerPopover
          id="opportunities-medicare-explainer"
          surfaceLabel="the Medicare eligibility gate"
          content={medicareGateExplainer}
        />
        <SimulatedBadge
          id="opportunities-values-simulated"
          surfaceLabel="the opportunity value fields"
          notice={opportunityValuesSimulatedNotice}
        />
      </div>
      <hr id="opportunities-rule" className="oxford-double-rule" />
    </header>
  );
}

export default function OpportunityPipelinePage() {
  const canAdvance = useCapability("create_edit_records");

  const [boardLoad, setBoardLoad] = useState<BoardLoadState>({
    kind: "loading",
  });
  // The id of the opportunity whose stage change (Advance or Mark Lost) is in
  // flight (its button spins), or null when none is pending. One at a time keeps
  // the refetch reconcile simple.
  const [changingId, setChangingId] = useState<string | null>(null);
  // A non-destructive action error: the board stays intact and the notice shows
  // above it. Cleared on the next attempt.
  const [advanceError, setAdvanceError] = useState<string | null>(null);
  // True while the page is mounted. Both the mount fetch and the post-advance
  // refetch read it before they `setState`, so a fetch in flight when the page
  // unmounts cannot update a gone component (mirrors LeadsListPage's cleanup ref).
  const isMountedRef = useRef(true);

  // Fetch the board; a resolve is ignored once the page has unmounted.
  const loadBoard = useCallback(() => {
    setBoardLoad({ kind: "loading" });
    getOpportunityBoard()
      .then((board) => {
        if (isMountedRef.current) {
          setBoardLoad({ kind: "loaded", board });
        }
      })
      .catch(() => {
        if (isMountedRef.current) {
          setBoardLoad({ kind: "error" });
        }
      });
  }, []);

  useEffect(() => {
    isMountedRef.current = true;
    loadBoard();
    return () => {
      isMountedRef.current = false;
    };
  }, [loadBoard]);

  // One handler for both Advance (to the next enabled stage) and Mark Lost (to the
  // terminal `Lost`); on success the board refetches so the card moves.
  const changeStage = async (opportunityId: string, targetStage: string) => {
    setAdvanceError(null);
    setChangingId(opportunityId);
    try {
      await changeOpportunityStage(opportunityId, targetStage);
      loadBoard();
    } catch (error) {
      // An ApiError carries the server's reason (e.g. the Medicare-gate 422), which
      // is more useful inline than a generic message; fall back for anything else.
      setAdvanceError(
        error instanceof ApiError
          ? error.message
          : "Could not change the opportunity's stage. Please try again.",
      );
    } finally {
      setChangingId(null);
    }
  };

  const handleAdvance = (opportunity: OpportunityRow) => {
    if (opportunity.next_stage !== null) {
      changeStage(opportunity.id, opportunity.next_stage);
    }
  };
  const handleMarkLost = (opportunity: OpportunityRow) =>
    changeStage(opportunity.id, "Lost");

  if (boardLoad.kind === "loading") {
    return (
      <div id="opportunities-page" className="opportunities-page">
        <OpportunitiesHeader />
        <p id="opportunities-loading" className="opportunities-status">
          Loading opportunities…
        </p>
      </div>
    );
  }

  if (boardLoad.kind === "error") {
    return (
      <div id="opportunities-page" className="opportunities-page">
        <OpportunitiesHeader />
        <div id="opportunities-error" className="opportunities-error">
          <p id="opportunities-error-message" className="opportunities-status">
            Could not load opportunities.
          </p>
          <Button
            id="opportunities-retry"
            variant="outlined"
            onClick={() => loadBoard()}
          >
            Try again
          </Button>
        </div>
      </div>
    );
  }

  const { board } = boardLoad;

  return (
    <div id="opportunities-page" className="opportunities-page">
      <OpportunitiesHeader />

      {advanceError && (
        <p
          id="opportunities-advance-error"
          className="opportunities-advance-error"
          role="alert"
        >
          {advanceError}
        </p>
      )}

      {board.opportunities.length === 0 ? (
        <div id="opportunities-empty" className="opportunities-empty">
          <p
            id="opportunities-empty-message"
            className="opportunities-empty-message"
          >
            No opportunities yet. Convert a qualified lead to open one.
          </p>
        </div>
      ) : (
        <PipelineBoard
          board={board}
          canAdvance={canAdvance}
          changingId={changingId}
          onAdvance={handleAdvance}
          onMarkLost={handleMarkLost}
        />
      )}
    </div>
  );
}
