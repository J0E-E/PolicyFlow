import { useCallback, useEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { CheckCircle, EmptyPage } from "iconoir-react";
import Button from "../components/Button.tsx";
import ButtonLink from "../components/ButtonLink.tsx";
import StampTag from "../components/StampTag.tsx";
import { leadStatusStamp } from "../components/leadStatusStamp.ts";
import { useCapability, useSession } from "../session";
import { claimLead, listLeads, listTenants } from "../api";
import type { MaskedLead, ProductLine, Tenant } from "../api";
import {
  isClaimable,
  isUnresolvedDuplicate,
  leadCreatedDate,
  leadOwnerLabel,
  leadProductLineLabels,
  leadSourceLabel,
} from "./leadsListPresentation.ts";

// The authenticated leads list at `/app/leads` (Epic 20). It renders INSIDE the
// AppShell chrome (masthead + left nav), so it carries its OWN Guide §5 page
// header (a Besley "Leads" headline + the Oxford double rule) plus a
// `create_edit_records`-gated "New lead" link, mirroring AgentIntakePage's
// header idiom.
//
// Two reads back the page:
//   - The tenant list (filtered to the session slug) supplies the product-line
//     registry so each row can map its selected keys to human labels. Resolved
//     once, mirroring AgentIntakePage's LoadState idiom (loading / error+retry).
//   - The leads themselves, refetched per active tab: "All leads" calls
//     `listLeads()`, "Unassigned queue" calls `listLeads(true)` (the queue
//     filter — unowned `New`). Switching tabs refetches.
//
// One-click Claim sits on each claimable row (unowned `New`) for holders of
// `claim_leads_manage_tasks`; on success the active tab refetches so the claimed
// lead leaves the queue (or flips to Working + owner on the All tab). Rows are
// NON-navigating — the name is plain text, not a link; the Epic 21 detail page
// owns `/app/leads/:id`.

/** Which tab is active — drives the `unassigned` argument to `listLeads`. */
type LeadsTab = "all" | "queue";

/** What the tenant resolution is doing (for the product-line labels). Mirrors
 *  AgentIntakePage so loading / error / loaded each render once. */
type TenantLoadState =
  | { kind: "loading" }
  | { kind: "loaded"; tenant: Tenant }
  | { kind: "not-found" }
  | { kind: "error" };

/** What the per-tab leads fetch is doing. */
type LeadsLoadState =
  | { kind: "loading" }
  | { kind: "loaded"; leads: MaskedLead[] }
  | { kind: "error" };

// The page header — the same Besley headline + Oxford rule on every branch, with
// the gated "New lead" affordance. Lives in one place so each body state wraps it.
function LeadsListHeader({ canCreateLeads }: { canCreateLeads: boolean }) {
  return (
    <header id="leads-list-header" className="leads-list-header">
      <div id="leads-list-header-row" className="leads-list-header-row">
        <h1 id="leads-list-title" className="leads-list-title">
          Leads
        </h1>
        {canCreateLeads && (
          <ButtonLink
            id="leads-list-new-lead-link"
            variant="filled"
            to="/app/leads/new"
          >
            New lead
          </ButtonLink>
        )}
      </div>
      <hr id="leads-list-rule" className="oxford-double-rule" />
    </header>
  );
}

export default function LeadsListPage() {
  const { identity } = useSession();
  const canCreateLeads = useCapability("create_edit_records");
  const canClaimLeads = useCapability("claim_leads_manage_tasks");
  const tenantSlug = identity?.user.tenant_slug ?? null;

  const [tenantLoad, setTenantLoad] = useState<TenantLoadState>({
    kind: "loading",
  });
  const [activeTab, setActiveTab] = useState<LeadsTab>("all");
  const [leadsLoad, setLeadsLoad] = useState<LeadsLoadState>({
    kind: "loading",
  });
  // The id of the lead whose Claim is in flight (its button shows the spinner),
  // or null when no claim is pending. One at a time keeps the reconcile simple.
  const [claimingLeadId, setClaimingLeadId] = useState<string | null>(null);
  // The cleanup for an in-flight post-claim refetch, so a tab switch before it
  // resolves can cancel it (otherwise its stale resolve could overwrite the new
  // tab's leads). Held in a ref because it lives outside React's render data.
  const claimRefetchCleanup = useRef<(() => void) | null>(null);
  // A non-destructive claim error: the list stays intact and the row's button
  // re-enables. Cleared on the next claim attempt or tab switch.
  const [claimErrorMessage, setClaimErrorMessage] = useState<string | null>(
    null,
  );

  // Resolve the tenant once, for the product-line registry (the row labels).
  const loadTenant = useCallback(() => {
    setTenantLoad({ kind: "loading" });
    let isActive = true;
    listTenants()
      .then((tenants) => {
        if (!isActive) {
          return;
        }
        const tenant = tenants.find((candidate) => candidate.slug === tenantSlug);
        setTenantLoad(
          tenant === undefined
            ? { kind: "not-found" }
            : { kind: "loaded", tenant },
        );
      })
      .catch(() => {
        if (isActive) {
          setTenantLoad({ kind: "error" });
        }
      });
    return () => {
      isActive = false;
    };
  }, [tenantSlug]);

  useEffect(() => loadTenant(), [loadTenant]);

  // Fetch the leads for one tab. The queue tab passes `unassigned=true`. Returns
  // the cleanup that ignores a stale resolve when the tab changes mid-flight.
  const loadLeads = useCallback((tab: LeadsTab) => {
    setLeadsLoad({ kind: "loading" });
    let isActive = true;
    listLeads(tab === "queue")
      .then((leads) => {
        if (isActive) {
          setLeadsLoad({ kind: "loaded", leads });
        }
      })
      .catch(() => {
        if (isActive) {
          setLeadsLoad({ kind: "error" });
        }
      });
    return () => {
      isActive = false;
    };
  }, []);

  // Refetch whenever the active tab changes (and on first mount). Cancel any
  // in-flight post-claim refetch first — this fetch supersedes it, so its stale
  // resolve must not overwrite the freshly loaded tab.
  useEffect(() => {
    claimRefetchCleanup.current?.();
    claimRefetchCleanup.current = null;
    return loadLeads(activeTab);
  }, [activeTab, loadLeads]);

  const selectTab = (tab: LeadsTab) => {
    setClaimErrorMessage(null);
    setActiveTab(tab);
  };

  // Claim one lead, then reconcile by refetching the active tab: the claimed lead
  // leaves the queue, and the All-tab row flips to Working + owner. A failure
  // surfaces a non-destructive inline error and re-enables the row's button — the
  // list (and its rows) stay put.
  const claimLeadById = (leadId: string) => {
    setClaimErrorMessage(null);
    setClaimingLeadId(leadId);
    claimLead(leadId)
      .then(() => {
        // Track this refetch's cleanup so a tab switch before it resolves can
        // cancel it (the tab-change effect calls the stored cleanup).
        claimRefetchCleanup.current = loadLeads(activeTab);
      })
      .catch(() => {
        setClaimErrorMessage(
          "We couldn't claim that lead — it may have just been claimed by someone else. Please try again.",
        );
      })
      .finally(() => {
        setClaimingLeadId(null);
      });
  };

  // ---- Tenant resolution states (block the whole page; need labels first) ----

  if (tenantLoad.kind === "loading") {
    return (
      <div id="leads-list-page" className="leads-list-page">
        <LeadsListHeader canCreateLeads={canCreateLeads} />
        <p
          id="leads-list-loading"
          className="leads-list-status"
          role="status"
          aria-live="polite"
        >
          Loading…
        </p>
      </div>
    );
  }

  if (tenantLoad.kind === "error") {
    return (
      <div id="leads-list-page" className="leads-list-page">
        <LeadsListHeader canCreateLeads={canCreateLeads} />
        <div id="leads-list-error" className="leads-list-error">
          <p
            id="leads-list-error-message"
            className="leads-list-status"
            role="status"
            aria-live="polite"
          >
            We couldn't load your leads. Please try again.
          </p>
          <Button
            id="leads-list-error-retry-button"
            variant="tonal"
            onClick={loadTenant}
          >
            Retry
          </Button>
        </div>
      </div>
    );
  }

  if (tenantLoad.kind === "not-found") {
    return (
      <div id="leads-list-page" className="leads-list-page">
        <LeadsListHeader canCreateLeads={canCreateLeads} />
        <p id="leads-list-not-found" className="leads-list-status" role="status">
          We couldn't find your agency. Leads aren't available here.
        </p>
      </div>
    );
  }

  // ---- Loaded tenant: tabs + the active tab's body ----

  return (
    <div id="leads-list-page" className="leads-list-page">
      <LeadsListHeader canCreateLeads={canCreateLeads} />
      <LeadsTabs
        activeTab={activeTab}
        onSelectTab={selectTab}
        leadsLoad={leadsLoad}
      />
      <LeadsTabBody
        activeTab={activeTab}
        leadsLoad={leadsLoad}
        productLines={tenantLoad.tenant.product_lines}
        canCreateLeads={canCreateLeads}
        canClaimLeads={canClaimLeads}
        claimingLeadId={claimingLeadId}
        claimErrorMessage={claimErrorMessage}
        onRetry={() => loadLeads(activeTab)}
        onClaim={claimLeadById}
      />
    </div>
  );
}

// ---- Tabs: an ARIA tablist with a --primary active marker + per-tab count ----

/** The two tabs in fixed order; the count comes from the loaded leads when the
 *  matching tab is active (we only ever hold one tab's leads at a time). */
const TAB_DEFINITIONS: { tab: LeadsTab; label: string }[] = [
  { tab: "all", label: "All leads" },
  { tab: "queue", label: "Unassigned queue" },
];

function LeadsTabs({
  activeTab,
  onSelectTab,
  leadsLoad,
}: {
  activeTab: LeadsTab;
  onSelectTab: (tab: LeadsTab) => void;
  leadsLoad: LeadsLoadState;
}) {
  // The count is only known for the active tab (the one whose leads are loaded);
  // the inactive tab shows no number until it is opened.
  const activeCount =
    leadsLoad.kind === "loaded" ? leadsLoad.leads.length : null;

  // WAI-ARIA roving: Left/Right (and Home/End) move selection + focus between
  // tabs, wrapping at the ends. Selecting a tab refetches via onSelectTab.
  const onTabKeyDown = (
    event: KeyboardEvent<HTMLButtonElement>,
    currentIndex: number,
  ) => {
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") {
      nextIndex = (currentIndex + 1) % TAB_DEFINITIONS.length;
    } else if (event.key === "ArrowLeft") {
      nextIndex =
        (currentIndex - 1 + TAB_DEFINITIONS.length) % TAB_DEFINITIONS.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = TAB_DEFINITIONS.length - 1;
    }
    if (nextIndex === null) {
      return;
    }
    event.preventDefault();
    const nextTab = TAB_DEFINITIONS[nextIndex].tab;
    onSelectTab(nextTab);
    document.getElementById(`leads-list-tab-${nextTab}`)?.focus();
  };

  return (
    <div
      id="leads-list-tablist"
      className="leads-list-tablist"
      role="tablist"
      aria-label="Lead views"
    >
      {TAB_DEFINITIONS.map(({ tab, label }, index) => {
        const isActive = tab === activeTab;
        return (
          <button
            key={tab}
            id={`leads-list-tab-${tab}`}
            className={
              isActive
                ? "leads-list-tab leads-list-tab-active"
                : "leads-list-tab"
            }
            type="button"
            role="tab"
            aria-selected={isActive}
            aria-controls="leads-list-tabpanel"
            tabIndex={isActive ? 0 : -1}
            onClick={() => onSelectTab(tab)}
            onKeyDown={(event) => onTabKeyDown(event, index)}
          >
            <span id={`leads-list-tab-${tab}-label`} className="leads-list-tab-label">
              {label}
            </span>
            {isActive && activeCount !== null && (
              <span
                id={`leads-list-tab-${tab}-count`}
                className="leads-list-tab-count"
              >
                {activeCount}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

// ---- The active tab's body: loading / error / empty / the table ----

function LeadsTabBody({
  activeTab,
  leadsLoad,
  productLines,
  canCreateLeads,
  canClaimLeads,
  claimingLeadId,
  claimErrorMessage,
  onRetry,
  onClaim,
}: {
  activeTab: LeadsTab;
  leadsLoad: LeadsLoadState;
  productLines: ProductLine[];
  canCreateLeads: boolean;
  canClaimLeads: boolean;
  claimingLeadId: string | null;
  claimErrorMessage: string | null;
  onRetry: () => void;
  onClaim: (leadId: string) => void;
}) {
  const panelProperties = {
    id: "leads-list-tabpanel",
    className: "leads-list-tabpanel",
    role: "tabpanel" as const,
    "aria-labelledby": `leads-list-tab-${activeTab}`,
  };

  if (leadsLoad.kind === "loading") {
    return (
      <div {...panelProperties}>
        <p
          id="leads-list-leads-loading"
          className="leads-list-status"
          role="status"
          aria-live="polite"
        >
          Loading leads…
        </p>
      </div>
    );
  }

  if (leadsLoad.kind === "error") {
    return (
      <div {...panelProperties}>
        <div id="leads-list-leads-error" className="leads-list-error">
          <p
            id="leads-list-leads-error-message"
            className="leads-list-status"
            role="status"
            aria-live="polite"
          >
            We couldn't load your leads. Please try again.
          </p>
          <Button
            id="leads-list-leads-error-retry-button"
            variant="tonal"
            onClick={onRetry}
          >
            Retry
          </Button>
        </div>
      </div>
    );
  }

  if (leadsLoad.leads.length === 0) {
    return (
      <div {...panelProperties}>
        <LeadsEmptyState activeTab={activeTab} canCreateLeads={canCreateLeads} />
      </div>
    );
  }

  return (
    <div {...panelProperties}>
      {claimErrorMessage !== null && (
        <p
          id="leads-list-claim-error"
          className="leads-list-claim-error"
          role="alert"
        >
          {claimErrorMessage}
        </p>
      )}
      <LeadsTable
        leads={leadsLoad.leads}
        productLines={productLines}
        canClaimLeads={canClaimLeads}
        claimingLeadId={claimingLeadId}
        onClaim={onClaim}
      />
    </div>
  );
}

// ---- Empty states: tab-specific Guide §5 framed notes ----

function LeadsEmptyState({
  activeTab,
  canCreateLeads,
}: {
  activeTab: LeadsTab;
  canCreateLeads: boolean;
}) {
  if (activeTab === "queue") {
    return (
      <div id="leads-list-empty-queue" className="leads-list-empty" role="status">
        <span
          id="leads-list-empty-queue-icon"
          className="leads-list-empty-icon"
          aria-hidden="true"
        >
          <CheckCircle width={28} height={28} />
        </span>
        <p id="leads-list-empty-queue-message" className="leads-list-empty-message">
          The queue is clear — every new lead has been claimed.
        </p>
      </div>
    );
  }

  return (
    <div id="leads-list-empty-all" className="leads-list-empty" role="status">
      <span
        id="leads-list-empty-all-icon"
        className="leads-list-empty-icon"
        aria-hidden="true"
      >
        <EmptyPage width={28} height={28} />
      </span>
      <p id="leads-list-empty-all-message" className="leads-list-empty-message">
        No leads yet.
      </p>
      {canCreateLeads && (
        <ButtonLink
          id="leads-list-empty-new-lead-link"
          variant="filled"
          to="/app/leads/new"
        >
          New lead
        </ButtonLink>
      )}
    </div>
  );
}

// ---- The dense data table (Guide §5): Stamp-type heads, hairline dividers ----

const COLUMN_HEADS = [
  { key: "name", label: "Name" },
  { key: "status", label: "Status" },
  { key: "product-lines", label: "Coverage" },
  { key: "age-band", label: "Age band" },
  { key: "zip-code", label: "ZIP" },
  { key: "source", label: "Source" },
  { key: "owner", label: "Owner" },
  { key: "created", label: "Created" },
  { key: "claim", label: "" },
];

function LeadsTable({
  leads,
  productLines,
  canClaimLeads,
  claimingLeadId,
  onClaim,
}: {
  leads: MaskedLead[];
  productLines: ProductLine[];
  canClaimLeads: boolean;
  claimingLeadId: string | null;
  onClaim: (leadId: string) => void;
}) {
  return (
    <table id="leads-list-table" className="leads-list-table">
      <thead id="leads-list-table-head">
        <tr id="leads-list-table-head-row">
          {COLUMN_HEADS.map((column) => (
            <th
              key={column.key}
              id={`leads-list-head-${column.key}`}
              className="leads-list-head"
              scope="col"
            >
              {column.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody id="leads-list-table-body">
        {leads.map((lead) => (
          <LeadRow
            key={lead.id}
            lead={lead}
            productLines={productLines}
            canClaimLeads={canClaimLeads}
            isClaiming={claimingLeadId === lead.id}
            onClaim={onClaim}
          />
        ))}
      </tbody>
    </table>
  );
}

function LeadRow({
  lead,
  productLines,
  canClaimLeads,
  isClaiming,
  onClaim,
}: {
  lead: MaskedLead;
  productLines: ProductLine[];
  canClaimLeads: boolean;
  isClaiming: boolean;
  onClaim: (leadId: string) => void;
}) {
  const statusStamp = leadStatusStamp(lead.status);

  return (
    <tr id={`leads-list-row-${lead.id}`} className="leads-list-row">
      <td id={`leads-list-row-${lead.id}-name`} className="leads-list-cell">
        {/* The name links to the lead detail page (Epic 21 now owns the route). */}
        <Link
          id={`leads-list-row-${lead.id}-name-link`}
          className="leads-list-name"
          to={`/app/leads/${lead.id}`}
        >
          {lead.first_name} {lead.last_name}
        </Link>
        {isUnresolvedDuplicate(lead) && (
          <StampTag
            id={`leads-list-row-${lead.id}-duplicate`}
            status="warning"
          >
            Possible duplicate
          </StampTag>
        )}
      </td>
      <td id={`leads-list-row-${lead.id}-status`} className="leads-list-cell">
        <StampTag
          id={`leads-list-row-${lead.id}-status-stamp`}
          status={statusStamp.status}
        >
          {statusStamp.label}
        </StampTag>
      </td>
      <td
        id={`leads-list-row-${lead.id}-product-lines`}
        className="leads-list-cell"
      >
        {leadProductLineLabels(lead, productLines)}
      </td>
      <td id={`leads-list-row-${lead.id}-age-band`} className="leads-list-cell">
        {lead.age_band}
      </td>
      <td id={`leads-list-row-${lead.id}-zip-code`} className="leads-list-cell">
        {lead.zip_code}
      </td>
      <td id={`leads-list-row-${lead.id}-source`} className="leads-list-cell">
        {leadSourceLabel(lead.lead_source)}
      </td>
      <td id={`leads-list-row-${lead.id}-owner`} className="leads-list-cell">
        {leadOwnerLabel(lead.owner_username)}
      </td>
      <td id={`leads-list-row-${lead.id}-created`} className="leads-list-cell">
        {leadCreatedDate(lead.created_at)}
      </td>
      <td id={`leads-list-row-${lead.id}-claim`} className="leads-list-cell">
        {canClaimLeads && isClaimable(lead) && (
          <Button
            id={`leads-list-row-${lead.id}-claim-button`}
            variant="tonal"
            isPending={isClaiming}
            onClick={() => onClaim(lead.id)}
          >
            Claim
          </Button>
        )}
      </td>
    </tr>
  );
}
