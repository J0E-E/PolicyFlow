// Frontend editorial copy for the select-tenant screen, keyed by tenant slug.
// Kept JSX-free in its own module — a clean Vite fast-refresh boundary, mirroring
// the `api/`, `session/`, and `buttonVariants` splits. The tenant list itself
// (slug, display_name, brand color) comes from `GET /api/tenants`; this file
// holds only the human-written specialization blurbs that the registry does not
// carry, so a copy edit never touches the page component.

/** The specialization blurb shown under a tenant's name, keyed by slug. */
const TENANT_BLURBS: Record<string, string> = {
  "sunshine-senior-benefits":
    "Medicare and senior-market coverage — Medicare Advantage, supplements, and final-expense plans for the 65-and-over community.",
  "florida-family-planning":
    "Life and protection planning for growing households — term life, juvenile, and income-protection products built around families.",
};

/** The specialization blurb for a tenant, or an empty string if a slug has no
 *  editorial copy yet (so a new tenant renders a nameless-but-safe card rather
 *  than crashing or showing `undefined`). */
export function getTenantBlurb(slug: string): string {
  return TENANT_BLURBS[slug] ?? "";
}

/** The "Why two tenants?" block copy — the differentiation + isolation proof
 *  that motivates the two-agency demo. Shown once above the tenant cards. */
export const WHY_TWO_TENANTS =
  "Two separate insurance agencies run on one PolicyFlow platform — different brands, products, and pipelines on the very same screens, yet neither can ever see the other's records. Pick either to step in; switching between them later is how the demo proves that isolation.";

// ---- Shopper site (the public, tenant-branded consumer storefront) ----

/** The consumer hero copy for a tenant's public Shopper home — the in-character
 *  buyer-facing pitch, written in each agency's own voice (distinct per tenant).
 *  Keyed by slug so a copy edit never touches the page component. */
interface ShopperHero {
  /** The buyer-facing hero headline. */
  title: string;
  /** The supporting line under the headline. */
  body: string;
}

const TENANT_SHOPPER_HEROES: Record<string, ShopperHero> = {
  "sunshine-senior-benefits": {
    title: "Medicare coverage that fits your life",
    body: "Compare Medicare Advantage, supplement, and final-expense plans built for the 65-and-over community.",
  },
  "florida-family-planning": {
    title: "Protect the people who count on you",
    body: "Term life, juvenile, and income-protection plans built around growing families.",
  },
};

/** The consumer hero for a tenant's Shopper home, or a safe neutral fallback so a
 *  new tenant renders a friendly hero rather than showing `undefined`. */
export function getTenantShopperHero(slug: string): ShopperHero {
  return (
    TENANT_SHOPPER_HEROES[slug] ?? {
      title: "Coverage built around you",
      body: "Tell us a little about yourself and we'll help you find the right plan.",
    }
  );
}
