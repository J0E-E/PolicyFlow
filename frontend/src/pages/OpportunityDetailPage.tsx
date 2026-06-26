import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import QuotePanel from "./QuotePanel.tsx";
import ApplicationSummary from "./ApplicationSummary.tsx";
import ApplicationStep from "./ApplicationStep.tsx";
import PolicySummary from "./PolicySummary.tsx";
import Button from "../components/Button.tsx";
import { useCapability } from "../session";
import { ApiError, getOpportunityBoard, selectQuote, submitApplication } from "../api";
import type { Application, OpportunityRow, Policy } from "../api";

// Whether a Draft application's product step is captured (or it has no step), so it
// is ready to submit. The Medicare ID is optional and does not gate submission.
function isStepComplete(application: Application): boolean {
  if (application.application_step === "beneficiary") {
    return application.beneficiary !== null;
  }
  if (application.application_step === "health") {
    return application.health_answers !== null;
  }
  return true;
}

// Whether the capture form should render — an uncaptured product step, or an
// uncaptured Tenant-1 Medicare ID.
function needsCapture(application: Application): boolean {
  const medicareUncaptured =
    application.collects_medicare_id && application.medicare_id_masked === null;
  return !isStepComplete(application) || medicareUncaptured;
}

// The agent-workspace OPPORTUNITY DETAIL page at `/app/opportunities/:id` (P2.3
// Epic 3). The minimal first slice: an opportunity header (contact, product line,
// current stage) plus the carrier-quote round-trip panel. Later P2.3 epics extend
// this same page with selection, the application step, submit, and the policy view.
//
// There is no single-opportunity read endpoint yet, so the page reuses the board
// fetch (`GET /api/opportunities`) and selects the row by id — sufficient at the
// demo's scale and avoiding a new endpoint for the tracer. The page is thin: it
// owns the fetch + the locally-tracked stage (the round-trip moves it to *Quoted*)
// and delegates the round-trip to `QuotePanel` (Frontend Philosophy).

const EM_DASH = "—";

/** What the fetch is doing — each branch renders once. */
type DetailLoadState =
  | { kind: "loading" }
  | { kind: "loaded"; opportunity: OpportunityRow }
  | { kind: "not-found" }
  | { kind: "error" };

export default function OpportunityDetailPage() {
  const { id: opportunityId } = useParams<{ id: string }>();
  const canRequest = useCapability("create_edit_records");

  const [detailLoad, setDetailLoad] = useState<DetailLoadState>({ kind: "loading" });
  // The opportunity's stage, tracked locally so the round-trip's move to *Quoted*
  // (and selection's move to *Application Started*) reflects without a refetch.
  const [stage, setStage] = useState<string | null>(null);
  // The Draft Application once a quote is selected; the quote panel then renders its
  // options read-only and the summary appears.
  const [application, setApplication] = useState<Application | null>(null);
  // The quote whose selection is in flight (its Select button spins), and a
  // non-destructive selection error shown above the panel.
  const [selectingQuoteId, setSelectingQuoteId] = useState<string | null>(null);
  const [selectError, setSelectError] = useState<string | null>(null);
  // The submit-in-flight flag and a non-destructive submit error.
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  // The issued policy once an application is approved + submitted.
  const [policy, setPolicy] = useState<Policy | null>(null);
  const isMountedRef = useRef(true);

  const loadOpportunity = useCallback(() => {
    setDetailLoad({ kind: "loading" });
    getOpportunityBoard()
      .then((board) => {
        if (!isMountedRef.current) {
          return;
        }
        const opportunity = board.opportunities.find(
          (row) => row.id === opportunityId,
        );
        if (opportunity === undefined) {
          setDetailLoad({ kind: "not-found" });
          return;
        }
        setDetailLoad({ kind: "loaded", opportunity });
        setStage(opportunity.stage);
      })
      .catch(() => {
        if (isMountedRef.current) {
          setDetailLoad({ kind: "error" });
        }
      });
  }, [opportunityId]);

  useEffect(() => {
    isMountedRef.current = true;
    loadOpportunity();
    return () => {
      isMountedRef.current = false;
    };
  }, [loadOpportunity]);

  // Select a quote → create the Draft Application. On success the application
  // appears and the opportunity advances to *Application Started* server-side, so we
  // reflect both locally without a refetch.
  const handleSelectQuote = (quoteId: string) => {
    if (opportunityId === undefined) {
      return;
    }
    setSelectError(null);
    setSelectingQuoteId(quoteId);
    selectQuote(opportunityId, quoteId)
      .then((created) => {
        setApplication(created);
        setStage("Application Started");
        // A re-selection after a decline starts a fresh attempt — drop any prior
        // issued policy from view.
        setPolicy(null);
        setSelectingQuoteId(null);
      })
      .catch((error: unknown) => {
        setSelectError(
          error instanceof ApiError
            ? error.message
            : "We couldn't select that quote. Please try again.",
        );
        setSelectingQuoteId(null);
      });
  };

  // Submit the Draft application → the inline carrier decision runs server-side. On
  // success the decided application + the opportunity's new stage are reflected.
  const handleSubmit = () => {
    if (application === null) {
      return;
    }
    setSubmitError(null);
    setIsSubmitting(true);
    submitApplication(application.id)
      .then((result) => {
        setApplication(result.application);
        setStage(result.opportunity_stage);
        setPolicy(result.policy);
        setIsSubmitting(false);
      })
      .catch((error: unknown) => {
        setSubmitError(
          error instanceof ApiError
            ? error.message
            : "We couldn't submit the application. Please try again.",
        );
        setIsSubmitting(false);
      });
  };

  return (
    <div id="opportunity-detail-page" className="opportunity-detail-page">
      <p id="opportunity-detail-back-row" className="opportunity-detail-back-row">
        <Link id="opportunity-detail-back" to="/app/opportunities">
          ← Back to opportunities
        </Link>
      </p>
      <OpportunityDetailBody
        detailLoad={detailLoad}
        stage={stage}
        canRequest={canRequest}
        opportunityId={opportunityId ?? ""}
        application={application}
        policy={policy}
        selectingQuoteId={selectingQuoteId}
        selectError={selectError}
        isSubmitting={isSubmitting}
        submitError={submitError}
        onStageChange={setStage}
        onSelectQuote={handleSelectQuote}
        onStepCaptured={setApplication}
        onSubmit={handleSubmit}
        onRetry={loadOpportunity}
      />
    </div>
  );
}

