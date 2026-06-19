import TenantSealMark from "./TenantSealMark.tsx";

interface ShopperMastheadProperties {
  /** The tenant slug — selects the seal art and scopes the brand rule. */
  tenantSlug: string;
  /** The tenant's display name — the consumer wordmark. */
  tenantName: string;
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
// ExplainerPopover here; this component is kept clean of demo chrome so that
// toggle is the only control that ever lands in the consumer masthead.
export default function ShopperMasthead({
  tenantSlug,
  tenantName,
}: ShopperMastheadProperties) {
  return (
    <header id="shopper-masthead" className="shopper-masthead">
      <div id="shopper-masthead-bar" className="shopper-masthead-bar">
        <TenantSealMark id="shopper-masthead-seal" slug={tenantSlug} />
        <span id="shopper-masthead-wordmark" className="shopper-masthead-wordmark">
          {tenantName}
        </span>
      </div>
      <div
        id="shopper-masthead-letterhead-rule"
        className="masthead-letterhead-rule"
        aria-hidden="true"
      />
    </header>
  );
}
