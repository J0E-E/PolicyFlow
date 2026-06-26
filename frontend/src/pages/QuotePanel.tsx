import { useEffect, useRef, useState } from "react";
import Button from "../components/Button.tsx";
import StampTag from "../components/StampTag.tsx";
import { ApiError, getQuoteRequest, requestQuotes } from "../api";
import type { QuoteOption } from "../api";

// The live-poll cadence while a round-trip is pending — the P1.9 idiom (1500 ms,
// inside the TDD's ~1.5s band), reused so the broker round-trip's `pending →
// completed` flip is caught within a tick of the ~1s relay.
const POLL_INTERVAL_MS = 1500;

// The stage from which quotes may be requested — the coherent precondition the
// request endpoint also enforces (a non-Qualified request is a 409).
const QUOTABLE_STAGE = "Qualified";

interface QuotePanelProperties {
  /** Required so every rendered element is uniquely targetable (CLAUDE.md). */
  id: string;
  /** The opportunity this round-trip is opened for. */
  opportunityId: string;
  /** The opportunity's current stage — gates the Request control. */
  stage: string;
  /** Whether the caller may open a round-trip (holds `create_edit_records`). A
   *  Read-Only viewer sees the panel but never the action. */
  canRequest: boolean;
  /** Fired with the opportunity's new stage when the round-trip completes (it moves
   *  to *Quoted* server-side), so the page reflects the move. */
  onOpportunityStageChange?: (stage: string) => void;
  /** Fired when the caller selects one of the returned options to turn into an
   *  Application. Absent (e.g. once an Application already exists) hides the Select
   *  controls — the options then render read-only. */
  onSelectQuote?: (quoteId: string) => void;
  /** The id of the quote whose selection is in flight (its Select button spins), or
   *  null when none is pending. */
  selectingQuoteId?: string | null;
}

// What the round-trip is doing — each branch renders once inside the panel.
type RoundTripState =
  | { kind: "idle" }
  | { kind: "requesting" }
  | { kind: "pending"; quoteRequestId: string }
  | { kind: "completed"; quotes: QuoteOption[] }
  | { kind: "error"; message: string };

// The carrier-quote round-trip panel (P2.3 Epic 3) on the opportunity detail page:
// a Request-quotes control that opens the broker round-trip, the live `pending`
// status while the stub works, and the returned options once `completed`. Read-only
// (selection is Epic 5). A focused component (Frontend Philosophy); the page owns
// the opportunity header. Tokens + design-system primitives only (the Guide wins).
export default function QuotePanel({
  id,
  opportunityId,
  stage,
  canRequest,
  onOpportunityStageChange,
  onSelectQuote,
  selectingQuoteId,
}: QuotePanelProperties) {
  const [roundTrip, setRoundTrip] = useState<RoundTripState>({ kind: "idle" });

  // Hold the stage-change callback in a ref so the poll effect never re-arms just
  // because the page passed a fresh closure — only the request id arms the loop.
  const onStageChangeRef = useRef(onOpportunityStageChange);
  onStageChangeRef.current = onOpportunityStageChange;

  // The armed poll: once a round-trip is pending, poll its status every
  // POLL_INTERVAL_MS until `completed`, then render the options and surface the
  // opportunity's *Quoted* move. A non-pending state arms nothing.
  const quoteRequestId =
    roundTrip.kind === "pending" ? roundTrip.quoteRequestId : null;
  useEffect(() => {
    if (quoteRequestId === null) {
      return;
    }
    let isActive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = () => {
      getQuoteRequest(opportunityId, quoteRequestId)
        .then((result) => {
          if (!isActive) {
            return;
          }
          if (result.quote_request.status === "completed") {
            setRoundTrip({ kind: "completed", quotes: result.quotes });
            onStageChangeRef.current?.(result.opportunity_stage);
            return;
          }
          timer = setTimeout(poll, POLL_INTERVAL_MS);
        })
        .catch((error: unknown) => {
          if (!isActive) {
            return;
          }
          setRoundTrip({
            kind: "error",
            message:
              error instanceof ApiError
                ? error.message
                : "We couldn't load the quote round-trip.",
          });
        });
    };

    poll();

    return () => {
      isActive = false;
      if (timer !== undefined) {
        clearTimeout(timer);
      }
    };
  }, [opportunityId, quoteRequestId]);

  const startRoundTrip = () => {
    setRoundTrip({ kind: "requesting" });
    requestQuotes(opportunityId)
      .then((quoteRequest) => {
        setRoundTrip({ kind: "pending", quoteRequestId: quoteRequest.id });
      })
      .catch((error: unknown) => {
        setRoundTrip({
          kind: "error",
          message:
            error instanceof ApiError
              ? error.message
              : "We couldn't request quotes. Please try again.",
        });
      });
  };

  return (
    <section id={id} className="quote-panel" aria-labelledby={`${id}-heading`}>
      <h2 id={`${id}-heading`} className="quote-panel-heading">
        Carrier quotes
      </h2>
      <QuotePanelBody
        id={id}
        stage={stage}
        canRequest={canRequest}
        roundTrip={roundTrip}
        onRequest={startRoundTrip}
        onSelectQuote={onSelectQuote}
        selectingQuoteId={selectingQuoteId ?? null}
      />
    </section>
  );
}

