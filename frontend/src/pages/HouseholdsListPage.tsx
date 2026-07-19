import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Community } from "iconoir-react";
import Button from "../components/Button.tsx";
import { getHouseholds } from "../api";
import type { HouseholdSearchResult } from "../api";

// The households index at `/app/households` (Epic 14) — the nav landing that backs
// the "Households" rail entry. It renders INSIDE the AppShell chrome (masthead +
// left nav), so it carries its OWN Guide §5 page header (a Besley "Households"
// headline + the Oxford double rule).
//
// One read backs the page: `getHouseholds("")` lists every household visible to the
// caller (the seed baseline ∪ the caller's own demo session), name-ordered and capped
// at the search endpoint's limit. Each row links to the household detail page at
// `/app/households/{id}`. A name-search control is deferred (the endpoint supports
// `?q=`) to hold this index at Goal scope, mirroring Epic 11's deferred assignee
// filter — the detail page + cross-sell prompt is this epic's substance.

/** What the household fetch is doing — each branch renders once (the LeadsListPage
 *  / TasksPage LoadState idiom). */
type HouseholdsLoadState =
  | { kind: "loading" }
  | { kind: "loaded"; households: HouseholdSearchResult[] }
  | { kind: "error" };

// The page header — the same Besley headline + Oxford rule on every branch, so each
// body state wraps it. No action affordance (households are created by lead
// conversion, never from this index).
function HouseholdsListHeader() {
  return (
    <header id="households-list-header" className="households-list-header">
      <h1 id="households-list-title" className="households-list-title">
        Households
      </h1>
      <hr id="households-list-rule" className="oxford-double-rule" />
    </header>
  );
}

export default function HouseholdsListPage() {
  const [householdsLoad, setHouseholdsLoad] = useState<HouseholdsLoadState>({
    kind: "loading",
  });

  // Fetch every visible household (empty query = all, name-ordered on the server).
  // Returns the cleanup that ignores a stale resolve after unmount.
  const loadHouseholds = useCallback(() => {
    setHouseholdsLoad({ kind: "loading" });
    let isActive = true;
    getHouseholds("")
      .then((households) => {
        if (isActive) {
          setHouseholdsLoad({ kind: "loaded", households });
        }
      })
      .catch(() => {
        if (isActive) {
          setHouseholdsLoad({ kind: "error" });
        }
      });
    return () => {
      isActive = false;
    };
  }, []);

  useEffect(() => loadHouseholds(), [loadHouseholds]);

  if (householdsLoad.kind === "loading") {
    return (
      <div id="households-list-page" className="households-list-page">
        <HouseholdsListHeader />
        <p
          id="households-list-loading"
          className="households-list-status"
          role="status"
          aria-live="polite"
        >
          Loading households…
        </p>
      </div>
    );
  }

  if (householdsLoad.kind === "error") {
    return (
      <div id="households-list-page" className="households-list-page">
        <HouseholdsListHeader />
        <div id="households-list-error" className="households-list-error">
          <p
            id="households-list-error-message"
            className="households-list-status"
            role="status"
            aria-live="polite"
          >
            We couldn't load your households. Please try again.
          </p>
          <Button
            id="households-list-error-retry-button"
            variant="tonal"
            onClick={loadHouseholds}
          >
            Retry
          </Button>
        </div>
      </div>
    );
  }

  if (householdsLoad.households.length === 0) {
    return (
      <div id="households-list-page" className="households-list-page">
        <HouseholdsListHeader />
        <HouseholdsEmptyState />
      </div>
    );
  }

  return (
    <div id="households-list-page" className="households-list-page">
      <HouseholdsListHeader />
      <ul id="households-list" className="households-list">
        {householdsLoad.households.map((household) => (
          <HouseholdListRow key={household.id} household={household} />
        ))}
      </ul>
    </div>
  );
}

// ---- Empty state: a calm Guide §5 framed ledger note (mirrors LeadsEmptyState) ----

function HouseholdsEmptyState() {
  return (
    <div id="households-list-empty" className="households-list-empty" role="status">
      <span
        id="households-list-empty-icon"
        className="households-list-empty-icon"
        aria-hidden="true"
      >
        <Community width={28} height={28} />
      </span>
      <p id="households-list-empty-message" className="households-list-empty-message">
        No households yet — convert a lead to create one.
      </p>
    </div>
  );
}

// ---- One household row: a bordered paper card linking to the detail page ----

// The member names, joined for the row subtext (plaintext first + last, no PII), or
// a calm fallback when a household has no contacts yet.
function memberNames(household: HouseholdSearchResult): string {
  if (household.members.length === 0) {
    return "No members yet";
  }
  return household.members
    .map((member) => `${member.first_name} ${member.last_name}`)
    .join(", ");
}

function HouseholdListRow({
  household,
}: {
  household: HouseholdSearchResult;
}) {
  return (
    <li id={`households-list-row-${household.id}`} className="households-list-row">
      <Link
        id={`households-list-row-${household.id}-link`}
        className="households-list-row-link"
        to={`/app/households/${household.id}`}
      >
        <span
          id={`households-list-row-${household.id}-name`}
          className="households-list-row-name"
        >
          {household.name}
        </span>
        <span
          id={`households-list-row-${household.id}-members`}
          className="households-list-row-members"
        >
          {memberNames(household)}
        </span>
      </Link>
    </li>
  );
}
