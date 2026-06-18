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
