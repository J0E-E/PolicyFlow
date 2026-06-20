import { useCallback, useEffect, useState } from "react";
import Button from "../components/Button.tsx";
import AgentIntakeForm from "./AgentIntakeForm.tsx";
import { useCapability, useSession } from "../session";
import { listTenants } from "../api";
import type { Tenant } from "../api";

// The authenticated agent intake page at `/app/leads/new` (Epic 19). It renders
// INSIDE the AppShell chrome (masthead + left nav, supplied by
// RequireSession → AppShell), so it carries its OWN Guide §5 page header (a
// "New lead" Besley headline + the Oxford double rule) rather than the
// unauthenticated PageLayout wordmark frame.
//
// Two gates stack before the form shows:
//   1. Capability — the page needs `create_edit_records`; a Read-Only agent sees
//      a short denied notice under the header, never the form.
//   2. Tenant — the form needs the agent's tenant for the product-line checkboxes
//      and the prefills, so the page resolves it from `listTenants()` filtered to
//      the session's `tenant_slug`, mirroring ShopperSitePage's LoadState idiom
//      (a loading skeleton, an error + Retry, a defensive not-found).
// The entry point (the "Leads" nav + a "New lead" link) is Epic 20's; this epic
// ships the route only, reachable by URL.

// What the tenant resolution is currently doing — so the loading / error /
// not-found / loaded states each render exactly once and never overlap.
type LoadState =
  | { kind: "loading" }
  | { kind: "loaded"; tenants: Tenant[] }
  | { kind: "error" };

// The page header is the same on every branch (denied, loading, error, loaded),
// so it lives in one place and wraps the branch-specific body.
function AgentIntakeHeader() {
  return (
    <header id="agent-intake-header" className="agent-intake-header">
      <h1 id="agent-intake-title" className="agent-intake-title">
        New lead
      </h1>
      <hr id="agent-intake-rule" className="oxford-double-rule" />
    </header>
  );
}

export default function AgentIntakePage() {
  const { identity } = useSession();
  const canCreateLeads = useCapability("create_edit_records");
  const tenantSlug = identity?.user.tenant_slug ?? null;

  const [loadState, setLoadState] = useState<LoadState>({ kind: "loading" });

  const loadTenants = useCallback(() => {
    setLoadState({ kind: "loading" });
    let isActive = true;
    listTenants()
      .then((tenants) => {
        if (isActive) {
          setLoadState({ kind: "loaded", tenants });
        }
      })
      .catch(() => {
        if (isActive) {
          setLoadState({ kind: "error" });
        }
      });
    return () => {
      isActive = false;
    };
  }, []);

  // Only resolve the tenant when the agent may actually create leads — a
  // Read-Only visitor sees the denied notice, so there is nothing to load for.
  useEffect(() => {
    if (!canCreateLeads) {
      return;
    }
    return loadTenants();
  }, [canCreateLeads, loadTenants]);

  // Capability gate — a Read-Only agent gets a short denied notice, not the form.
  if (!canCreateLeads) {
    return (
      <div id="agent-intake-page" className="agent-intake-page">
        <AgentIntakeHeader />
        <p
          id="agent-intake-denied"
          className="agent-intake-denied"
          role="status"
        >
          You don't have permission to create leads.
        </p>
      </div>
    );
  }

  // Loading — a quiet status line while the tenant list resolves.
  if (loadState.kind === "loading") {
    return (
      <div id="agent-intake-page" className="agent-intake-page">
        <AgentIntakeHeader />
        <p
          id="agent-intake-loading"
          className="agent-intake-status"
          role="status"
          aria-live="polite"
        >
          Loading…
        </p>
      </div>
    );
  }

  // Error — the fetch failed; offer a Retry (mirrors ShopperSitePage).
  if (loadState.kind === "error") {
    return (
      <div id="agent-intake-page" className="agent-intake-page">
        <AgentIntakeHeader />
        <div id="agent-intake-error" className="agent-intake-error">
          <p
            id="agent-intake-error-message"
            className="agent-intake-status"
            role="status"
            aria-live="polite"
          >
            We couldn't load the form. Please try again.
          </p>
          <Button
            id="agent-intake-error-retry-button"
            variant="tonal"
            onClick={loadTenants}
          >
            Retry
          </Button>
        </div>
      </div>
    );
  }

  const tenant = loadState.tenants.find(
    (candidate) => candidate.slug === tenantSlug,
  );

  // Not found — a defensive guard: the agent's tenant slug matched no tenant in
  // the list (a tenantless Platform Admin, or registry drift).
  if (tenant === undefined) {
    return (
      <div id="agent-intake-page" className="agent-intake-page">
        <AgentIntakeHeader />
        <p
          id="agent-intake-not-found"
          className="agent-intake-status"
          role="status"
        >
          We couldn't find your agency. Lead creation isn't available here.
        </p>
      </div>
    );
  }

  // Loaded + permitted — render the intake form for the agent's tenant.
  return (
    <div id="agent-intake-page" className="agent-intake-page">
      <AgentIntakeHeader />
      <AgentIntakeForm tenant={tenant} />
    </div>
  );
}
