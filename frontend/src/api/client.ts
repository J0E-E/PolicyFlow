// The single typed HTTP client every later frontend epic calls. It is a thin
// `fetch` wrapper that sends the `pf_session` cookie on every request
// (`credentials: "include"`) and exposes the four backend calls the demo shell
// needs, each returning its parsed, typed body.
//
// A failed call surfaces as a thrown, typed `ApiError` carrying the HTTP
// `status` (or `0` for a network drop) and a human-readable `message`. Callers
// use try/catch; Epic 4 will branch on `error.status === 401` to tell "signed
// out" from a real failure.

import type {
  RenewalSweepResult,
  ConversionPrefill,
  ConversionSummary,
  ConvertLeadRequest,
  CreateLeadRequest,
  HouseholdSearchResult,
  DemoSessionResetResult,
  DemoSessionState,
  Identity,
  MaskedLead,
  Application,
  OpportunityBoard,
  OpportunityRow,
  Policy,
  PublicIntakeRequest,
  QuoteRequestPoll,
  QuoteRequestSummary,
  PublicIntakeResult,
  RejectLeadRequest,
  ResolveDuplicateRequest,
  RevealLeadRequest,
  RevealLeadResponse,
  Role,
  Tenant,
  TimelineRow,
} from "./types";

/**
 * A failed API call, thrown by the client. `status` is the HTTP status code, or
 * `0` when the request never reached the server (a network drop). `message`
 * carries the backend's `detail` string when it is one, or a sensible fallback.
 */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** The HTTP methods this client issues. */
type HttpMethod = "GET" | "POST" | "PATCH";

/**
 * Send one request to the backend and return its parsed JSON body, typed as `T`.
 *
 * The `pf_session` cookie rides every call via `credentials: "include"`. For a
 * POST with a body, the JSON `Content-Type` header is set and the body is
 * serialized. A non-2xx response throws an `ApiError` carrying the status and
 * the backend's `detail` (when it is a string) or a fallback; a network failure
 * throws an `ApiError` with `status` `0`.
 */
async function request<T>(
  method: HttpMethod,
  path: string,
  body?: unknown,
): Promise<T> {
  const requestOptions: RequestInit = {
    method,
    credentials: "include",
  };
  if (body !== undefined) {
    requestOptions.headers = { "Content-Type": "application/json" };
    requestOptions.body = JSON.stringify(body);
  }

  let response: Response;
  try {
    response = await fetch(path, requestOptions);
  } catch {
    // The request never reached the server (offline, DNS failure, CORS block).
    throw new ApiError(0, "network request failed");
  }

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorMessage(response));
  }

  return (await response.json()) as T;
}

/**
 * Pull a human-readable error message out of a failed response. Uses the
 * backend's `detail` field when it is a string; otherwise — a `422`'s
 * validation array, a missing `detail`, or a non-JSON body — falls back to the
 * response's status text or a generic message.
 */
async function readErrorMessage(response: Response): Promise<string> {
  try {
    const errorBody = await response.json();
    if (
      errorBody !== null &&
      typeof errorBody === "object" &&
      typeof (errorBody as { detail?: unknown }).detail === "string"
    ) {
      return (errorBody as { detail: string }).detail;
    }
  } catch {
    // Body was not JSON — fall through to the status-text fallback.
  }
  return response.statusText || "request failed";
}

/**
 * Get the currently signed-in user's identity from `GET /api/auth/me`. Throws an
 * `ApiError` with `status` `401` when there is no active session.
 */
export function getCurrentIdentity(): Promise<Identity> {
  return request<Identity>("GET", "/api/auth/me");
}

/**
 * List the public tenants from `GET /api/tenants`, unwrapping the
 * `{ tenants: [...] }` envelope into a plain array.
 */
export async function listTenants(): Promise<Tenant[]> {
  const responseBody = await request<{ tenants: Tenant[] }>(
    "GET",
    "/api/tenants",
  );
  return responseBody.tenants;
}

/**
 * Assume a seeded demo persona via `POST /api/demo/assume-persona`, re-minting
 * the session as that user and returning the new identity. The call arguments
 * stay camelCase; the wrapper maps `tenantSlug` to the wire's `tenant_slug`.
 */
