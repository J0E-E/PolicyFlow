import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import Button from "../components/Button.tsx";
import PageLayout from "../components/PageLayout.tsx";
import ShopperLayout from "../components/ShopperLayout.tsx";
import ShopperHomePage from "./ShopperHomePage.tsx";
import { useTenantTheming } from "../components/useTenantTheming.ts";
import { useSession } from "../session";
import { listTenants } from "../api";
import type { Tenant } from "../api";

// The public Shopper route (`/site/:slug`) — the consumer storefront where the
// visitor plays the prospective buyer. It renders purely from the slug in the URL:
// the surface is unauthenticated and persona-free, so there is no session check
// and no redirect — it changes *surface*, not identity (Epic 24 adds the toggle).
//
// The slug both themes the surface (useTenantTheming sets `data-tenant` on the
// document root, so the brand paints itself) and is validated against the public
// tenant list: `listTenants()` resolves the tenant's display name AND proves the
// slug is real. The state machine mirrors SelectTenantPage's LoadState idiom and
// the Epic 15 robust-states pattern — a loading skeleton, a fetch error + Retry,
// and a friendly not-found for an unknown slug (linking back to /select-tenant).

// What the page is currently doing — so the loading / error / not-found / branded
// states each render exactly once and never overlap.
type LoadState =
  | { kind: "loading" }
  | { kind: "loaded"; tenants: Tenant[] }
  | { kind: "error" };

export default function ShopperSitePage() {
  const { slug } = useParams<{ slug: string }>();
  const tenantSlug = slug ?? null;

  // Theme from the slug alone (persona-free); cleaned up on unmount so toggling
  // back to /app re-themes cleanly (Epic 24).
  useTenantTheming(tenantSlug);

  // The storefront stays public — there is no redirect (Epic 23's unauthenticated
  // design is preserved). The session status only gates the surface toggle: a
  // signed-in visitor came from the workspace and sees "← Back to the agent
  // workspace"; a signed-out shopper browses freely with no toggle (Epic 24).
  const { status } = useSession();
  const isSignedIn = status === "signed-in";

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

  useEffect(() => loadTenants(), [loadTenants]);

  // Loading — a quiet neutral skeleton while the tenant list resolves.
  if (loadState.kind === "loading") {
    return (
      <PageLayout pageId="shopper-loading">
        <div
          id="shopper-loading-skeleton"
          className="shopper-state"
          role="status"
          aria-live="polite"
        >
          <p
            id="shopper-loading-message"
            className="shopper-state-message"
          >
            Loading…
          </p>
        </div>
      </PageLayout>
    );
  }

  // Error — the fetch failed; offer a Retry (the Epic 15 error+retry path).
  if (loadState.kind === "error") {
    return (
      <PageLayout pageId="shopper-error">
        <div id="shopper-error" className="shopper-state">
          <h1 id="shopper-error-title" className="shopper-state-title">
            Something went wrong
          </h1>
          <p
            id="shopper-error-message"
            className="shopper-state-message"
            role="status"
            aria-live="polite"
          >
            We couldn't load this site. Please try again.
          </p>
          <Button
            id="shopper-error-retry-button"
            variant="tonal"
            onClick={loadTenants}
          >
            Retry
          </Button>
        </div>
      </PageLayout>
    );
  }

  const tenant = loadState.tenants.find(
    (candidate) => candidate.slug === tenantSlug,
  );

  // Not found — a real tenant list loaded but no slug matched; a friendly note
  // back to the tenant picker (no agent chrome, neutral PageLayout).
  if (tenant === undefined) {
    return (
      <PageLayout pageId="shopper-not-found">
        <div id="shopper-not-found" className="shopper-state">
          <h1
            id="shopper-not-found-title"
            className="shopper-state-title"
          >
            We couldn't find that site
          </h1>
          <p
            id="shopper-not-found-message"
            className="shopper-state-message"
          >
            This link doesn't match any of our agencies. Choose one to get
            started.
          </p>
          <Link
            id="shopper-not-found-link"
            className="text-link"
            to="/select-tenant"
          >
            Browse our agencies
          </Link>
        </div>
      </PageLayout>
    );
  }

  // Branded shell — a valid slug; render the consumer chrome + buyer home.
  return (
    <ShopperLayout
      tenantSlug={tenant.slug}
      tenantName={tenant.display_name}
      isSignedIn={isSignedIn}
    >
      <ShopperHomePage tenant={tenant} />
    </ShopperLayout>
  );
}
