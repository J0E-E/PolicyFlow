import { HelpCircle } from "iconoir-react";
import type { Identity, Role } from "../api";
import TenantSealMark from "./TenantSealMark.tsx";
import RoleSwitcher from "./RoleSwitcher.tsx";
import DemoSessionCountdown from "./DemoSessionCountdown.tsx";
import ViewOnlyTag from "./ViewOnlyTag.tsx";
import ExplainerPopover from "./ExplainerPopover.tsx";
import SurfaceToggle from "./SurfaceToggle.tsx";
import {
  roleSwitcherExplainer,
  sessionModelExplainer,
} from "./explainerContent.ts";

interface MastheadProperties {
  /** The signed-in identity — supplies the tenant brand cluster and persona. */
  identity: Identity;
  /** Switch to a seeded persona — the session context's `assumePersona`, threaded
   *  in from AppShell so this stays a pure, props-only component (its tests render
   *  it with a stub, no provider). Forwarded to the role switcher. */
  assumePersona: (tenantSlug: string, role: Role) => Promise<void>;
  /** Open the scenario-reference modal — AppShell owns the open flag and threads
   *  this opener in (Epic 18). The persistent help-icon button in the right cluster
   *  calls it; the docket header carries the other entry point. */
  onOpenScenarioReference: () => void;
}

// The branded app-shell masthead (Guide §2.3, §4 "App shell is a fixed left nav +
// top masthead", §6.5). Two clusters on the top bar over a 3px letterhead rule in
// the tenant brand `--primary`:
//
//   left  — the tenant seal mark, the "PolicyFlow" wordmark, the tenant name,
//           and the role switcher (who you are, what tenant you're in).
//   right — the live demo-session countdown ("DEMO SESSION · HH:MM REMAINING",
//           P1.8 — self-contained, owns its own fetch), an inert
//           notification-bell placeholder (Guide §6.12, wired later), and a live
//           "How it's built" link opening the public /how-its-built page in a new
//           tab (Epic 21 — preserving the open workspace).
//
// The inert affordances are real disabled controls with accessible names and
// aria-disabled, so they are announced as present-but-unavailable rather than
// silently missing (Guide §7). Theming is declarative: an ancestor `[data-tenant]`
// / `[data-persona]` scope (set by useIdentityTheming) resolves `--primary` and
// the persona accent, so this component carries no tenant/persona logic itself.
//
// Platform Admin (no tenant scope) is reachable via the role switcher. The tenant
// brand cluster shows only when a tenant name is present, so the tenantless
// Platform Admin degrades gracefully (no seal, no tenant name); the whole masthead
// inverts to `--surface-ink` via the `[data-persona="platform_admin"]` scope
// (styles/app-shell.css), and a "PLATFORM OPERATIONS — OUTSIDE TENANT SCOPE" label
// (Guide §2.4, §6.7 verbatim) renders alongside the switcher.
//
// The Read-Only persona instead carries a persistent "VIEW ONLY" posture tag after
// the switcher (Guide §2.4). The two posture labels are mutually exclusive and only
// the constrained personas carry one — Agent and Tenant Admin (the normal editable,
// in-tenant state) get none (the deliberate Guide §2.4 asymmetry).
export default function Masthead({
  identity,
  assumePersona,
  onOpenScenarioReference,
}: MastheadProperties) {
  const { role, tenant_slug: tenantSlug, tenant_name: tenantName } =
    identity.user;
  const hasTenantScope = tenantSlug !== null && tenantName !== null;
  const isPlatformAdmin = role === "platform_admin";
  const isReadOnly = role === "read_only";

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
          <RoleSwitcher
            id="app-masthead-role-switcher"
            assumePersona={assumePersona}
            currentRole={role}
            currentTenantSlug={tenantSlug}
          />
          {/* RBAC explainer (Epic 19) — beside the switcher, not inside it
              (RoleSwitcher stays pure/props-only). The masthead's on-ink focus
              scope (Epic 11's --focus-ring-on-ink, app-shell.css) keeps its focus
              ring visible when Platform Admin inverts the masthead. */}
          <ExplainerPopover
            id="explainer-role-switcher"
            surfaceLabel="role-based access control"
            content={roleSwitcherExplainer}
          />
          {isReadOnly && <ViewOnlyTag id="app-masthead-view-only" />}
          {isPlatformAdmin && (
            <span
              id="app-masthead-platform-ops"
              className="masthead-platform-ops"
            >
              <span
                id="app-masthead-platform-ops-label"
                className="masthead-platform-ops-label"
              >
                PLATFORM OPERATIONS — OUTSIDE TENANT SCOPE
              </span>
            </span>
          )}
        </div>

        <div id="app-masthead-right" className="masthead-cluster masthead-right">
          {/* Surface toggle (Epic 24) — leading the utility cluster. "View the
              public site →" navigates to this tenant's Shopper storefront, the
              pf_session cookie riding along so toggling back lands signed-in. Only
              for a tenant-scoped identity: the tenantless Platform Admin has no
              single storefront to preview, so it sees no toggle (consistent with
              the masthead already dropping the seal + tenant name for it). */}
          {hasTenantScope && (
            <SurfaceToggle
              id="app-masthead-surface-toggle"
              to={`/site/${tenantSlug}`}
              label="View the public site"
              direction="forward"
            />
          )}
          {/* Persistent help affordance (Epic 18): a LIVE icon button opening the
              scenario-reference modal — the catalog of every demo scenario, its
              trigger, and its outcome. Reuses the icon-button geometry but overrides
              the bell's inert cursor (it is a real control). */}
          <button
            id="app-masthead-scenario-reference-button"
            type="button"
            className="masthead-icon-button masthead-help-button"
            aria-haspopup="dialog"
            aria-label="Scenario reference"
            title="Scenario reference"
            onClick={onOpenScenarioReference}
          >
            <HelpCircle
              width={18}
              height={18}
              aria-hidden="true"
              className="masthead-help-glyph"
            />
          </button>
          {/* Live demo-session countdown (P1.8) — self-contained: it owns its own
              `GET /api/demo/session` fetch and ticks locally from `expires_at`, so
              this masthead stays props-only. For an active session it renders
              "DEMO SESSION · HH:MM REMAINING"; every other state falls back to the
              plain "DEMO SESSION" overline stamp (keeping the stable
              `app-masthead-session-stamp` id). */}
          <DemoSessionCountdown />
          {/* Session-model explainer (Epic 19) — after the DEMO SESSION stamp,
              explaining the sandboxed demo session (no CRM PARALLEL section). */}
          <ExplainerPopover
            id="explainer-session-model"
            surfaceLabel="the demo session"
            content={sessionModelExplainer}
          />
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
          {/* Live link to the public "How it's built" page (Epic 21). Opens in a
              new tab (target="_blank" + rel) so the demo workspace stays put; same
              id as Epic 10's inert placeholder. */}
          <a
            id="app-masthead-how-its-built"
            className="masthead-how-its-built"
            href="/how-its-built"
            target="_blank"
            rel="noopener noreferrer"
            title="How it's built — opens in a new tab"
          >
            How it's built
          </a>
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
