import type { Identity } from "../api";
import TenantSealMark from "./TenantSealMark.tsx";
import PersonaIndicator from "./PersonaIndicator.tsx";
import StampTag from "./StampTag.tsx";

interface MastheadProperties {
  /** The signed-in identity — supplies the tenant brand cluster and persona. */
  identity: Identity;
}

// The branded app-shell masthead (Guide §2.3, §4 "App shell is a fixed left nav +
// top masthead", §6.5). Two clusters on the top bar over a 3px letterhead rule in
// the tenant brand `--primary`:
//
//   left  — the tenant seal mark, the "PolicyFlow" wordmark, the tenant name,
//           and the persona indicator (who you are, what tenant you're in).
//   right — a static "DEMO SESSION" stamp (the live countdown is P1.8), an inert
//           notification-bell placeholder (Guide §6.12, wired later), and an
//           inert "How it's built" link (Epic 21 wires it to the real page).
//
// The inert affordances are real disabled controls with accessible names and
// aria-disabled, so they are announced as present-but-unavailable rather than
// silently missing (Guide §7). Theming is declarative: an ancestor `[data-tenant]`
// / `[data-persona]` scope (set by useIdentityTheming) resolves `--primary` and
// the persona accent, so this component carries no tenant/persona logic itself.
//
// Platform Admin (no tenant scope) is reachable only once the Epic 11 switcher
// exists; until then the masthead renders for a tenant-scoped persona. The
// tenant brand cluster is shown only when a tenant name is present, so a
// tenantless identity degrades gracefully (no seal, no tenant name) rather than
// rendering a broken seal — the full Platform-Admin masthead inversion is Epic 11.
export default function Masthead({ identity }: MastheadProperties) {
  const { role, tenant_slug: tenantSlug, tenant_name: tenantName } =
    identity.user;
  const hasTenantScope = tenantSlug !== null && tenantName !== null;

  return (
    <header id="app-masthead" className="masthead">
      <div id="app-masthead-bar" className="masthead-bar">
        <div id="app-masthead-left" className="masthead-cluster masthead-left">
          {hasTenantScope && (
            <TenantSealMark id="app-masthead-seal" slug={tenantSlug} />
          )}
          <span id="app-masthead-wordmark" className="masthead-wordmark">
            PolicyFlow
          </span>
          {hasTenantScope && (
            <>
              <span
                id="app-masthead-tenant-divider"
                className="masthead-divider"
                aria-hidden="true"
              />
              <span id="app-masthead-tenant-name" className="masthead-tenant-name">
                {tenantName}
              </span>
            </>
          )}
          <PersonaIndicator id="app-masthead-persona" role={role} />
        </div>

        <div id="app-masthead-right" className="masthead-cluster masthead-right">
          <StampTag id="app-masthead-session-stamp" variant="overline">
            Demo session
          </StampTag>
          <button
            id="app-masthead-notifications-button"
            type="button"
            className="masthead-icon-button"
            disabled
            aria-disabled="true"
            aria-label="Notifications (coming later)"
            title="Notifications — coming later"
          >
            <span
              id="app-masthead-notifications-glyph"
              className="masthead-bell-glyph"
              aria-hidden="true"
            />
          </button>
          <span
            id="app-masthead-how-its-built"
            className="masthead-how-its-built"
            role="link"
            aria-disabled="true"
            title="How it's built — coming later"
          >
            How it's built
          </span>
        </div>
      </div>
      <div
        id="app-masthead-letterhead-rule"
        className="masthead-letterhead-rule"
        aria-hidden="true"
      />
    </header>
  );
}
