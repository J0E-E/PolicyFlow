// Unit tests for the typed API client. jsdom has no backend, so every test
// mocks `globalThis.fetch` via `vi.stubGlobal` and asserts the client sends the
// right method/path/credentials/body and parses (or unwraps) the response —
// plus the typed-error behavior for non-2xx and network failures.

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  assumePersona,
  claimLead,
  convertLead,
  getConversion,
  getHouseholds,
  createLead,
  getCurrentIdentity,
  getLead,
  listLeads,
  listTenants,
  qualifyLead,
  rejectLead,
  resolveDuplicate,
  revealLeadField,
  signOut,
  submitPublicIntake,
} from "./client";
import type {
  CreateLeadRequest,
  Identity,
  MaskedLead,
  PublicIntakeRequest,
  RevealLeadResponse,
  Tenant,
} from "./types";

const sampleIdentity: Identity = {
  user: {
    id: "11111111-1111-1111-1111-111111111111",
    username: "agent.one",
    role: "agent",
    tenant_id: "22222222-2222-2222-2222-222222222222",
    tenant_slug: "sunshine-senior-benefits",
    tenant_name: "Sunshine Senior Benefits",
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
    product_lines: [
      { key: "medicare_advantage", label: "Medicare Advantage" },
      { key: "final_expense", label: "Final Expense" },
    ],
  },
  {
    slug: "florida",
    display_name: "Florida Mutual",
    brand_primary_color: "#0F6A72",
    product_lines: [{ key: "term_life", label: "Term Life" }],
  },
];

const sampleMaskedLead: MaskedLead = {
  id: "33333333-3333-3333-3333-333333333333",
  first_name: "Jordan",
  last_name: "Rivera",
  email: "j****@example.com",
  phone: "***-***-0188",
  date_of_birth: "****-**-**",
  age_band: "65-74",
  zip_code: "32801",
  street_address: "***",
  product_lines_of_interest: ["medicare_advantage"],
  preferred_contact_method: "email",
  notes: null,
  rejection_reason: null,
  lead_source: "public_form",
  status: "New",
  owner_user_id: null,
  owner_username: null,
  duplicate_of_lead_id: null,
  duplicate_resolution: null,
  created_at: "2026-06-20T12:00:00Z",
  updated_at: "2026-06-20T12:00:00Z",
  is_seed: false,
  is_session_record: false,
};

const sampleCreateLeadRequest: CreateLeadRequest = {
  first_name: "Jordan",
  last_name: "Rivera",
  email: "jordan.rivera@example.com",
  phone: "(407) 555-0188",
  date_of_birth: "1958-06-15",
  zip_code: "32801",
  product_lines_of_interest: ["medicare_advantage"],
  street_address: "742 Marina Bay Drive",
  preferred_contact_method: "email",
  notes: null,
};

const samplePublicIntakeRequest: PublicIntakeRequest = {
  tenant_slug: "sunshine",
  website: "",
  first_name: "Jordan",
  last_name: "Rivera",
  email: "jordan.rivera@example.com",
  phone: "(407) 555-0188",
  date_of_birth: "1958-06-15",
  zip_code: "32801",
  product_lines_of_interest: ["medicare_advantage"],
};

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

