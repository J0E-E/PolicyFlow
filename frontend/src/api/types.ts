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
//   - ProductLine    -> core/app/demo/router.py (each tenant's product_lines)
//   - MaskedLead     -> core/app/leads/masking.py (build_masked_lead — the single
//                       masked read shape every lead read returns)
//   - Lead requests  -> core/app/leads/schemas.py (CreateLeadRequest,
//                       PublicIntakeRequest, RejectLeadRequest,
//                       ResolveDuplicateRequest, RevealLeadRequest)
//   - Lead unions    -> core/app/leads/state.py (LeadStatus / LeadSource),
//                       core/app/leads/router.py (RevealableField),
//                       core/app/leads/schemas.py (ResolveDuplicateAction),
//                       core/app/models/lead.py (DuplicateResolution)
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

/** One product line a tenant offers — the `{ key, label }` pairs the intake forms render. */
export interface ProductLine {
  /** The stored snake_case key, e.g. `medicare_advantage` — submitted on intake. */
  key: string;
  /** The human-readable label, e.g. `Medicare Advantage` — shown in the form. */
  label: string;
}

/** One tenant in the public `GET /api/tenants` list. */
export interface Tenant {
  slug: string;
  display_name: string;
  /** The tenant's authoritative `--primary` brand color, e.g. `#9C4A1E`. */
  brand_primary_color: string;
  /** The product lines this tenant offers, in registry order. */
  product_lines: ProductLine[];
}

/** A lead's lifecycle status — mirrors the backend `LeadStatus` values. */
export type LeadStatus = "New" | "Working" | "Qualified" | "Rejected";

/** Where a lead came from — mirrors the backend `LeadSource` values. */
export type LeadSource = "public_form" | "agent_entered";

/**
 * How a flagged-duplicate lead was resolved, or `null` while unresolved — mirrors
 * the backend `duplicate_resolution` column values.
 */
export type DuplicateResolution = "linked" | "new" | "rejected";

/** A lead field that can be unmasked via the reveal endpoint — every encrypted column. */
export type RevealableField =
  | "email"
  | "phone"
  | "date_of_birth"
  | "street_address";

/**
 * The action naming how an agent resolves a flagged duplicate — the wire value of
 * `ResolveDuplicateRequest.action`. `link` confirms the same person, `new` clears
 * the flag, `reject` discards the lead as a duplicate.
 */
export type ResolveDuplicateAction = "link" | "new" | "reject";

/**
 * The masked read shape returned on every lead read (list, queue, and detail),
 * mirroring `build_masked_lead`. `email`/`phone` are masked display strings,
 * `date_of_birth` is the constant masked-date token (`age_band` carries the usable
 * value), and `street_address` is the `***` token when present or `null` when absent.
 * UUIDs and timestamps cross the wire as strings.
 */
export interface MaskedLead {
  /** Raw lead UUID string. */
  id: string;
  first_name: string;
  last_name: string;
  /** Masked email display string (the cleartext never leaves the server). */
  email: string;
  /** Masked phone display string. */
  phone: string;
  /** The constant masked-date token (`****-**-**`); read `age_band` for the value. */
  date_of_birth: string;
  /** The plaintext age band, e.g. `65-74` — shown directly, never recomputed. */
  age_band: string;
  zip_code: string;
  /** The `***` token when a street address is on file, or `null` when absent. */
  street_address: string | null;
  /** The selected product-line keys. */
  product_lines_of_interest: string[];
  preferred_contact_method: string | null;
  notes: string | null;
  rejection_reason: string | null;
  lead_source: LeadSource;
  status: LeadStatus;
  /** Owning agent's user UUID string, or `null` when unowned (queue leads). */
  owner_user_id: string | null;
  owner_username: string | null;
  /** The matched prior lead's UUID string when flagged a duplicate, else `null`. */
  duplicate_of_lead_id: string | null;
  duplicate_resolution: DuplicateResolution | null;
  /** ISO 8601 timestamp string. */
  created_at: string;
  /** ISO 8601 timestamp string. */
  updated_at: string;
}

/**
 * The agent create request body for `POST /api/leads`, mirroring the lenient
 * `CreateLeadRequest`. Seven required fields plus three optionals; `age_band` is
 * never sent (it is derived server-side from `date_of_birth`).
 */
export interface CreateLeadRequest {
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  /** ISO 8601 date string (`YYYY-MM-DD`). */
  date_of_birth: string;
  zip_code: string;
  /** At least one product-line key. */
  product_lines_of_interest: string[];
  street_address?: string | null;
  preferred_contact_method?: string | null;
  notes?: string | null;
}

/**
 * The strict public intake request body for `POST /api/public/intake`, mirroring
 * `PublicIntakeRequest`. The agent body plus `tenant_slug` (the slug names the
 * tenant on the unauthenticated route) and the optional `website` honeypot (a
 * hidden field a human leaves empty; filling it drops the submission).
 */
export interface PublicIntakeRequest {
  tenant_slug: string;
  /** The honeypot field — leave empty; a non-empty value silently drops the submission. */
  website?: string | null;
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  /** ISO 8601 date string (`YYYY-MM-DD`). */
  date_of_birth: string;
  zip_code: string;
  /** Between 1 and 10 product-line keys. */
  product_lines_of_interest: string[];
  street_address?: string | null;
  preferred_contact_method?: string | null;
  notes?: string | null;
}

/**
 * The reject request body for `POST /api/leads/{id}/reject`, mirroring
 * `RejectLeadRequest`. The free-text `reason` is optional — a reason-less reject is
 * allowed — and stored on the lead, never carried on the event.
 */
export interface RejectLeadRequest {
  reason?: string | null;
}

/**
 * The resolve-duplicate request body for `POST /api/leads/{id}/resolve-duplicate`,
 * mirroring `ResolveDuplicateRequest`.
 */
export interface ResolveDuplicateRequest {
  action: ResolveDuplicateAction;
}

/**
 * The reveal request body for `POST /api/leads/{id}/reveal`, mirroring
 * `RevealLeadRequest` — which single field to unmask for this lead.
 */
export interface RevealLeadRequest {
  field: RevealableField;
}

/**
 * The reveal response from `POST /api/leads/{id}/reveal`: the decrypted `value` of
 * the requested `field`, or `null` when the field has no stored value (an absent
 * `street_address`). `field` echoes the request as a plain string.
 */
export interface RevealLeadResponse {
  field: string;
  value: string | null;
}

/**
 * The sanitized success body from `POST /api/public/intake` — always `{ ok: true }`,
 * on both the real-create and honeypot-drop paths. It never carries the lead.
 */
export interface PublicIntakeResult {
  ok: boolean;
}