// The panel body — one branch per round-trip state, plus the pre-request prompt.
function QuotePanelBody({
  id,
  stage,
  canRequest,
  roundTrip,
  onRequest,
  onSelectQuote,
  selectingQuoteId,
}: {
  id: string;
  stage: string;
  canRequest: boolean;
  roundTrip: RoundTripState;
  onRequest: () => void;
  onSelectQuote?: (quoteId: string) => void;
  selectingQuoteId: string | null;
}) {
  if (roundTrip.kind === "pending" || roundTrip.kind === "requesting") {
    return (
      <p id={`${id}-pending`} className="quote-panel-note" role="status" aria-live="polite">
        Requesting quotes from carriers…
      </p>
    );
  }

  if (roundTrip.kind === "error") {
    return (
      <div id={`${id}-error-row`} className="quote-panel-error-row">
        <p id={`${id}-error`} className="quote-panel-note" role="alert">
          {roundTrip.message}
        </p>
        {canRequest && stage === QUOTABLE_STAGE && (
          <Button id={`${id}-retry`} variant="outlined" onClick={onRequest}>
            Try again
          </Button>
        )}
      </div>
    );
  }

  if (roundTrip.kind === "completed") {
    if (roundTrip.quotes.length === 0) {
      return (
        <p id={`${id}-empty`} className="quote-panel-note">
          No quotes were returned for this opportunity.
        </p>
      );
    }
    return (
      <ul id={`${id}-list`} className="quote-panel-list">
        {roundTrip.quotes.map((quote) => (
          <QuoteOptionItem
            key={quote.id}
            id={`${id}-quote-${quote.id}`}
            quote={quote}
            onSelectQuote={onSelectQuote}
            isSelecting={selectingQuoteId === quote.id}
          />
        ))}
      </ul>
    );
  }

  // idle — offer the request control when the opportunity is quotable and the
  // caller may act; otherwise a calm note explaining why there is no action.
  if (stage !== QUOTABLE_STAGE) {
    return (
      <p id={`${id}-not-quotable`} className="quote-panel-note">
        Quotes can be requested once the opportunity is qualified.
      </p>
    );
  }
  if (!canRequest) {
    return (
      <p id={`${id}-read-only`} className="quote-panel-note">
        You have read-only access to this opportunity.
      </p>
    );
  }
  return (
    <div id={`${id}-request-row`} className="quote-panel-request-row">
      <p id={`${id}-prompt`} className="quote-panel-note">
        Request canned carrier quotes for this opportunity.
      </p>
      <Button id={`${id}-request`} variant="filled" onClick={onRequest}>
        Request quotes
      </Button>
    </div>
  );
}

// One returned option — carrier, plan label, coverage, monthly + annual premium,
// and (when selectable) a Select control that turns it into a Draft Application.
function QuoteOptionItem({
  id,
  quote,
  onSelectQuote,
  isSelecting,
}: {
  id: string;
  quote: QuoteOption;
  onSelectQuote?: (quoteId: string) => void;
  isSelecting: boolean;
}) {
  return (
    <li id={id} className="quote-option">
      <div id={`${id}-header`} className="quote-option-header">
        <span id={`${id}-carrier`} className="quote-option-carrier">
          {quote.carrier}
        </span>
        <StampTag id={`${id}-coverage`} variant="overline">
          {`$${quote.coverage_amount.toLocaleString()} coverage`}
        </StampTag>
      </div>
      <p id={`${id}-label`} className="quote-option-label">
        {quote.product_label}
      </p>
      <p id={`${id}-premium`} className="quote-option-premium">
        {`$${quote.premium_monthly.toLocaleString()}/mo · $${quote.premium_annual.toLocaleString()}/yr`}
      </p>
      {onSelectQuote && (
        <Button
          id={`${id}-select`}
          variant="filled"
          isPending={isSelecting}
          onClick={() => onSelectQuote(quote.id)}
        >
          Select this quote
        </Button>
      )}
    </li>
  );
}