export function assumePersona(
  tenantSlug: string,
  role: Role,
): Promise<Identity> {
  return request<Identity>("POST", "/api/demo/assume-persona", {
    tenant_slug: tenantSlug,
    role,
  });
}

/**
 * Read the current demo session's state from the public `GET /api/demo/session`.
 *
 * The masthead countdown fetches this once on mount and then ticks locally from
 * `expires_at`. The body is the flat `DemoSessionState` shape (no envelope): an
 * `active` session carries the id, expiry, and remembered tenant; `expired` keeps
 * the expiry + tenant; `none` is just `{ status: "none" }`. The `pf_demo_session`
 * cookie rides the call via `credentials: "include"`.
 */
export function getDemoSession(): Promise<DemoSessionState> {
  return request<DemoSessionState>("GET", "/api/demo/session");
}

/**
 * Reset the caller's own demo session via `POST /api/demo/session/reset`.
 *
 * The Platform-Admin-only workspace reset: it wipes this demo session's leads
 * (across every tenant schema) and its seed-ledger markers, but keeps the session
 * row, the `pf_demo_session` cookie, and the countdown alive — re-seeding is
 * deferred to the next persona switch. Returns the `{ leads_deleted, ledger_deleted }`
 * summary of what was removed; the `pf_demo_session` cookie rides the call via
 * `credentials: "include"`.
 */
export function resetDemoSession(): Promise<DemoSessionResetResult> {
  return request<DemoSessionResetResult>("POST", "/api/demo/session/reset");
}

/**
 * Run the AEP renewal sweep via `POST /api/renewals/aep-sweep` (P2.4 Epic 6).
 *
 * The Platform-Admin-only sweep: it runs `generate_renewals` for the AEP rule over
 * the caller's demo session in its currently-selected tenant, bypassing the seasonal
 * calendar, and returns the `{ generated, skipped }` counts. The `pf_demo_session`
 * cookie rides the call via `credentials: "include"`; a re-run of an already-swept
 * session reports every policy as `skipped` (idempotent).
 */
export function runAepSweep(): Promise<RenewalSweepResult> {
  return request<RenewalSweepResult>("POST", "/api/renewals/aep-sweep");
}

/**
 * Run the anniversary renewal sweep via `POST /api/renewals/anniversary-sweep`
 * (P2.4 Epic 8).
 *
 * The Platform-Admin-only sibling of `runAepSweep`: it runs `generate_renewals` for
 * the anniversary rule over the caller's demo session in its currently-selected
 * tenant, renewing only anniversary-line policies inside the rolling 60-day window,
 * and returns the same `{ generated, skipped }` counts. Idempotent on re-run.
 */
export function runAnniversarySweep(): Promise<RenewalSweepResult> {
  return request<RenewalSweepResult>("POST", "/api/renewals/anniversary-sweep");
}

/** Sign out via `POST /api/auth/logout`; the response body is ignored. */
export async function signOut(): Promise<void> {
  await request<{ detail: string }>("POST", "/api/auth/logout");
}

/**
 * Create a lead as the signed-in agent via `POST /api/leads`, unwrapping the
 * `{ lead }` envelope into the masked lead. The request is the snake_case wire body
 * passed straight through.
 */
export async function createLead(
  createLeadRequest: CreateLeadRequest,
): Promise<MaskedLead> {
  const responseBody = await request<{ lead: MaskedLead }>(
    "POST",
    "/api/leads",
    createLeadRequest,
  );
  return responseBody.lead;
}

/**
 * Submit a public intake via the unauthenticated `POST /api/public/intake`,
 * returning the sanitized `{ ok: true }` result (never the lead — identical on the
 * real-create and honeypot-drop paths).
 */
export function submitPublicIntake(
  publicIntakeRequest: PublicIntakeRequest,
): Promise<PublicIntakeResult> {
  return request<PublicIntakeResult>(
    "POST",
    "/api/public/intake",
    publicIntakeRequest,
  );
}

