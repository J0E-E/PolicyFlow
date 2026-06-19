import type { ReactNode } from "react";
import ShopperMasthead from "./ShopperMasthead.tsx";
import Footer from "./Footer.tsx";

interface ShopperLayoutProperties {
  /** The tenant slug — forwarded to the consumer masthead's seal + brand rule. */
  tenantSlug: string;
  /** The tenant's display name — the consumer wordmark. */
  tenantName: string;
  /** The routed buyer-home content rendered into the `<main>`. */
  children: ReactNode;
}

// The public Shopper surface frame: the consumer masthead full-width on top, a
// centered scrolling `<main>`, and the shared Footer pinned to the foot of a
// sticky-footer flex column (mirrors AppShell / PageLayout). Presentational only —
// the routed page (ShopperHomePage) owns its own content; this just supplies the
// branded consumer chrome around it (React philosophy / Guide §4 layout).
//
// Unlike AppShell there is no left-nav rail and no role switcher: the Shopper is
// unauthenticated and persona-free, so the frame is simply masthead -> main ->
// footer, giving the natural landmark focus order (Guide §7).
export default function ShopperLayout({
  tenantSlug,
  tenantName,
  children,
}: ShopperLayoutProperties) {
  return (
    <div id="shopper-shell" className="shopper-shell">
      <ShopperMasthead tenantSlug={tenantSlug} tenantName={tenantName} />
      <main id="shopper-main" className="shopper-main">
        {children}
      </main>
      <Footer />
    </div>
  );
}
