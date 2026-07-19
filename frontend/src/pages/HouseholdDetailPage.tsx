import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import PolicySummary from "./PolicySummary.tsx";
import Button from "../components/Button.tsx";
import { useCapability } from "../session";
import { ApiError, acceptCrossSell, getHouseholdDetail } from "../api";
import type { CrossSellSuggestion, HouseholdDetail } from "../api";

// The household DETAIL page at `/app/households/:id` (Epic 14) — the customer-facing
// household view. It renders INSIDE the AppShell chrome, so it carries its own Guide
// §5 page header (the household name in Besley + the Oxford double rule) plus a back
// link to the index.
//
// One read backs the page: `getHouseholdDetail(id)` returns the household, its
// contacts, its active overlay-aware policies (a swept baseline policy reads *Renewal
// Due* via the derive-at-read overlay, Epic 6/7), and its cross-sell suggestions. A
// household not visible to the caller is a 404 (Epic 13), rendered as a calm
// not-found note. The cross-sell prompt cards are layered on in Phase 4.

/** What the household fetch is doing — each branch renders once (the
 *  OpportunityDetailPage load-state idiom, with a 404 not-found branch). */
type DetailLoadState =
  | { kind: "loading" }
  | { kind: "loaded"; detail: HouseholdDetail }
  | { kind: "not-found" }
  | { kind: "error" };

export default function HouseholdDetailPage() {
  const { id: householdId } = useParams<{ id: string }>();
  // The cross-sell "Create opportunity" action is gated on `create_edit_records` —
  // Read-Only sees no button (mirrors the endpoint's 403).
  const canCreateCrossSell = useCapability("create_edit_records");

  const [detailLoad, setDetailLoad] = useState<DetailLoadState>({
    kind: "loading",
  });
  // The product line whose accept is in flight (its button shows the spinner), or null.
  const [acceptingLine, setAcceptingLine] = useState<string | null>(null);
  // The lines already accepted this visit — their cards flip to a terminal "Opportunity
  // created" state. This is CLIENT-SIDE by necessity (ADR 0002): a cross-sell creates an
  // Opportunity, not a policy, and coverage is policy-only, so a refetch would still
  // return the accepted line — the card must not rely on a refetch to disappear.
  const [acceptedLines, setAcceptedLines] = useState<Set<string>>(new Set());
  // A non-destructive accept error: the cards stay intact and the button re-enables.
  const [acceptError, setAcceptError] = useState<string | null>(null);

  // Fetch the household detail. A 404 (household not visible to the caller) is its own
  // calm branch; any other failure is the generic error + retry. Returns the cleanup
  // that ignores a stale resolve after unmount. A reload also clears the client-side
  // cross-sell accept state (it belongs to the prior render of the cards).
  const loadDetail = useCallback(() => {
    if (householdId === undefined) {
      return () => {};
    }
    setDetailLoad({ kind: "loading" });
    setAcceptedLines(new Set());
    setAcceptError(null);
    let isActive = true;
    getHouseholdDetail(householdId)
      .then((detail) => {
        if (isActive) {
          setDetailLoad({ kind: "loaded", detail });
        }
      })
      .catch((error: unknown) => {
        if (!isActive) {
          return;
        }
        setDetailLoad(
          error instanceof ApiError && error.status === 404
            ? { kind: "not-found" }
            : { kind: "error" },
        );
      });
    return () => {
      isActive = false;
    };
  }, [householdId]);

  useEffect(() => loadDetail(), [loadDetail]);

  // Accept one cross-sell line → open the opportunity, then flip that card to its
  // terminal "Opportunity created" state client-side (see `acceptedLines` above). A
  // failure (403/409 — e.g. the line was covered or accepted elsewhere) surfaces a
  // non-destructive inline error and re-enables the button.
  const acceptCrossSellLine = (productLine: string) => {
    if (householdId === undefined) {
      return;
    }
    setAcceptError(null);
    setAcceptingLine(productLine);
    acceptCrossSell(householdId, productLine)
      .then(() => {
        setAcceptedLines((accepted) => new Set(accepted).add(productLine));
      })
      .catch((error: unknown) => {
        setAcceptError(
          error instanceof ApiError
            ? error.message
            : "We couldn't create that opportunity. Please try again.",
        );
      })
      .finally(() => {
        setAcceptingLine(null);
      });
  };

  return (
    <div id="household-detail-page" className="household-detail-page">
      <p id="household-detail-back-row" className="household-detail-back-row">
        <Link id="household-detail-back" to="/app/households">
          ← Back to households
        </Link>
      </p>
      <HouseholdDetailBody
        detailLoad={detailLoad}
        onRetry={loadDetail}
        crossSell={{
          canCreateCrossSell,
          acceptingLine,
          acceptedLines,
          acceptError,
          onAccept: acceptCrossSellLine,
        }}
      />
    </div>
  );
}

