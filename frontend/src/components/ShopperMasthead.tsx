import TenantSealMark from "./TenantSealMark.tsx";
import SurfaceToggle from "./SurfaceToggle.tsx";

interface ShopperMastheadProperties {
  /** The tenant slug — selects the seal art and scopes the brand rule. */
  tenantSlug: string;
  /** The tenant's display name — the consumer wordmark. */
  tenantName: string;
  /** Whether a signed-in workspace session exists — gates the surface toggle
   *  (Epic 24). A signed-out shopper browses with no toggle (no workspace to
   *  return to). Kept a prop so this component stays pure (no `useSession`). */
  isSignedIn: boolean;
}

// The public Shopper masthead (the consumer storefront chrome). Tenant-LED, not
// product-led: the tenant's seal + name ARE the wordmark, over the tenant's 3px
// brand letterhead rule. It deliberately carries NONE of the agent workspace's
// chrome — no PolicyFlow wordmark, no role switcher, no left nav, no DEMO SESSION
// stamp, no help/bell. The visitor here is a prospective buyer, not staff.
//
// It reuses the masthead visual language persona-free: the `--surface-1` paper
// panel, the `--outline` hairline, the seal mark, and the `.masthead-letterhead-rule`
// idiom whose `--primary` resolves from the `[data-tenant]` scope the Shopper page
// sets (useTenantTheming). Its own paper-panel structure lives in shopper.css.
//
// Epic 24 mounts the surface toggle ("← Back to the agent workspace") + its
// ExplainerPopover at the right end of the bar — the only control on the consumer
// masthead, and only when the visitor has a signed-in workspace session to return
// to (a signed-out shopper browses with no toggle). It is right-aligned via the
// `.shopper-masthead-toggle` margin-left:auto (styles/surface-toggle.css).
export default function ShopperMasthead({
  tenantSlug,
  tenantName,
  isSignedIn,
}: ShopperMastheadProperties) {
  return (
    <header id="shopper-masthead" className="shopper-masthead">
      <div id="shopper-masthead-bar" className="shopper-masthead-bar">
        <TenantSealMark id="shopper-masthead-seal" slug={tenantSlug} />
        <span id="shopper-masthead-wordmark" className="shopper-masthead-wordmark">
          {tenantName}
        </span>
        {isSignedIn && (
          <div
            id="shopper-masthead-toggle"
            className="shopper-masthead-toggle"
          >
            <SurfaceToggle
              id="shopper-masthead-surface-toggle"
              to="/app"
              label="Back to the agent workspace"
              direction="back"
            />
          </div>
        )}
      </div>
      <div
        id="shopper-masthead-letterhead-rule"
        className="masthead-letterhead-rule"
        aria-hidden="true"
      />
    </header>
  );
}