// The detail body — one branch per load state. The loaded state renders the
// header and the quote panel; the others render a calm status note.
function OpportunityDetailBody({
  detailLoad,
  stage,
  canRequest,
  opportunityId,
  application,
  policy,
  selectingQuoteId,
  selectError,
  isSubmitting,
  submitError,
  onStageChange,
  onSelectQuote,
  onStepCaptured,
  onSubmit,
  onRetry,
}: {
  detailLoad: DetailLoadState;
  stage: string | null;
  canRequest: boolean;
  opportunityId: string;
  application: Application | null;
  policy: Policy | null;
  selectingQuoteId: string | null;
  selectError: string | null;
  isSubmitting: boolean;
  submitError: string | null;
  onStageChange: (stage: string) => void;
  onSelectQuote: (quoteId: string) => void;
  onStepCaptured: (application: Application) => void;
  onSubmit: () => void;
  onRetry: () => void;
}) {
  if (detailLoad.kind === "loading") {
    return (
      <p id="opportunity-detail-loading" className="opportunity-detail-status">
        Loading opportunity…
      </p>
    );
  }

  if (detailLoad.kind === "not-found") {
    return (
      <p id="opportunity-detail-not-found" className="opportunity-detail-status">
        This opportunity could not be found.
      </p>
    );
  }

  if (detailLoad.kind === "error") {
    return (
      <div id="opportunity-detail-error-row" className="opportunity-detail-error-row">
        <p id="opportunity-detail-error" className="opportunity-detail-status">
          Could not load this opportunity.
        </p>
        <button
          id="opportunity-detail-retry"
          type="button"
          className="opportunity-detail-retry"
          onClick={onRetry}
        >
          Try again
        </button>
      </div>
    );
  }

  const { opportunity } = detailLoad;
  const firstName = opportunity.contact_first_name ?? "";
  const lastName = opportunity.contact_last_name ?? "";
  const contactName = `${firstName} ${lastName}`.trim() || EM_DASH;
  const currentStage = stage ?? opportunity.stage;

  return (
    <>
      <header id="opportunity-detail-header" className="opportunity-detail-header">
        <h1 id="opportunity-detail-title" className="opportunity-detail-title">
          {contactName}
        </h1>
        <p id="opportunity-detail-product-line" className="opportunity-detail-product-line">
          {opportunity.product_line_label}
        </p>
        <p id="opportunity-detail-stage" className="opportunity-detail-stage">
          {`Stage: ${currentStage}`}
        </p>
        <hr id="opportunity-detail-rule" className="oxford-double-rule" />
      </header>
      {selectError && (
        <p id="opportunity-detail-select-error" className="opportunity-detail-status" role="alert">
          {selectError}
        </p>
      )}
      {application && (
        <ApplicationSummary id="opportunity-detail-application" application={application} />
      )}
      {policy && <PolicySummary id="opportunity-detail-policy" policy={policy} />}
      {application &&
        application.status === "Draft" &&
        needsCapture(application) && (
          <ApplicationStep
            id="opportunity-detail-step"
            application={application}
            onCaptured={onStepCaptured}
          />
        )}
      {application &&
        application.status === "Draft" &&
        isStepComplete(application) &&
        canRequest && (
          <div id="opportunity-detail-submit-row" className="opportunity-detail-submit-row">
            {submitError && (
              <p id="opportunity-detail-submit-error" className="opportunity-detail-status" role="alert">
                {submitError}
              </p>
            )}
            <Button
              id="opportunity-detail-submit"
              variant="filled"
              isPending={isSubmitting}
              onClick={onSubmit}
            >
              Submit application
            </Button>
          </div>
        )}
      <QuotePanel
        id="opportunity-detail-quotes"
        opportunityId={opportunityId}
        stage={currentStage}
        canRequest={canRequest}
        onOpportunityStageChange={onStageChange}
        onSelectQuote={
          application === null || application.status === "Declined"
            ? onSelectQuote
            : undefined
        }
        selectingQuoteId={selectingQuoteId}
      />
    </>
  );
}
