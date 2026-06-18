import type { Role } from "../api";

// One human-readable label per role, so chrome and copy read in plain words
// ("Agent", "Tenant Admin") rather than the wire value ("agent", "tenant_admin").
// Shared by the demo home status line and the masthead role switcher so the
// two never drift (a role renamed here is renamed in both places at once).
export const ROLE_LABELS: Record<Role, string> = {
  agent: "Agent",
  tenant_admin: "Tenant Admin",
  read_only: "Read-Only",
  platform_admin: "Platform Admin",
};
