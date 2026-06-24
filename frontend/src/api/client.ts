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
  CreateLeadRequest,
  DemoSessionResetResult,
  DemoSessionState,
  Identity,
  MaskedLead,
  PublicIntakeRequest,
  PublicIntakeResult,
  RejectLeadRequest,
  ResolveDuplicateRequest,
  RevealLeadRequest,
  RevealLeadResponse,
  Role,
  Tenant,
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
type HttpMethod = "GET" | "POST";

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