describe("lead client calls", () => {
  it("createLead POSTs /api/leads with the body and unwraps { lead }", async () => {
    vi.stubGlobal("fetch", mockJsonResponse({ lead: sampleMaskedLead }));

    const lead = await createLead(sampleCreateLeadRequest);

    const [url, options] = lastFetchCall();
    expect(url).toBe("/api/leads");
    expect(options.method).toBe("POST");
    expect(options.credentials).toBe("include");
    expect(options.headers).toEqual({ "Content-Type": "application/json" });
    expect(JSON.parse(options.body as string)).toEqual(sampleCreateLeadRequest);
    expect(lead).toEqual(sampleMaskedLead);
  });

  it("submitPublicIntake POSTs /api/public/intake with the body and returns { ok }", async () => {
    vi.stubGlobal("fetch", mockJsonResponse({ ok: true }));

    const result = await submitPublicIntake(samplePublicIntakeRequest);

    const [url, options] = lastFetchCall();
    expect(url).toBe("/api/public/intake");
    expect(options.method).toBe("POST");
    expect(options.credentials).toBe("include");
    expect(JSON.parse(options.body as string)).toEqual(
      samplePublicIntakeRequest,
    );
    expect(result).toEqual({ ok: true });
  });

  it("listLeads GETs /api/leads (no query) and unwraps { leads } by default", async () => {
    vi.stubGlobal("fetch", mockJsonResponse({ leads: [sampleMaskedLead] }));

    const leads = await listLeads();

    const [url, options] = lastFetchCall();
    expect(url).toBe("/api/leads");
    expect(options.method).toBe("GET");
    expect(options.credentials).toBe("include");
    expect(leads).toEqual([sampleMaskedLead]);
  });

  it("listLeads appends ?unassigned=true only when unassigned is true", async () => {
    vi.stubGlobal("fetch", mockJsonResponse({ leads: [sampleMaskedLead] }));

    await listLeads(true);

    const [url] = lastFetchCall();
    expect(url).toBe("/api/leads?unassigned=true");
  });

  it("listLeads omits the query when unassigned is false", async () => {
    vi.stubGlobal("fetch", mockJsonResponse({ leads: [] }));

    await listLeads(false);

    const [url] = lastFetchCall();
    expect(url).toBe("/api/leads");
  });

  it("getLead GETs /api/leads/{id} and unwraps { lead }", async () => {
    vi.stubGlobal("fetch", mockJsonResponse({ lead: sampleMaskedLead }));

    const lead = await getLead(sampleMaskedLead.id);

    const [url, options] = lastFetchCall();
    expect(url).toBe(`/api/leads/${sampleMaskedLead.id}`);
    expect(options.method).toBe("GET");
    expect(options.credentials).toBe("include");
    expect(options.body).toBeUndefined();
    expect(lead).toEqual(sampleMaskedLead);
  });

  it("claimLead POSTs /api/leads/{id}/claim and unwraps { lead }", async () => {
    vi.stubGlobal("fetch", mockJsonResponse({ lead: sampleMaskedLead }));

    const lead = await claimLead(sampleMaskedLead.id);

    const [url, options] = lastFetchCall();
    expect(url).toBe(`/api/leads/${sampleMaskedLead.id}/claim`);
    expect(options.method).toBe("POST");
    expect(options.credentials).toBe("include");
    expect(options.body).toBeUndefined();
    expect(lead).toEqual(sampleMaskedLead);
  });

  it("qualifyLead POSTs /api/leads/{id}/qualify and unwraps { lead }", async () => {
    vi.stubGlobal("fetch", mockJsonResponse({ lead: sampleMaskedLead }));

    const lead = await qualifyLead(sampleMaskedLead.id);

    const [url, options] = lastFetchCall();
    expect(url).toBe(`/api/leads/${sampleMaskedLead.id}/qualify`);
    expect(options.method).toBe("POST");
    expect(options.credentials).toBe("include");
    expect(options.body).toBeUndefined();
    expect(lead).toEqual(sampleMaskedLead);
  });

  it("rejectLead POSTs /api/leads/{id}/reject with the reason body and unwraps { lead }", async () => {
    vi.stubGlobal("fetch", mockJsonResponse({ lead: sampleMaskedLead }));

    const lead = await rejectLead(sampleMaskedLead.id, { reason: "not a fit" });

    const [url, options] = lastFetchCall();
    expect(url).toBe(`/api/leads/${sampleMaskedLead.id}/reject`);
    expect(options.method).toBe("POST");
    expect(options.credentials).toBe("include");
    expect(JSON.parse(options.body as string)).toEqual({ reason: "not a fit" });
    expect(lead).toEqual(sampleMaskedLead);
  });

  it("getHouseholds GETs /api/households with the encoded query and unwraps { households }", async () => {
    const households = [
      {
        id: "household-1",
        name: "Lopez Household",
        members: [{ first_name: "Maria", last_name: "Lopez" }],
      },
    ];
    vi.stubGlobal("fetch", mockJsonResponse({ households }));

    const result = await getHouseholds("Lo pez");

    const [url, options] = lastFetchCall();
    expect(url).toBe("/api/households?q=Lo%20pez");
    expect(options.method).toBe("GET");
    expect(options.credentials).toBe("include");
    expect(result).toEqual(households);
  });

  it("getConversion GETs /api/leads/{id}/conversion and returns the flat summary", async () => {
    const summary = {
      contact: { id: "contact-1", first_name: "Maria", last_name: "Lopez" },
      household: { id: "household-1", name: "Lopez Household" },
      opportunities: [
        { id: "opp-1", product_line: "medicare_advantage", stage: "New" },
      ],
    };
    vi.stubGlobal("fetch", mockJsonResponse(summary));

    const result = await getConversion(sampleMaskedLead.id);

    const [url, options] = lastFetchCall();
    expect(url).toBe(`/api/leads/${sampleMaskedLead.id}/conversion`);
    expect(options.method).toBe("GET");
    expect(options.credentials).toBe("include");
    expect(result).toEqual(summary);
  });

  it("convertLead POSTs /api/leads/{id}/convert with the household + product lines and unwraps { lead }", async () => {
    vi.stubGlobal("fetch", mockJsonResponse({ lead: sampleMaskedLead }));

    const lead = await convertLead(sampleMaskedLead.id, {
      household: { mode: "new" },
      product_lines: ["medicare_advantage"],
    });

    const [url, options] = lastFetchCall();
    expect(url).toBe(`/api/leads/${sampleMaskedLead.id}/convert`);
    expect(options.method).toBe("POST");
    expect(options.credentials).toBe("include");
    expect(JSON.parse(options.body as string)).toEqual({
      household: { mode: "new" },
      product_lines: ["medicare_advantage"],
    });
    expect(lead).toEqual(sampleMaskedLead);
  });

  it("resolveDuplicate POSTs /api/leads/{id}/resolve-duplicate with the action and unwraps { lead }", async () => {
    vi.stubGlobal("fetch", mockJsonResponse({ lead: sampleMaskedLead }));

    const lead = await resolveDuplicate(sampleMaskedLead.id, { action: "link" });

    const [url, options] = lastFetchCall();
    expect(url).toBe(`/api/leads/${sampleMaskedLead.id}/resolve-duplicate`);
    expect(options.method).toBe("POST");
    expect(options.credentials).toBe("include");
    expect(JSON.parse(options.body as string)).toEqual({ action: "link" });
    expect(lead).toEqual(sampleMaskedLead);
  });

  it("revealLeadField POSTs /api/leads/{id}/reveal and returns the { field, value } body", async () => {
    const revealed: RevealLeadResponse = {
      field: "email",
      value: "jordan.rivera@example.com",
    };
    vi.stubGlobal("fetch", mockJsonResponse(revealed));

    const result = await revealLeadField(sampleMaskedLead.id, {
      field: "email",
    });

    const [url, options] = lastFetchCall();
    expect(url).toBe(`/api/leads/${sampleMaskedLead.id}/reveal`);
    expect(options.method).toBe("POST");
    expect(options.credentials).toBe("include");
    expect(JSON.parse(options.body as string)).toEqual({ field: "email" });
    expect(result).toEqual(revealed);
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
