// The single typed HTTP client every later frontend epic calls. It is a thin
// `fetch` wrapper that sends the `pf_session` cookie on every request
// (`credentials: "include"`) and exposes the four backend calls the demo shell
// needs, each returning its parsed, typed body.
//
// A failed call surfaces as a thrown, typed `ApiError` carrying the HTTP
// `status` (or `0` for a network drop) and a human-readable `message`. Callers
// use try/catch; Epic 4 will branch on `error.status === 401` to tell "signed
// out" from a real failure.

import type { Identity, Role, Tenant } from "./types";

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

/** Sign out via `POST /api/auth/logout`; the response body is ignored. */
export async function signOut(): Promise<void> {
  await request<{ detail: string }>("POST", "/api/auth/logout");
}
