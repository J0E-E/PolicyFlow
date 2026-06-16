// Unit tests for the typed API client. jsdom has no backend, so every test
// mocks `globalThis.fetch` via `vi.stubGlobal` and asserts the client sends the
// right method/path/credentials/body and parses (or unwraps) the response —
// plus the typed-error behavior for non-2xx and network failures.

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  assumePersona,
  getCurrentIdentity,
  listTenants,
  signOut,
} from "./client";
import type { Identity, Tenant } from "./types";

const sampleIdentity: Identity = {
  user: {
    id: "11111111-1111-1111-1111-111111111111",
    username: "agent.one",
    role: "agent",
    tenant_id: "22222222-2222-2222-2222-222222222222",
  },
  capabilities: [
    "claim_leads_manage_tasks",
    "create_edit_records",
    "reveal_pii",
    "view_dashboards",
    "view_tenant_records",
  ],
};

const sampleTenants: Tenant[] = [
  {
    slug: "sunshine",
    display_name: "Sunshine Insurance",
    brand_primary_color: "#9C4A1E",
  },
  {
    slug: "florida",
    display_name: "Florida Mutual",
    brand_primary_color: "#0F6A72",
  },
];

/** Build a stub `fetch` that resolves to a 2xx JSON response carrying `body`. */
function mockJsonResponse(body: unknown): typeof fetch {
  return vi.fn(async () => {
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }) as unknown as typeof fetch;
}

/** Build a stub `fetch` that resolves to a non-2xx response carrying `body`. */
function mockErrorResponse(
  status: number,
  body: unknown,
  statusText = "",
): typeof fetch {
  return vi.fn(async () => {
    return new Response(JSON.stringify(body), {
      status,
      statusText,
      headers: { "Content-Type": "application/json" },
    });
  }) as unknown as typeof fetch;
}

/** Read back the `[url, options]` of the most recent stubbed `fetch` call. */
function lastFetchCall(): [string, RequestInit] {
  const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
  const call = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
  return [call[0] as string, call[1] as RequestInit];
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("happy-path requests", () => {
  it("getCurrentIdentity GETs /api/auth/me with credentials and returns the body", async () => {
    vi.stubGlobal("fetch", mockJsonResponse(sampleIdentity));

    const identity = await getCurrentIdentity();

    const [url, options] = lastFetchCall();
    expect(url).toBe("/api/auth/me");
    expect(options.method).toBe("GET");
    expect(options.credentials).toBe("include");
    expect(options.body).toBeUndefined();
    expect(identity).toEqual(sampleIdentity);
  });

  it("listTenants GETs /api/tenants and unwraps the { tenants } envelope", async () => {
    vi.stubGlobal("fetch", mockJsonResponse({ tenants: sampleTenants }));

    const tenants = await listTenants();

    const [url, options] = lastFetchCall();
    expect(url).toBe("/api/tenants");
    expect(options.method).toBe("GET");
    expect(options.credentials).toBe("include");
    expect(tenants).toEqual(sampleTenants);
  });

  it("assumePersona POSTs the JSON body with snake_case tenant_slug and header", async () => {
    vi.stubGlobal("fetch", mockJsonResponse(sampleIdentity));

    const identity = await assumePersona("sunshine", "agent");

    const [url, options] = lastFetchCall();
    expect(url).toBe("/api/demo/assume-persona");
    expect(options.method).toBe("POST");
    expect(options.credentials).toBe("include");
    expect(options.headers).toEqual({ "Content-Type": "application/json" });
    expect(JSON.parse(options.body as string)).toEqual({
      tenant_slug: "sunshine",
      role: "agent",
    });
    expect(identity).toEqual(sampleIdentity);
  });

  it("signOut POSTs /api/auth/logout and resolves to void", async () => {
    vi.stubGlobal("fetch", mockJsonResponse({ detail: "logged out" }));

    const result = await signOut();

    const [url, options] = lastFetchCall();
    expect(url).toBe("/api/auth/logout");
    expect(options.method).toBe("POST");
    expect(options.credentials).toBe("include");
    expect(result).toBeUndefined();
  });
});

describe("typed error handling", () => {
  it("a 401 throws ApiError with status 401 and the detail message", async () => {
    vi.stubGlobal("fetch", mockErrorResponse(401, { detail: "not signed in" }));

    await expect(getCurrentIdentity()).rejects.toMatchObject({
      status: 401,
      message: "not signed in",
    });
  });

  it("a 403 throws ApiError with status 403 and the detail message", async () => {
    vi.stubGlobal(
      "fetch",
      mockErrorResponse(403, { detail: "demo login is disabled" }),
    );

    await expect(assumePersona("sunshine", "agent")).rejects.toMatchObject({
      status: 403,
      message: "demo login is disabled",
    });
  });

  it("a 404 throws ApiError with status 404 and the detail message", async () => {
    vi.stubGlobal("fetch", mockErrorResponse(404, { detail: "unknown tenant" }));

    await expect(assumePersona("nope", "agent")).rejects.toMatchObject({
      status: 404,
      message: "unknown tenant",
    });
  });

  it("a 422 with an array detail falls back to the status text", async () => {
    vi.stubGlobal(
      "fetch",
      mockErrorResponse(
        422,
        { detail: [{ loc: ["body", "role"], msg: "bad role" }] },
        "Unprocessable Entity",
      ),
    );

    await expect(assumePersona("sunshine", "agent")).rejects.toMatchObject({
      status: 422,
      message: "Unprocessable Entity",
    });
  });

  it("a non-JSON error body falls back to the status text", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        return new Response("<html>oops</html>", {
          status: 500,
          statusText: "Internal Server Error",
        });
      }) as unknown as typeof fetch,
    );

    await expect(getCurrentIdentity()).rejects.toMatchObject({
      status: 500,
      message: "Internal Server Error",
    });
  });

  it("a network failure throws ApiError with status 0", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }) as unknown as typeof fetch,
    );

    await expect(getCurrentIdentity()).rejects.toMatchObject({
      status: 0,
      message: "network request failed",
    });
  });

  it("a thrown ApiError is an instanceof Error and ApiError", async () => {
    vi.stubGlobal("fetch", mockErrorResponse(401, { detail: "not signed in" }));

    const thrownError = await getCurrentIdentity().catch((error) => error);
    expect(thrownError).toBeInstanceOf(Error);
    expect(thrownError).toBeInstanceOf(ApiError);
    expect(thrownError.name).toBe("ApiError");
  });
});
