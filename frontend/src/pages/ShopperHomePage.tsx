import Card from "../components/Card.tsx";
import ShopperIntakeForm from "./ShopperIntakeForm.tsx";
import { getTenantShopperHero } from "./tenantEditorial.ts";
import type { Tenant } from "../api";

interface ShopperHomePageProperties {
  /** The loaded tenant — its slug selects the per-tenant consumer hero copy and
   *  its product lines drive the intake form's coverage-interest choices. Threaded
   *  down from ShopperSitePage so the form needs no fetch of its own. */
  tenant: Tenant;
}

// The public buyer-home — what a prospective customer lands on when they visit a
// tenant's Shopper site. A per-tenant consumer hero (each agency's own
// in-character pitch) over the real public intake form (Epic 18), which replaced
// the earlier "quote coming soon" placeholder behind the `shopper-home-quote-card`
// seam. The form lives inside the paper Card shell, submits to the public intake
// endpoint, and carries the tenant down so it knows the slug + product lines.
export default function ShopperHomePage({ tenant }: ShopperHomePageProperties) {
  const hero = getTenantShopperHero(tenant.slug);

  return (
    <div id="shopper-home-content" className="shopper-home-content">
      <h1 id="shopper-home-hero-title" className="shopper-home-hero-title">
        {hero.title}
      </h1>
      <p id="shopper-home-hero-body" className="shopper-home-hero-body">
        {hero.body}
      </p>

      {/* The real public intake form, behind the seam P1.7 replaced. */}
      <Card id="shopper-home-quote-card" title="Get your free quote">
        <p id="shopper-home-quote-body" className="shopper-home-quote-body">
          Tell us a little about yourself and a licensed agent will put together
          your options — no obligation.
        </p>
        <ShopperIntakeForm tenant={tenant} />
      </Card>
    </div>
  );
}
