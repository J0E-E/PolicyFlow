import type { Capability, Role } from "../api";
import { NAV_SECTIONS, isSectionVisible } from "./navSections.ts";
import NavItem from "./NavItem.tsx";

interface LeftNavProperties {
  /** The active persona — gates role-conditional sections (e.g. Outbox). */
  role: Role;
  /** The active role's capabilities — gates capability-conditional sections. */
  capabilities: Capability[];
}

// The fixed left-nav rail for the signed-in /app workspace (Guide §4). It is the
// "Primary" navigation landmark: a <nav aria-label="Primary"> reading the session,
// filtering NAV_SECTIONS by each item's gate against the active role/capabilities,
// and mapping the survivors to NavItem rows.
//
// The rail previews the app's real structure honestly — one live "Demo home" link
// (the active marker) plus the future sections each persona will eventually reach,
// shown inert ("coming in a later step") rather than as dead links. The gate set
// yields, per persona:
//   Agent          = Demo home + 6 CRM sections + Dashboards
//   Tenant Admin   = + Audit Log + Outbox & integration health
//   Read-Only      = Demo home + CRM sections + Dashboards + Audit Log
//   Platform Admin = Demo home + ONLY Platform Health & DLQ
//
// Theming is declarative: the active marker resolves --primary from the ancestor
// [data-tenant] scope. Platform Admin's brand-drain (tokens.css) already neutralizes
// --primary, so the marker degrades to a neutral with no extra inversion CSS here.
//
// AppShell passes role + capabilities (it already holds the session), keeping this a
// pure, props-only component testable without a provider (only a router, for the
// live NavLink). Every element gets a unique descriptive id (CLAUDE.md).
export default function LeftNav({ role, capabilities }: LeftNavProperties) {
  const visibleSections = NAV_SECTIONS.filter((section) =>
    isSectionVisible(section.gate, role, capabilities),
  );

  return (
    <nav id="left-nav" className="left-nav" aria-label="Primary">
      <ul id="left-nav-list" className="left-nav-list">
        {visibleSections.map((section) => (
          <li
            id={`left-nav-row-${section.key}`}
            key={section.key}
            className="left-nav-row"
          >
            <NavItem id={`left-nav-item-${section.key}`} section={section} />
          </li>
        ))}
      </ul>
    </nav>
  );
}
