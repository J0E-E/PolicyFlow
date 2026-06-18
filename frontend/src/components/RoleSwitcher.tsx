import { useRef, useState } from "react";
import type { Role } from "../api";
import { ROLE_LABELS } from "./roleLabels.ts";
import { PERSONA_ICONS } from "./personaIcons.ts";
import PersonaChip from "./PersonaChip.tsx";

interface RoleSwitcherProperties {
  /** Required base id; every rendered element derives a unique id from it. */
  id: string;
  /** Switch to a seeded persona — the session context's `assumePersona`, threaded
   *  down from AppShell through Masthead (so this stays a pure, props-only
   *  component testable with a stub). Resolves on success, rejects on failure. */
  assumePersona: (tenantSlug: string, role: Role) => Promise<void>;
  /** The active persona — selects which chip is pressed. */
  currentRole: Role;
  /** The active tenant slug, or null for the tenantless Platform Admin. */
  currentTenantSlug: string | null;
}

// The persona order on the bar (Guide §6.7): the three tenant-scoped hands, then
// the tenantless ops persona last.
const PERSONA_ORDER: Role[] = [
  "agent",
  "tenant_admin",
  "read_only",
  "platform_admin",
];

// The masthead role switcher (Guide §2.4, §6.7): the four personas as annotated
// chips. Selecting one calls `assumePersona`, which re-mints the session as that
// real seeded user — RBAC is enforced because the visitor now *is* that user, not
// because the chrome changed (the color is a cue, never the gate).
//
// Home-tenant memory: the three tenant-scoped chips switch within the tenant the
// visitor is "in", but Platform Admin is tenantless, so once you visit it there is
// no current slug to switch back into. The switcher remembers the last
// tenant-scoped slug it has seen (a ref updated on every render that carries a
// tenant) and routes the tenant-scoped chips at that remembered home tenant, so
// returning from Platform Admin lands back where you started. Platform Admin
// itself ignores the slug (assumePersona resolves the global tenantless admin).
//
// Active-chip no-op, in-flight, and error mirror SelectTenantPage's loading/error
// pattern: clicking the active persona short-circuits (no pointless re-mint +
// audit churn); a switch in flight disables all chips and announces "Switching…";
// a failure surfaces a message (aria-live) and re-enables the chips.
export default function RoleSwitcher({
  id,
  assumePersona,
  currentRole,
  currentTenantSlug,
}: RoleSwitcherProperties) {
  // The last tenant-scoped slug seen — the "home" tenant the tenant-scoped chips
  // switch within. Updated whenever a tenant-scoped identity is present so it
  // survives a round-trip through the tenantless Platform Admin.
  const homeTenantSlug = useRef<string | null>(null);
  if (currentTenantSlug !== null) {
    homeTenantSlug.current = currentTenantSlug;
  }

  const [pendingRole, setPendingRole] = useState<Role | null>(null);
  const [switchError, setSwitchError] = useState<string | null>(null);

  const isSwitching = pendingRole !== null;

  async function handleSelectPersona(role: Role) {
    // Clicking the already-active persona is a no-op — avoid a pointless re-mint
    // and audit churn (settled at plan time).
    if (role === currentRole || isSwitching) {
      return;
    }

    // Platform Admin is tenantless (assumePersona ignores the slug); the three
    // tenant-scoped chips target the remembered home tenant. The fallback below
    // cannot occur via the normal demo entry, which always starts in a tenant.
    const targetTenantSlug =
      role === "platform_admin"
        ? (currentTenantSlug ?? homeTenantSlug.current ?? "")
        : (homeTenantSlug.current ?? currentTenantSlug ?? "");

    setSwitchError(null);
    setPendingRole(role);
    try {
      await assumePersona(targetTenantSlug, role);
      // On success the session context re-themes from the new identity; this
      // component just clears its in-flight state.
      setPendingRole(null);
    } catch {
      setPendingRole(null);
      setSwitchError("Could not switch persona. Please try again.");
    }
  }

  return (
    <div
      id={id}
      className="role-switcher"
      role="group"
      aria-label="Switch persona"
    >
      <div id={`${id}-chips`} className="role-switcher-chips">
        {PERSONA_ORDER.map((role) => {
          const IconComponent = PERSONA_ICONS[role];
          return (
            <PersonaChip
              key={role}
              id={`${id}-${role}`}
              role={role}
              label={ROLE_LABELS[role]}
              icon={<IconComponent width={16} height={16} />}
              isActive={role === currentRole}
              isPending={isSwitching}
              onSelect={handleSelectPersona}
            />
          );
        })}
      </div>

      {/* One status line — pending and error are mutually exclusive (a switch in
          flight has no error yet; an error means nothing is in flight), so the
          single `${id}-message` id is never duplicated. The aria-live region is
          always rendered so a screen reader announces the change in place. */}
      <p
        id={`${id}-message`}
        className="role-switcher-message"
        role="status"
        aria-live="polite"
      >
        {isSwitching ? "Switching…" : (switchError ?? "")}
      </p>
    </div>
  );
}
