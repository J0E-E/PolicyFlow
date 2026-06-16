// Shared TypeScript types for the data that crosses the wire between the
// frontend and the backend. These mirror the backend's JSON **wire shape
// exactly** — snake_case keys, raw UUID strings — so there is no transform
// layer the call sites would otherwise pay for on every request. See the
// backend sources each type tracks:
//   - Role           -> core/app/models/user.py (the `Role` StrEnum values)
//   - Capability     -> core/app/auth/rbac.py (the `Capability` StrEnum values)
//   - Identity       -> core/app/auth/identity.py (build_identity_response;
//                       the user block carries tenant_slug + tenant_name, both
//                       null for the tenantless Platform Admin)
//   - Tenant         -> core/app/demo/router.py (GET /api/tenants entries)
//
// Drift note: these unions mirror the backend StrEnums by hand, so a value
// added on the backend is unknown to the frontend type until it is added here
// too. Acceptable for the demo; recorded in the epic plan.

/** Who a user is — mirrors the backend `Role` StrEnum values. */
export type Role = "agent" | "tenant_admin" | "read_only" | "platform_admin";

/** One permission a role may hold — mirrors the backend `Capability` values. */
export type Capability =
  | "view_tenant_records"
  | "create_edit_records"
  | "claim_leads_manage_tasks"
  | "reassign_leads_tasks"
  | "reveal_pii"
  | "replay_discard_dlq"
  | "view_tenant_config"
  | "view_audit_logs"
  | "view_dashboards"
  | "platform_health_demo_controls";

/** The signed-in user's public fields — no PII (no email, no password hash). */
export interface IdentityUser {
  /** Raw user UUID string. */
  id: string;
  username: string;
  role: Role;
  /** Tenant UUID string, or `null` for the tenantless Platform Admin. */
  tenant_id: string | null;
  /** Tenant slug (e.g. `sunshine-senior-benefits`), or `null` for Platform Admin. */
  tenant_slug: string | null;
  /** Tenant display name (e.g. `Sunshine Senior Benefits`), or `null` for Platform Admin. */
  tenant_name: string | null;
}

/**
 * The shared identity body returned by login, `GET /api/auth/me`, and
 * `POST /api/demo/assume-persona`. `capabilities` is a flat, sorted array of the
 * capability strings the user's role holds (per the backend RBAC matrix).
 */
export interface Identity {
  user: IdentityUser;
  capabilities: Capability[];
}

/** One tenant in the public `GET /api/tenants` list. */
export interface Tenant {
  slug: string;
  display_name: string;
  /** The tenant's authoritative `--primary` brand color, e.g. `#9C4A1E`. */
  brand_primary_color: string;
}
