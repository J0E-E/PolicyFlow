import { useEffect } from "react";
import type { Identity } from "../api";

// Drives the Guide's declarative theming from the signed-in identity. The token
// layer (tokens.css) keys the tenant brand ramp off `[data-tenant="<slug>"]` and
// the persona accent + Platform-Admin brand-drain off `[data-persona="<role>"]`;
// this effect is the one place those attributes get set, so the whole app
// re-themes the moment identity changes (e.g. the Epic 11 role switch).
//
// The attributes live on `document.documentElement` (the `<html>` root) per the
// TDD: theming applies to the whole document, not just the shell subtree, and a
// later full dark theme would key off the same root. The effect cleans the
// attributes up on unmount so leaving the guarded `/app` zone (sign-out) drops
// the tenant/persona theming and the app falls back to neutral paper.
//
// Platform Admin operates outside tenant scope (`tenant_slug === null`): no
// `data-tenant` is set, so the `[data-persona="platform_admin"]` brand-drain in
// tokens.css takes over and no tenant brand can render.
export function useIdentityTheming(identity: Identity | null): void {
  const tenantSlug = identity?.user.tenant_slug ?? null;
  const role = identity?.user.role ?? null;

  useEffect(() => {
    const root = document.documentElement;

    if (tenantSlug !== null) {
      root.setAttribute("data-tenant", tenantSlug);
    } else {
      root.removeAttribute("data-tenant");
    }

    if (role !== null) {
      root.setAttribute("data-persona", role);
    } else {
      root.removeAttribute("data-persona");
    }

    return () => {
      root.removeAttribute("data-tenant");
      root.removeAttribute("data-persona");
    };
  }, [tenantSlug, role]);
}
