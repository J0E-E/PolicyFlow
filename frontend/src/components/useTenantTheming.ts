import { useEffect } from "react";

// Drives the Guide's tenant brand theming on the public Shopper surface from the
// route slug alone — the persona-free sibling of useIdentityTheming. The token
// layer (tokens.css) keys the tenant brand ramp off `[data-tenant="<slug>"]`, so
// setting that one attribute is enough to paint the consumer masthead's 3px
// letterhead rule and any `--primary`-derived chrome in the tenant's brand.
//
// The Shopper site is unauthenticated and persona-free: it changes *surface*, not
// identity, and carries no RBAC role. So this effect sets ONLY `data-tenant` and
// never touches `data-persona` (the [data-persona] accents + the Platform-Admin
// brand-drain belong to the agent workspace only).
//
// The attribute lives on `document.documentElement` (the `<html>` root) — the same
// place useIdentityTheming writes — and is cleaned up on unmount. Both surfaces'
// theming effects clean up on unmount, so toggling `/site` <-> `/app` (Epic 24)
// re-themes cleanly with no stale attribute left behind.
export function useTenantTheming(tenantSlug: string | null): void {
  useEffect(() => {
    const root = document.documentElement;

    if (tenantSlug !== null) {
      root.setAttribute("data-tenant", tenantSlug);
    } else {
      root.removeAttribute("data-tenant");
    }

    return () => {
      root.removeAttribute("data-tenant");
    };
  }, [tenantSlug]);
}