/** The cross-sell prompt's props, bundled so the loaded branch can thread them to
 *  the CrossSellSection without a long parameter list. */
interface CrossSellControls {
  /** Whether the caller may accept (holds `create_edit_records`). */
  canCreateCrossSell: boolean;
  /** The line whose accept is in flight, or null. */
  acceptingLine: string | null;
  /** The lines already accepted this visit (terminal cards). */
  acceptedLines: Set<string>;
  /** A non-destructive accept error message, or null. */
  acceptError: string | null;
  /** Accept the given product line. */
  onAccept: (productLine: string) => void;
}

// The detail body — one branch per load state. The loaded state renders the header,
// contacts, and the active policies; the others render a calm status note.
function HouseholdDetailBody({
  detailLoad,
  onRetry,
  crossSell,
}: {
  detailLoad: DetailLoadState;
  onRetry: () => void;
  crossSell: CrossSellControls;
}) {
  if (detailLoad.kind === "loading") {
    return (
      <p
        id="household-detail-loading"
        className="household-detail-status"
        role="status"
        aria-live="polite"
      >
        Loading household…
      </p>
    );
  }

  if (detailLoad.kind === "not-found") {
    return (
      <p id="household-detail-not-found" className="household-detail-status">
        This household could not be found.
      </p>
    );
  }

  if (detailLoad.kind === "error") {
    return (
      <div id="household-detail-error" className="household-detail-error">
        <p
          id="household-detail-error-message"
          className="household-detail-status"
          role="status"
          aria-live="polite"
        >
          We couldn't load this household. Please try again.
        </p>
        <Button
          id="household-detail-error-retry-button"
          variant="tonal"
          onClick={onRetry}
        >
          Retry
        </Button>
      </div>
    );
  }

  const { detail } = detailLoad;
  return (
    <>
      <header id="household-detail-header" className="household-detail-header">
        <h1 id="household-detail-title" className="household-detail-title">
          {detail.household.name}
        </h1>
        <hr id="household-detail-rule" className="oxford-double-rule" />
      </header>
      <ContactsSection contacts={detail.contacts} />
      <PoliciesSection policies={detail.policies} />
      <CrossSellSection crossSellLines={detail.cross_sell} controls={crossSell} />
    </>
  );
}

// ---- Contacts: the household's people (plaintext names, no PII) ----