/**
 * List leads from `GET /api/leads`, unwrapping the `{ leads }` envelope. Pass
 * `unassigned` `true` to restrict to the queue (unowned `New` leads); the
 * `?unassigned=true` query is appended **only** when `true`, matching the queue
 * tab's absent/`true` convention.
 */
export async function listLeads(unassigned?: boolean): Promise<MaskedLead[]> {
  const path = unassigned ? "/api/leads?unassigned=true" : "/api/leads";
  const responseBody = await request<{ leads: MaskedLead[] }>("GET", path);
  return responseBody.leads;
}

/**
 * Get one lead from `GET /api/leads/{id}`, unwrapping the `{ lead }` envelope.
 * Throws an `ApiError` with `status` `404` for a missing or cross-tenant id.
 */
export async function getLead(leadId: string): Promise<MaskedLead> {
  const responseBody = await request<{ lead: MaskedLead }>(
    "GET",
    `/api/leads/${leadId}`,
  );
  return responseBody.lead;
}

/**
 * Get the pipeline board from `GET /api/opportunities` — the tenant's enabled,
 * labeled `pipeline.stages` (the columns) plus the `opportunities` rows. An empty
 * `opportunities` array is a valid result — a session with none converted yet.
 */
export async function getOpportunityBoard(): Promise<OpportunityBoard> {
  return request<OpportunityBoard>("GET", "/api/opportunities");
}

/**
 * Advance one opportunity via `POST /api/opportunities/{id}/stage`, unwrapping the
 * `{ opportunity }` envelope into the updated row. `targetStage` is the canonical
 * stage value to move to (the row's `next_stage`). Throws an `ApiError` carrying
 * the status for a refused move — `404` (unknown), `403` (not owner/admin), `409`
 * (illegal transition), `422` (unknown stage).
 */
export async function changeOpportunityStage(
  opportunityId: string,
  targetStage: string,
): Promise<OpportunityRow> {
  const responseBody = await request<{ opportunity: OpportunityRow }>(
    "POST",
    `/api/opportunities/${opportunityId}/stage`,
    { target_stage: targetStage },
  );
  return responseBody.opportunity;
}

/**
 * Open a carrier-quote round-trip via `POST /api/opportunities/{id}/quote-requests`,
 * unwrapping the `{ quote_request }` envelope into the new `pending` request. The
 * caller then polls it with `getQuoteRequest`. Throws an `ApiError` carrying the
 * status for a refused request — `404` (unknown), `403` (not owner/admin), `409`
 * (not a qualified opportunity), `422` (Medicare-gated under-65).
 */
export async function requestQuotes(
  opportunityId: string,
): Promise<QuoteRequestSummary> {
  const responseBody = await request<{ quote_request: QuoteRequestSummary }>(
    "POST",
    `/api/opportunities/${opportunityId}/quote-requests`,
  );
  return responseBody.quote_request;
}

/**
 * Poll one quote round-trip via `GET /api/opportunities/{id}/quote-requests/{rid}`.
 * A pure read: the `quotes` array is empty until the request is `completed`, then
 * carries the attached options, and `opportunity_stage` reflects the *Quoted* move.
 * Throws an `ApiError` with `status` `404` for an unknown / cross-session request.
 */
export function getQuoteRequest(
  opportunityId: string,
  quoteRequestId: string,
): Promise<QuoteRequestPoll> {
  return request<QuoteRequestPoll>(
    "GET",
    `/api/opportunities/${opportunityId}/quote-requests/${quoteRequestId}`,
  );
}

/**
 * Get the policy issued for one opportunity via
 * `GET /api/opportunities/{id}/policy`, unwrapping the `{ policy }` envelope. The
 * policy's `status` is overlay-aware (P2.4 Epic 6): a baseline policy the caller's
 * session has renewed reads *Renewal Due*. Throws an `ApiError` with `status` `404`
 * for an opportunity not visible to the caller or one with no issued policy.
 */
export async function getOpportunityPolicy(
  opportunityId: string,
): Promise<Policy> {
  const responseBody = await request<{ policy: Policy }>(
    "GET",
    `/api/opportunities/${opportunityId}/policy`,
  );
  return responseBody.policy;
}

