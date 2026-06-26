import { useCallback, useEffect, useRef, useState } from "react";
import Button from "../components/Button.tsx";
import Card from "../components/Card.tsx";
import StampTag from "../components/StampTag.tsx";
import { useCapability } from "../session";
import { changeOpportunityStage, listOpportunities } from "../api";
import type { OpportunityRow } from "../api";

// The authenticated pipeline board at `/app/opportunities` (P2.2 Epic 2 tracer).
// It renders INSIDE the AppShell chrome (masthead + left nav), so it carries its
// OWN Guide §5 page header (a Besley "Opportunities" headline + the Oxford double
// rule), mirroring the leads list.
//
// This is the thinnest demoable thread: it lists the session's converted
// opportunities as a flat grid of cards (the stage-grouped columns + rich card
// fields are later P2.2 epics), each showing its current stage. A holder of
// `create_edit_records` gets a one-click Advance on each non-terminal card that
// moves it to the server-computed next stage; on success the board refetches so
// the card reflects its new stage.

/** What the board fetch is doing — each branch renders once. */
type BoardLoadState =
  | { kind: "loading" }
  | { kind: "loaded"; opportunities: OpportunityRow[] }
  | { kind: "error" };

// The page header — the same Besley headline + Oxford rule on every body state.
function OpportunitiesHeader() {
  return (
    <header id="opportunities-header" className="opportunities-header">
      <h1 id="opportunities-title" className="opportunities-title">
        Opportunities
      </h1>
      <hr id="opportunities-rule" className="oxford-double-rule" />
    </header>
  );
}

export default function OpportunityPipelinePage() {
  const canAdvance = useCapability("create_edit_records");

  const [boardLoad, setBoardLoad] = useState<BoardLoadState>({
    kind: "loading",
  });
  // The id of the opportunity whose Advance is in flight (its button spins), or
  // null when none is pending. One at a time keeps the refetch reconcile simple.
  const [advancingId, setAdvancingId] = useState<string | null>(null);
  // A non-destructive advance error: the board stays intact and the notice shows
  // above it. Cleared on the next advance attempt.
  const [advanceError, setAdvanceError] = useState<string | null>(null);
  // True while the page is mounted. Both the mount fetch and the post-advance
  // refetch read it before they `setState`, so a fetch in flight when the page
  // unmounts cannot update a gone component (mirrors LeadsListPage's cleanup ref).
  const isMountedRef = useRef(true);

  // Fetch the board; a resolve is ignored once the page has unmounted.
  const loadBoard = useCallback(() => {
    setBoardLoad({ kind: "loading" });
    listOpportunities()
      .then((opportunities) => {
        if (isMountedRef.current) {
          setBoardLoad({ kind: "loaded", opportunities });
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

  const advance = async (opportunity: OpportunityRow) => {
    if (opportunity.next_stage === null) {
      return;
    }
    setAdvanceError(null);
    setAdvancingId(opportunity.id);
    try {
      await changeOpportunityStage(opportunity.id, opportunity.next_stage);
      loadBoard();
    } catch {
      setAdvanceError("Could not advance the opportunity. Please try again.");
    } finally {
      setAdvancingId(null);
    }
  };

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

  const { opportunities } = boardLoad;

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

      {opportunities.length === 0 ? (
        <div id="opportunities-empty" className="opportunities-empty">
          <p
            id="opportunities-empty-message"
            className="opportunities-empty-message"
          >
            No opportunities yet. Convert a qualified lead to open one.
          </p>
        </div>
      ) : (
        <div id="opportunities-grid" className="opportunities-grid">
          {opportunities.map((opportunity) => (
            <Card
              key={opportunity.id}
              id={`opportunity-card-${opportunity.id}`}
              title={opportunity.product_line}
              footer={
                canAdvance && opportunity.next_stage !== null ? (
                  <Button
                    id={`opportunity-advance-${opportunity.id}`}
                    variant="filled"
                    isPending={advancingId === opportunity.id}
                    onClick={() => advance(opportunity)}
                  >
                    {`Advance to ${opportunity.next_stage}`}
                  </Button>
                ) : (
                  <p
                    id={`opportunity-terminal-${opportunity.id}`}
                    className="opportunity-card-terminal"
                  >
                    No further stage
                  </p>
                )
              }
            >
              <div
                id={`opportunity-stage-line-${opportunity.id}`}
                className="opportunity-card-line"
              >
                <StampTag
                  id={`opportunity-stage-${opportunity.id}`}
                  status="neutral"
                >
                  {opportunity.stage}
                </StampTag>
              </div>
              <p
                id={`opportunity-contact-${opportunity.id}`}
                className="opportunity-card-contact"
              >
                {`Contact ${opportunity.contact_id}`}
              </p>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
