import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import Button from "../components/Button.tsx";
import PageLayout from "../components/PageLayout.tsx";
import { listTenants } from "../api";
import type { Tenant } from "../api";
import { useSession } from "../session";

// Tenant-selection route (`/select-tenant`). The live walking-skeleton flow:
// fetch the public tenant list on mount, render each tenant as a focusable
// button, and on click passwordlessly assume the Agent persona for that tenant
// and route into the guarded `/app` zone. Un-branded — the tenant's brand color
// is not used yet (that is Epic 15); this slice proves select -> assume ->
// demo home end-to-end on the existing base styles.

// What the page is currently doing — so the loading / empty / error / pending /
// assume-error states each render exactly once and never overlap.
type LoadState =
  | { kind: "loading" }
  | { kind: "loaded"; tenants: Tenant[] }
  | { kind: "error" };

export default function SelectTenantPage() {
  const { assumePersona } = useSession();
  const navigate = useNavigate();

  const [loadState, setLoadState] = useState<LoadState>({ kind: "loading" });
  // The slug currently being signed in (disables the buttons), or null.
  const [assumingSlug, setAssumingSlug] = useState<string | null>(null);
  const [assumeError, setAssumeError] = useState<string | null>(null);

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

  useEffect(() => loadTenants(), [loadTenants]);

  async function handleSelectTenant(tenant: Tenant) {
    setAssumeError(null);
    setAssumingSlug(tenant.slug);
    try {
      await assumePersona(tenant.slug, "agent");
      navigate("/app");
    } catch {
      // Re-enable the controls and explain the failure in the page's own voice.
      setAssumingSlug(null);
      setAssumeError("Could not sign you in. Please try again.");
    }
  }

  const isAssuming = assumingSlug !== null;

  return (
    <PageLayout pageId="select-tenant">
      <div id="select-tenant-content" className="select-tenant-content">
        <h1 id="select-tenant-headline" className="select-tenant-headline">
          Select a tenant
        </h1>
        <p id="select-tenant-intro" className="select-tenant-intro">
          Pick a demo organization to step into. Selecting one signs you in as an
          Agent for that tenant.
        </p>

        {loadState.kind === "loading" && (
          <p
            id="select-tenant-loading"
            className="select-tenant-status"
            role="status"
            aria-live="polite"
          >
            Loading tenants…
          </p>
        )}

        {loadState.kind === "error" && (
          <div id="select-tenant-error" className="select-tenant-error">
            <p
              id="select-tenant-error-message"
              className="select-tenant-status"
              role="status"
              aria-live="polite"
            >
              Could not load tenants.
            </p>
            <Button
              id="select-tenant-retry-button"
              variant="tonal"
              onClick={loadTenants}
            >
              Retry
            </Button>
          </div>
        )}

        {loadState.kind === "loaded" && loadState.tenants.length === 0 && (
          <p
            id="select-tenant-empty"
            className="select-tenant-status"
            role="status"
            aria-live="polite"
          >
            No tenants are available.
          </p>
        )}

        {loadState.kind === "loaded" && loadState.tenants.length > 0 && (
          <ul id="select-tenant-card-list" className="tenant-card-list">
            {loadState.tenants.map((tenant) => (
              <li
                id={`select-tenant-card-item-${tenant.slug}`}
                key={tenant.slug}
                className="tenant-card-item"
              >
                <button
                  id={`select-tenant-card-${tenant.slug}`}
                  type="button"
                  className="tenant-card tenant-card-button"
                  onClick={() => handleSelectTenant(tenant)}
                  disabled={isAssuming}
                >
                  <span
                    id={`select-tenant-card-${tenant.slug}-name`}
                    className="tenant-card-name"
                  >
                    {tenant.display_name}
                  </span>
                  <span
                    id={`select-tenant-card-${tenant.slug}-note`}
                    className="tenant-card-note"
                  >
                    Sign in as an Agent for {tenant.display_name}.
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}

        {isAssuming && (
          <p
            id="select-tenant-pending"
            className="select-tenant-status"
            role="status"
            aria-live="polite"
          >
            Signing you in…
          </p>
        )}

        {assumeError !== null && (
          <p
            id="select-tenant-assume-error"
            className="select-tenant-status"
            role="status"
            aria-live="polite"
          >
            {assumeError}
          </p>
        )}

        <Link id="select-tenant-back-link" className="text-link" to="/">
          Back to landing
        </Link>
      </div>
    </PageLayout>
  );
}