/**
 * Select an attached quote via `POST /api/opportunities/{id}/applications`,
 * unwrapping the `{ application }` envelope into the new Draft Application. The
 * opportunity advances to *Application Started* server-side. Throws an `ApiError`
 * carrying the status for a refused selection — `404` (unknown opportunity/quote),
 * `403` (not owner/admin), `409` (opportunity not Quoted).
 */
export async function selectQuote(
  opportunityId: string,
  quoteId: string,
): Promise<Application> {
  const responseBody = await request<{ application: Application }>(
    "POST",
    `/api/opportunities/${opportunityId}/applications`,
    { quote_id: quoteId },
  );
  return responseBody.application;
}

/**
 * Capture the product-specific step on a Draft application via
 * `PATCH /api/applications/{id}`, unwrapping the `{ application }` envelope into the
 * updated application. The body carries the `beneficiary` details **or** the
 * `health_answers`, matching the product line's step. Throws an `ApiError` carrying
 * the status for a refused capture — `404`, `403`, `409` (not Draft), `422` (wrong
 * or incomplete step payload).
 */
export async function patchApplication(
  applicationId: string,
  body: {
    beneficiary?: Record<string, string>;
    health_answers?: Record<string, boolean>;
    medicare_id?: string;
  },
): Promise<Application> {
  const responseBody = await request<{ application: Application }>(
    "PATCH",
    `/api/applications/${applicationId}`,
    body,
  );
  return responseBody.application;
}

/**
 * Reveal the unmasked Medicare ID of one application via
 * `POST /api/applications/{id}/reveal-medicare-id` — the audited, capability-gated
 * reveal (Tenant-1). Returns `{ field, value }` (`value` is `null` when none was
 * captured). Throws an `ApiError` for a refused reveal — `403` (no `REVEAL_PII`),
 * `404`, `422` (the tenant collects no Medicare ID).
 */
export function revealMedicareId(
  applicationId: string,
): Promise<{ field: string; value: string | null }> {
  return request<{ field: string; value: string | null }>(
    "POST",
    `/api/applications/${applicationId}/reveal-medicare-id`,
  );
}

/**
 * Submit a Draft application via `POST /api/applications/{id}/submit`, running the
 * inline carrier decision server-side. Returns the decided application (now
 * `Approved` or `Declined`) and the opportunity's new stage. Throws an `ApiError`
 * carrying the status for a refused submit — `404`, `403`, `409` (not Draft, or the
 * step is not complete).
 */
export async function submitApplication(
  applicationId: string,
): Promise<{
  application: Application;
  opportunity_stage: string;
  policy: Policy | null;
}> {
  return request<{
    application: Application;
    opportunity_stage: string;
    policy: Policy | null;
  }>("POST", `/api/applications/${applicationId}/submit`);
}

/**
 * Get one lead's event timeline from `GET /api/leads/{id}/timeline`, unwrapping the
 * `{ rows }` envelope into the oldest-first row array. The rows are the lead's own
 * domain events (P1.9 Epic 1 tracer — events only). Throws an `ApiError` with
 * `status` `404` for a missing, cross-tenant, or cross-session lead (the same guard
 * as `getLead`). An empty array is a valid result — a lead with no events yet.
 */
export async function getLeadTimeline(leadId: string): Promise<TimelineRow[]> {
  const responseBody = await request<{ rows: TimelineRow[] }>(
    "GET",
    `/api/leads/${leadId}/timeline`,
  );
  return responseBody.rows;
}

/**
 * Claim a lead via `POST /api/leads/{id}/claim` (moves `New → Working`, owned by
 * the caller), unwrapping the `{ lead }` envelope into the updated masked lead.
 */
export async function claimLead(leadId: string): Promise<MaskedLead> {
  const responseBody = await request<{ lead: MaskedLead }>(
    "POST",
    `/api/leads/${leadId}/claim`,
  );
  return responseBody.lead;
}

/**
 * Qualify a lead via `POST /api/leads/{id}/qualify` (moves `Working → Qualified`),
 * unwrapping the `{ lead }` envelope into the updated masked lead.
 */
