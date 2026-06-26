import { useCallback, useEffect, useRef, useState } from "react";
import Button from "../components/Button.tsx";
import Card from "../components/Card.tsx";
import ExplainerPopover from "../components/ExplainerPopover.tsx";
import { medicareGateExplainer } from "../components/explainerContent.ts";
import { useCapability } from "../session";
import { ApiError, changeOpportunityStage, getOpportunityBoard } from "../api";
import type { OpportunityBoard, OpportunityRow } from "../api";

// The authenticated pipeline board at `/app/opportunities` (P2.2). It renders
// INSIDE the AppShell chrome (masthead + left nav), so it carries its OWN Guide §5
// page header (a Besley "Opportunities" headline + the Oxford double rule),
// mirroring the leads list.
//
// The board shows one COLUMN per the tenant's enabled stage (Epic 3/4), headed by
// that tenant's stage label, with each opportunity card grouped into its stage's
// column. A holder of `create_edit_records` gets a one-click Advance on each
// non-terminal card that moves it to the server-computed next *enabled* stage
// (a disabled optional stage is skipped); on success the board refetches.
//
// The columns + cards are rendered inline here; Epic 8 splits them into
// PipelineBoard / PipelineColumn / OpportunityCard components and adds the value
// fields. This epic owns the grouped, tenant-labeled columns and the skip-aware
// Advance label.

/** What the board fetch is doing — each branch renders once. */
type BoardLoadState =
  | { kind: "loading" }
  | { kind: "loaded"; board: OpportunityBoard }
  | { kind: "error" };

// The page header — the same Besley headline + Oxford rule on every body state,
// with the Medicare-gate explainer beside the title.
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

  const { pipeline, opportunities } = boardLoad.board;
  // Map a canonical stage key to this tenant's display label (the Advance target
  // names the next stage in the tenant's own words).
  const labelForStage = (stageKey: string): string =>
    pipeline.stages.find((stage) => stage.key === stageKey)?.label ?? stageKey;

  const renderCard = (opportunity: OpportunityRow) => {
    const nextStage = opportunity.next_stage;
    const isTerminal = nextStage === null && !opportunity.can_mark_lost;
    return (
    <Card
      key={opportunity.id}
      id={`opportunity-card-${opportunity.id}`}
      title={opportunity.product_line}
      headingLevel={3}
      footer={
        isTerminal ? (
          <p
            id={`opportunity-terminal-${opportunity.id}`}
            className="opportunity-card-terminal"
          >
            No further stage
          </p>
        ) : canAdvance ? (
          <div
            id={`opportunity-actions-${opportunity.id}`}
            className="opportunity-card-actions"
          >
            {nextStage !== null && (
              <Button
                id={`opportunity-advance-${opportunity.id}`}
                variant="filled"
                isPending={changingId === opportunity.id}
                onClick={() => changeStage(opportunity.id, nextStage)}
              >
                {`Advance to ${labelForStage(nextStage)}`}
              </Button>
            )}
            {opportunity.can_mark_lost && (
              <Button
                id={`opportunity-mark-lost-${opportunity.id}`}
                variant="outlined"
                isPending={changingId === opportunity.id}
                onClick={() => changeStage(opportunity.id, "Lost")}
              >
                Mark Lost
              </Button>
            )}
          </div>
        ) : undefined
      }
    >
      <p
        id={`opportunity-contact-${opportunity.id}`}
        className="opportunity-card-contact"
      >
        {`Contact ${opportunity.contact_id}`}
      </p>
    </Card>
    );
  };

  // Lost is terminal and off-spine, so it has no pipeline column; collect any Lost
  // cards into their own lane so they stay visible on the board.
  const lostOpportunities = opportunities.filter(
    (opportunity) => opportunity.stage === "Lost",
  );

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
        <div id="opportunities-board" className="opportunities-board">
          {pipeline.stages.map((stage) => {
            const cards = opportunities.filter(
              (opportunity) => opportunity.stage === stage.key,
            );
            return (
              <section
                key={stage.key}
                id={`pipeline-column-${stage.key}`}
                className="pipeline-column"
                aria-labelledby={`pipeline-column-${stage.key}-heading`}
              >
                <h2
                  id={`pipeline-column-${stage.key}-heading`}
                  className="pipeline-column-heading"
                >
                  {stage.label}
                </h2>
                <div
                  id={`pipeline-column-${stage.key}-cards`}
                  className="pipeline-column-cards"
                >
                  {cards.length === 0 ? (
                    <p
                      id={`pipeline-column-${stage.key}-empty`}
                      className="pipeline-column-empty"
                    >
                      No opportunities
                    </p>
                  ) : (
                    cards.map(renderCard)
                  )}
                </div>
              </section>
            );
          })}

          {lostOpportunities.length > 0 && (
            <section
              id="pipeline-column-lost"
              className="pipeline-column pipeline-column-lost"
              aria-labelledby="pipeline-column-lost-heading"
            >
              <h2
                id="pipeline-column-lost-heading"
                className="pipeline-column-heading pipeline-column-lost-heading"
              >
                Lost
              </h2>
              <div
                id="pipeline-column-lost-cards"
                className="pipeline-column-cards"
              >
                {lostOpportunities.map(renderCard)}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