function ContactsSection({
  contacts,
}: {
  contacts: HouseholdDetail["contacts"];
}) {
  return (
    <section
      id="household-detail-contacts"
      className="household-detail-section"
      aria-labelledby="household-detail-contacts-heading"
    >
      <h2
        id="household-detail-contacts-heading"
        className="household-detail-section-heading"
      >
        Contacts
      </h2>
      {contacts.length === 0 ? (
        <p
          id="household-detail-contacts-empty"
          className="household-detail-empty-note"
        >
          No contacts in this household yet.
        </p>
      ) : (
        <ul id="household-detail-contacts-list" className="household-detail-contacts-list">
          {contacts.map((contact) => (
            <li
              key={contact.id}
              id={`household-detail-contact-${contact.id}`}
              className="household-detail-contact"
            >
              {`${contact.first_name} ${contact.last_name}`}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ---- Policies: the household's ACTIVE policies, overlay-aware (*Renewal Due*) ----

// Each policy reuses the shared PolicySummary (Epic 6/8) — already overlay-aware, so
// a swept baseline policy shows the *Renewal Due* warning badge for free. Every
// instance is given a unique id prefix (PolicySummary derives all its child ids from
// it) so two policies never collide on the repo's unique-id rule.
function PoliciesSection({
  policies,
}: {
  policies: HouseholdDetail["policies"];
}) {
  return (
    <section
      id="household-detail-policies"
      className="household-detail-section"
      aria-labelledby="household-detail-policies-heading"
    >
      <h2
        id="household-detail-policies-heading"
        className="household-detail-section-heading"
      >
        Policies
      </h2>
      {policies.length === 0 ? (
        <p
          id="household-detail-policies-empty"
          className="household-detail-empty-note"
        >
          This household has no active policies.
        </p>
      ) : (
        <div id="household-detail-policies-list" className="household-detail-policies-list">
          {policies.map((policy) => (
            <PolicySummary
              key={policy.id}
              id={`household-detail-policy-${policy.id}`}
              policy={policy}
            />
          ))}
        </div>
      )}
    </section>
  );
}

// ---- Cross-sell prompt: Guide §6.14 framed ledger notes for coverage gaps ----

// One information-toned card per uncovered product line, with a one-click "Create
// opportunity" action. The whole block is suppressed when the backend returns no
// suggestions (fully covered, or the household has no active policy — ADR 0002), so a
// household with no gaps shows nothing here at all.
function CrossSellSection({
  crossSellLines,
  controls,
}: {
  crossSellLines: CrossSellSuggestion[];
  controls: CrossSellControls;
}) {
  if (crossSellLines.length === 0) {
    return null;
  }
  return (
    <section
      id="household-detail-cross-sell"
      className="household-detail-section"
      aria-labelledby="household-detail-cross-sell-heading"
    >
      <h2
        id="household-detail-cross-sell-heading"
        className="household-detail-section-heading"
      >
        Cross-sell opportunities
      </h2>
      {controls.acceptError !== null && (
        <p
          id="household-detail-cross-sell-error"
          className="household-detail-cross-sell-error"
          role="alert"
        >
          {controls.acceptError}
        </p>
      )}
      <div id="household-detail-cross-sell-list" className="household-detail-cross-sell-list">
        {crossSellLines.map((line) => (
          <CrossSellCard
            key={line.product_line}
            line={line}
            controls={controls}
          />
        ))}
      </div>
    </section>
  );
}

// A single coverage-gap card (Guide §6.14): an information-toned framed note naming the
// gap, plus the gated "Create opportunity" action. Once accepted it flips to a terminal
// "Opportunity created" note — the action does not reappear (the accept is client-side
// terminal, since a refetch would still list the line, ADR 0002).
function CrossSellCard({
  line,
  controls,
}: {
  line: CrossSellSuggestion;
  controls: CrossSellControls;
}) {
  const isAccepted = controls.acceptedLines.has(line.product_line);
  const rowId = `household-detail-cross-sell-${line.product_line}`;
  return (
    <div id={rowId} className="household-detail-cross-sell-card">
      <p id={`${rowId}-note`} className="household-detail-cross-sell-note">
        {`This household has no ${line.product_line_label} coverage.`}
      </p>
      {isAccepted ? (
        <p id={`${rowId}-created`} className="household-detail-cross-sell-created">
          Opportunity created
        </p>
      ) : (
        controls.canCreateCrossSell && (
          <Button
            id={`${rowId}-accept-button`}
            variant="tonal"
            isPending={controls.acceptingLine === line.product_line}
            onClick={() => controls.onAccept(line.product_line)}
          >
            Create opportunity
          </Button>
        )
      )}
    </div>
  );
}