export async function qualifyLead(leadId: string): Promise<MaskedLead> {
  const responseBody = await request<{ lead: MaskedLead }>(
    "POST",
    `/api/leads/${leadId}/qualify`,
  );
  return responseBody.lead;
}

/**
 * Get the duplicate pre-select for a lead from
 * `GET /api/leads/{id}/conversion-prefill` — the household to pre-select on the convert
 * screen, or `{ preselected_household: null }` when the lead is not a duplicate of a
 * converted prior. Throws an `ApiError` with `status` `404` for a missing /
 * cross-tenant / cross-session lead. Returned flat (no envelope).
 */
export async function getConversionPrefill(
  leadId: string,
): Promise<ConversionPrefill> {
  return request<ConversionPrefill>(
    "GET",
    `/api/leads/${leadId}/conversion-prefill`,
  );
}

/**
 * Search households by name via `GET /api/households?q=`, unwrapping the
 * `{ households }` envelope into the match array (each with its members' plaintext
 * names). Backs the convert "link an existing household" picker; an empty array is a
 * valid result (no match). Tenant- and session-scoped on the server.
 */
export async function getHouseholds(
  query: string,
): Promise<HouseholdSearchResult[]> {
  const responseBody = await request<{ households: HouseholdSearchResult[] }>(
    "GET",
    `/api/households?q=${encodeURIComponent(query)}`,
  );
  return responseBody.households;
}

/**
 * Get a converted lead's "converted to" summary from `GET /api/leads/{id}/conversion`
 * (the contact / household / opportunities it became). Throws an `ApiError` with
 * `status` `404` for a missing / cross-tenant / cross-session lead and `409` for a
 * lead that exists but is not `Converted`. The body is returned flat (no envelope).
 */
export async function getConversion(leadId: string): Promise<ConversionSummary> {
  return request<ConversionSummary>(
    "GET",
    `/api/leads/${leadId}/conversion`,
  );
}

/**
 * Convert a lead via `POST /api/leads/{id}/convert` (moves `Qualified → Converted`,
 * creating the household / contact / opportunities), unwrapping the `{ lead }`
 * envelope into the frozen masked lead. The body chooses the household mode and the
 * product lines to open opportunities for.
 */
export async function convertLead(
  leadId: string,
  convertLeadRequest: ConvertLeadRequest,
): Promise<MaskedLead> {
  const responseBody = await request<{ lead: MaskedLead }>(
    "POST",
    `/api/leads/${leadId}/convert`,
    convertLeadRequest,
  );
  return responseBody.lead;
}

/**
 * Reject a lead via `POST /api/leads/{id}/reject` (moves `Working → Rejected`),
 * unwrapping the `{ lead }` envelope. The optional free-text reason rides the body.
 */
export async function rejectLead(
  leadId: string,
  rejectLeadRequest: RejectLeadRequest,
): Promise<MaskedLead> {
  const responseBody = await request<{ lead: MaskedLead }>(
    "POST",
    `/api/leads/${leadId}/reject`,
    rejectLeadRequest,
  );
  return responseBody.lead;
}

/**
 * Resolve a flagged duplicate via `POST /api/leads/{id}/resolve-duplicate`,
 * unwrapping the `{ lead }` envelope. The body names the `link` / `new` / `reject`
 * action.
 */
export async function resolveDuplicate(
  leadId: string,
  resolveDuplicateRequest: ResolveDuplicateRequest,
): Promise<MaskedLead> {
  const responseBody = await request<{ lead: MaskedLead }>(
    "POST",
    `/api/leads/${leadId}/resolve-duplicate`,
    resolveDuplicateRequest,
  );
  return responseBody.lead;
}

/**
 * Unmask one field of a lead via `POST /api/leads/{id}/reveal`, returning the
 * `{ field, value }` body (the audited reveal seam runs server-side). The body
 * names which field to reveal; `value` is `null` when the field has no stored value.
 */
export function revealLeadField(
  leadId: string,
  revealLeadRequest: RevealLeadRequest,
): Promise<RevealLeadResponse> {
  return request<RevealLeadResponse>(
    "POST",
    `/api/leads/${leadId}/reveal`,
    revealLeadRequest,
  );
}
