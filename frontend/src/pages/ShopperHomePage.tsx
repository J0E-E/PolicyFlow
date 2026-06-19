import Card from "../components/Card.tsx";
import { getTenantShopperHero } from "./tenantEditorial.ts";

interface ShopperHomePageProperties {
  /** The tenant slug — selects the per-tenant consumer hero copy. */
  tenantSlug: string;
}

// The public buyer-home placeholder — what a prospective customer lands on when
// they visit a tenant's Shopper site. A per-tenant consumer hero (each agency's
// own in-character pitch) over an in-character "Get your free quote — coming soon"
// card. No intake form, prefill, or abuse controls yet — those are P1.7, which
// swaps its real public intake form in behind the `shopper-home-quote-card` seam.
export default function ShopperHomePage({
  tenantSlug,
}: ShopperHomePageProperties) {
  const hero = getTenantShopperHero(tenantSlug);

  return (
    <div id="shopper-home-content" className="shopper-home-content">
      <h1 id="shopper-home-hero-title" className="shopper-home-hero-title">
        {hero.title}
      </h1>
      <p id="shopper-home-hero-body" className="shopper-home-hero-body">
        {hero.body}
      </p>

      {/* The seam P1.7 replaces with the real public intake form. */}
      <Card id="shopper-home-quote-card" title="Get your free quote">
        <p id="shopper-home-quote-body" className="shopper-home-quote-body">
          Tell us a little about yourself and we'll put together your options — no
          obligation. Our online quote form is arriving shortly.
        </p>
      </Card>
    </div>
  );
}
