import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import Button from "../components/Button.tsx";
import Card from "../components/Card.tsx";
import PageLayout from "../components/PageLayout.tsx";
import TenantSealMark from "../components/TenantSealMark.tsx";
import { listTenants } from "../api";
import type { Tenant } from "../api";
import { useSession } from "../session";
import { WHY_TWO_TENANTS, getTenantBlurb } from "./tenantEditorial.ts";

// Tenant-selection route (`/select-tenant`) — the real branded screen. Above the
// cards a "Why two tenants?" block frames the demo (two agencies on one platform,
// neither able to see the other's records). Each tenant renders as a branded
// Epic 8 Card: seal mark + specialization blurb, with a Filled footer button that
// passwordlessly assumes the Agent persona and routes into the guarded `/app`
// zone. Per-card branding rides the Guide's `[data-tenant]` token ramp — each
// card's wrapping `<li>` carries `data-tenant`, so `--primary` cascades in and the
// Filled button + the 3px letterhead rule paint that tenant's brand automatically
// (terracotta for Sunshine, petrol for Florida) with no per-tenant color code.
//
// Entry is the agent workspace only (select -> assume Agent -> `/app`); the
// Shopper surface and the surface toggle are Epics 23/24.

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
          Choose a demo tenant
        </h1>

        {/* "Why two tenants?" — stable ids so Epic 19 can anchor its explainer
            popover here; Epic 15 renders no placeholder of its own. */}
        <section
          id="select-tenant-why"
          className="select-tenant-why"
          aria-labelledby="select-tenant-why-heading"
        >
          <h2
            id="select-tenant-why-heading"
            className="select-tenant-why-heading"
          >
            Why two tenants?
          </h2>
          <p id="select-tenant-why-body" className="select-tenant-why-body">
            {WHY_TWO_TENANTS}
          </p>
        </section>

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
          <ul id="select-tenant-card-list" className="select-tenant-card-list">
            {loadState.tenants.map((tenant) => {
              const cardId = `select-tenant-card-${tenant.slug}`;
              return (
                // `data-tenant` scopes the Guide's [data-tenant] ramp to this
                // card, so --primary cascades in and the brand paints itself.
                <li
                  id={`select-tenant-card-item-${tenant.slug}`}
                  key={tenant.slug}
                  className="select-tenant-card-item"
                  data-tenant={tenant.slug}
                >
                  <Card
                    id={cardId}
                    title={tenant.display_name}
                    footer={
                      <Button
                        id={`${cardId}-enter-button`}
                        variant="filled"
                        isPending={assumingSlug === tenant.slug}
                        disabled={isAssuming}
                        onClick={() => handleSelectTenant(tenant)}
                      >
                        Enter the agent workspace →
                      </Button>
                    }
                  >
                    <TenantSealMark
                      id={`${cardId}-seal`}
                      slug={tenant.slug}
                    />
                    <p id={`${cardId}-blurb`} className="select-tenant-blurb">
                      {getTenantBlurb(tenant.slug)}
                    </p>
                  </Card>
                </li>
              );
            })}
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
