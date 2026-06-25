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
export type LeadStatus =
  | "New"
  | "Working"
  | "Qualified"
  | "Rejected"
  | "Converted";

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
 * UUIDs and timestamps cross the wire as strings. `is_seed` / `is_session_record` are
 * the two derived demo-session markers (the raw `demo_session_id` never crosses the
 * wire); both are `false` for a session-less caller.
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
  /**
   * `true` when the caller is in a live demo session and this is a shared seed row
   * (`demo_session_id IS NULL` on the backend) — visible to every visitor and not
   * editable. Always `false` for a session-less caller. The UI shows a "SHARED SAMPLE"
   * marker and hides mutating actions on these rows (reveal stays available).
   */
  is_seed: boolean;
  /**
   * `true` when the caller is in a live demo session and this row belongs to that
   * session — the visitor's own record. Always `false` for a session-less caller. The
   * UI shows a "YOUR SESSION" marker on these rows.
   */
  is_session_record: boolean;
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

/**
 * One domain-event row in a lead's timeline (`GET /api/leads/{id}/timeline`),
 * mirroring the backend event-row shape (`core/app/leads/timeline.py`). A domain
 * event is a neutral *fact*, so `kind` is always `"event"` and `status` always
 * `"occurred"` (never a bright state signal — that belongs to its reaction rows).
 * `event_type` is the raw dotted bus value verbatim (e.g. `lead.created`);
 * `occurred_at` is an ISO 8601 timestamp string; `event_id` / `correlation_id` are
 * raw UUID strings.
 */
export interface TimelineEventRow {
  kind: "event";
  status: "occurred";
  /** The raw dotted bus event type, verbatim — e.g. `lead.created`. */
  event_type: string;
  /** ISO 8601 timestamp string of when the event occurred. */
  occurred_at: string;
  /** Raw event UUID string. */
  event_id: string;
  /** Raw correlation UUID string — shared by every event of one lead's flow. */
  correlation_id: string;
}

/**
 * The derived status of a sidecar reaction (P1.9 Epic 2), read off real bus state,
 * never stored. `pending` — the parent event is not yet published; `processing` —
 * published but the consumer has not recorded a result; `done` — the consumer
 * processed it. `failed` is in the vocabulary but dormant (M3 lights it up — the
 * read never emits it this phase).
 */
export type ReactionStatus = "pending" | "processing" | "done" | "failed";

/**
 * One reaction sibling row under a domain event (P1.9 Epic 2), mirroring the
 * backend reaction-row shape (`core/app/leads/timeline.py`). A reaction is a
 * consumer's response to its parent event, so it carries the parent's
 * `event_type` / `event_id` / `correlation_id`, the `consumer_name` (the raw dotted
 * bus actor, e.g. `enrichment.stub`), and a derived `status` that drives a bright
 * on-ink stamp. `occurred_at` is the reaction's `processed_at` ISO string, or `null`
 * while it has not been processed. `result_summary` is the reaction's one-line result —
 * the enrichment quality score, computed deterministically on the consumer write-path;
 * `sync.logger` yields none, so its summary stays `null` (rendered as an omitted sub-line).
 */
export interface TimelineReactionRow {
  kind: "reaction";
  status: ReactionStatus;
  /** The raw dotted consumer name — e.g. `enrichment.stub`, `sync.logger`. */
  consumer_name: string;
  /** The parent event's raw dotted bus event type, verbatim. */
  event_type: string;
  /** The reaction's `processed_at` as an ISO 8601 string, or `null` while unprocessed. */
  occurred_at: string | null;
  /** The parent event's raw UUID string — reactions share their parent's `event_id`. */
  event_id: string;
  /** The parent event's raw correlation UUID string. */
  correlation_id: string;
  /** The one-line reaction result (e.g. the enrichment quality score), or `null` when the
   *  reaction produces no result (the sync logger). A null summary renders no sub-line. */
  result_summary: string | null;
}

/**
 * One row in a lead's timeline — a `kind`-discriminated union of a domain-event row
 * and its reaction sibling rows. The read returns them oldest-first, each event
 * immediately followed by its own reactions.
 */
export type TimelineRow = TimelineEventRow | TimelineReactionRow;

/** The status of the current demo session — mirrors the backend `DemoSessionStatus`. */
export type DemoSessionStatus = "active" | "expired" | "none";

/**
 * The current demo session's public state from `GET /api/demo/session`, mirroring
 * the backend `read_demo_session_state` body. `active` carries all fields;
 * `expired` carries `expires_at` + `last_tenant_slug` (the seam graceful expiry
 * reuses to preserve the tenant); `none` carries just the status. The masthead
 * countdown ticks locally from `expires_at`, fetched once on mount (no polling).
 */
export interface DemoSessionState {
  status: DemoSessionStatus;
  /** Raw demo-session UUID string — present for `active`/`expired`, absent for `none`. */
  demo_session_id?: string;
  /** ISO 8601 timestamp when the session window ends — absent for `none`. */
  expires_at?: string;
  /** The last tenant slug the visit assumed — present when known, else absent. */
  last_tenant_slug?: string;
}

/**
 * The summary returned by `POST /api/demo/session/reset` — how many rows the reset
 * removed. `leads_deleted` totals the caller's session-tagged leads across every
 * tenant schema; `ledger_deleted` counts the seed-ledger markers cleared (so the
 * next persona switch re-seeds a fresh queue).
 */
export interface DemoSessionResetResult {
  leads_deleted: number;
  ledger_deleted: number;
}
