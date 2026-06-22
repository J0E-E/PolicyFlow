// Tests for the authenticated lead detail page (Epic 21). jsdom has no backend, so
// `../api` is mocked: listTenants drives the product-line registry, getLead drives
// the lead (and the matched lead in the duplicate panel), and the action calls
// (revealLeadField / qualifyLead / rejectLead / resolveDuplicate) drive the
// controls. The page reads the session via `../session`, so that is mocked too —
// useSession returns a fixed agent identity and useCapability is driven per
// capability (reveal_pii, create_edit_records). The page reads `:id` from the route
// and renders react-router links, so it mounts inside a MemoryRouter + Routes at
// `/app/leads/:id`. Covers: loading, loaded view + masked PII, not-found (404),
// error + retry, the §6.4 reveal (happy path, Read-Only no control, absent field),
// qualify, reject with a reason, and the duplicate panel + resolve.

import { fireEvent, render, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import LeadDetailPage from "./LeadDetailPage.tsx";
import type { Capability, Identity, MaskedLead, Tenant } from "../api";

vi.mock("../api", () => ({
  listTenants: vi.fn(),
  getLead: vi.fn(),
  revealLeadField: vi.fn(),
  qualifyLead: vi.fn(),
  rejectLead: vi.fn(),
  resolveDuplicate: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.name = "ApiError";
      this.status = status;
    }
  },
}));

vi.mock("../session", () => ({
  useSession: vi.fn(),
  useCapability: vi.fn(),
}));

import {
  ApiError,
  getLead,
  listTenants,
  qualifyLead,
  rejectLead,
  resolveDuplicate,
  revealLeadField,
} from "../api";
import { useCapability, useSession } from "../session";

const listTenantsMock = vi.mocked(listTenants);
const getLeadMock = vi.mocked(getLead);
const revealLeadFieldMock = vi.mocked(revealLeadField);
const qualifyLeadMock = vi.mocked(qualifyLead);
const rejectLeadMock = vi.mocked(rejectLead);
const resolveDuplicateMock = vi.mocked(resolveDuplicate);
const useCapabilityMock = vi.mocked(useCapability);
const useSessionMock = vi.mocked(useSession);

const sunshineTenant: Tenant = {
  slug: "sunshine-senior-benefits",
  display_name: "Sunshine Senior Benefits",
  brand_primary_color: "#9C4A1E",
  product_lines: [
    { key: "medicare_advantage", label: "Medicare Advantage" },
    { key: "final_expense", label: "Final Expense" },
  ],
};

const agentIdentity: Identity = {
  user: {
    id: "11111111-1111-1111-1111-111111111111",
    username: "agent.one@sunshine.example",
    role: "agent",
    tenant_id: "22222222-2222-2222-2222-222222222222",
    tenant_slug: "sunshine-senior-benefits",
    tenant_name: "Sunshine Senior Benefits",
  },
  capabilities: ["create_edit_records", "claim_leads_manage_tasks", "reveal_pii"],
};

function makeLead(overrides: Partial<MaskedLead>): MaskedLead {
  return {
    id: "lead-1",
    first_name: "Maria",
    last_name: "Lopez",
    email: "m•••@example.com",
    phone: "•••-•••-0149",
    date_of_birth: "****-**-**",
    age_band: "65-74",
    zip_code: "33134",
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
    created_at: "2026-06-18T14:30:00Z",
    updated_at: "2026-06-18T14:30:00Z",
    is_seed: false,
    is_session_record: false,
    ...overrides,
  };
}

function sessionFor(identity: Identity) {
  return {
    status: "signed-in" as const,
    identity,
    capabilities: identity.capabilities,
    assumePersona: vi.fn(),
    signOut: vi.fn(),
  };
}

// Mount the page at `/app/leads/:id` so useParams resolves the lead id.
function renderPage(leadId = "lead-1") {
  return render(
    <MemoryRouter initialEntries={[`/app/leads/${leadId}`]}>
      <Routes>
        <Route path="/app/leads/:id" element={<LeadDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function capabilitySet(held: Capability[]) {
  return (capability: Capability) => held.includes(capability);
}

beforeEach(() => {
  listTenantsMock.mockReset();
  getLeadMock.mockReset();
  revealLeadFieldMock.mockReset();
  qualifyLeadMock.mockReset();
  rejectLeadMock.mockReset();
  resolveDuplicateMock.mockReset();
  useCapabilityMock.mockReset();
  useSessionMock.mockReset();
  useSessionMock.mockReturnValue(sessionFor(agentIdentity));
  useCapabilityMock.mockImplementation(
    capabilitySet(["create_edit_records", "claim_leads_manage_tasks", "reveal_pii"]),
  );
  listTenantsMock.mockResolvedValue([sunshineTenant]);
  getLeadMock.mockResolvedValue(makeLead({}));
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("LeadDetailPage loading + loaded view", () => {
  it("shows a loading state while the reads are in flight", async () => {
    renderPage();
    expect(document.getElementById("lead-detail-loading")).toBeInTheDocument();
    // Let the in-flight reads settle so their state updates land inside act().
    await waitFor(() => {
      expect(document.getElementById("lead-detail-title")).toBeInTheDocument();
    });
  });

  it("renders the header, masked contact, and lead details once loaded", async () => {
    getLeadMock.mockResolvedValue(
      makeLead({
        notes: "Prefers mornings.",
        preferred_contact_method: "phone",
      }),
    );
    renderPage();

    await waitFor(() => {
      expect(document.getElementById("lead-detail-title")).toBeInTheDocument();
    });

    expect(document.getElementById("lead-detail-title")).toHaveTextContent(
      "Maria Lopez",
    );
    expect(
      document.getElementById("lead-detail-status-stamp-label"),
    ).toHaveTextContent("New");
    expect(document.getElementById("lead-detail-id")).toHaveTextContent("lead-1");
    // The masked email shows behind the lock, not revealed.
    expect(document.getElementById("lead-detail-email-value")).toHaveTextContent(
      "m•••@example.com",
    );
    // Coverage maps the key to its label; preferred-contact maps to its label.
    expect(
      document.getElementById("lead-detail-coverage-content"),
    ).toHaveTextContent("Medicare Advantage");
    expect(
      document.getElementById("lead-detail-preferred-contact-content"),
    ).toHaveTextContent("Phone call");
    expect(
      document.getElementById("lead-detail-notes-content"),
    ).toHaveTextContent("Prefers mornings.");
  });

  it("shows a not-found state for a missing or cross-tenant lead (404)", async () => {
    getLeadMock.mockRejectedValue(new ApiError(404, "lead not found"));
    renderPage();

    await waitFor(() => {
      expect(document.getElementById("lead-detail-not-found")).toBeInTheDocument();
    });
    expect(document.getElementById("lead-detail-not-found-back")).toHaveAttribute(
      "href",
      "/app/leads",
    );
  });

  it("shows a retryable error for a non-404 failure", async () => {
    getLeadMock.mockRejectedValueOnce(new ApiError(500, "boom"));
    renderPage();

    await waitFor(() => {
      expect(document.getElementById("lead-detail-error")).toBeInTheDocument();
    });

    // Retry refetches; the lead resolves the second time.
    getLeadMock.mockResolvedValueOnce(makeLead({}));
    fireEvent.click(
      document.getElementById("lead-detail-error-retry-button")!,
    );
    await waitFor(() => {
      expect(document.getElementById("lead-detail-title")).toBeInTheDocument();
    });
  });

  it("renders an absent street address as 'Not provided' with no reveal control", async () => {
    getLeadMock.mockResolvedValue(makeLead({ street_address: null }));
    renderPage();

    await waitFor(() => {
      expect(document.getElementById("lead-detail-title")).toBeInTheDocument();
    });
    expect(
      document.getElementById("lead-detail-street-address-absent"),
    ).toHaveTextContent("Not provided");
    expect(
      document.getElementById("lead-detail-street-address-unseal"),
    ).toBeNull();
  });
});

describe("LeadDetailPage PII reveal (§6.4)", () => {
  it("reveals a field through the inline confirm and marks it audited", async () => {
    revealLeadFieldMock.mockResolvedValue({
      field: "email",
      value: "maria.lopez@example.com",
    });
    renderPage();

    await waitFor(() => {
      expect(document.getElementById("lead-detail-email-unseal")).toBeInTheDocument();
    });

    // Open the confirm, then confirm.
    fireEvent.click(document.getElementById("lead-detail-email-unseal")!);
    expect(document.getElementById("lead-detail-email-confirm")).toBeInTheDocument();
    fireEvent.click(document.getElementById("lead-detail-email-confirm-button")!);

    await waitFor(() => {
      expect(
        document.getElementById("lead-detail-email-revealed-value"),
      ).toBeInTheDocument();
    });
    expect(
      document.getElementById("lead-detail-email-revealed-value"),
    ).toHaveTextContent("maria.lopez@example.com");
    expect(
      document.getElementById("lead-detail-email-revealed-marker"),
    ).toHaveTextContent("revealed — audited");
    expect(revealLeadFieldMock).toHaveBeenCalledWith("lead-1", { field: "email" });
  });

  it("hides the reveal control for a viewer without reveal_pii (Read-Only)", async () => {
    useCapabilityMock.mockImplementation(capabilitySet(["view_tenant_records"]));
    renderPage();

    await waitFor(() => {
      expect(document.getElementById("lead-detail-email-value")).toBeInTheDocument();
    });
    expect(document.getElementById("lead-detail-email-unseal")).toBeNull();
  });
});

describe("LeadDetailPage qualify / reject actions", () => {
  it("shows no qualify/reject section for a non-Working lead", async () => {
    getLeadMock.mockResolvedValue(makeLead({ status: "New" }));
    renderPage();

    await waitFor(() => {
      expect(document.getElementById("lead-detail-title")).toBeInTheDocument();
    });
    expect(document.getElementById("lead-detail-actions")).toBeNull();
  });

  it("qualifies a Working lead and flips the status stamp", async () => {
    getLeadMock.mockResolvedValue(makeLead({ status: "Working" }));
    qualifyLeadMock.mockResolvedValue(makeLead({ status: "Qualified" }));
    renderPage();

    await waitFor(() => {
      expect(document.getElementById("lead-detail-qualify-button")).toBeInTheDocument();
    });
    fireEvent.click(document.getElementById("lead-detail-qualify-button")!);

    await waitFor(() => {
      expect(
        document.getElementById("lead-detail-status-stamp-label"),
      ).toHaveTextContent("Qualified");
    });
    expect(qualifyLeadMock).toHaveBeenCalledWith("lead-1");
    // The section is gone — the lead is no longer Working.
    expect(document.getElementById("lead-detail-actions")).toBeNull();
  });

  it("rejects a Working lead with a reason", async () => {
    getLeadMock.mockResolvedValue(makeLead({ status: "Working" }));
    rejectLeadMock.mockResolvedValue(
      makeLead({ status: "Rejected", rejection_reason: "Out of area." }),
    );
    renderPage();

    await waitFor(() => {
      expect(document.getElementById("lead-detail-reject-button")).toBeInTheDocument();
    });
    // Open the inline reject form, type a reason, confirm.
    fireEvent.click(document.getElementById("lead-detail-reject-button")!);
    fireEvent.change(document.getElementById("lead-detail-reject-reason")!, {
      target: { value: "Out of area." },
    });
    fireEvent.click(document.getElementById("lead-detail-reject-confirm-button")!);

    await waitFor(() => {
      expect(
        document.getElementById("lead-detail-status-stamp-label"),
      ).toHaveTextContent("Rejected");
    });
    expect(rejectLeadMock).toHaveBeenCalledWith("lead-1", {
      reason: "Out of area.",
    });
    // The rejection reason now shows on the details card.
    expect(
      document.getElementById("lead-detail-rejection-reason-content"),
    ).toHaveTextContent("Out of area.");
  });

  it("hides the actions section for a viewer without create_edit_records", async () => {
    getLeadMock.mockResolvedValue(makeLead({ status: "Working" }));
    useCapabilityMock.mockImplementation(capabilitySet(["view_tenant_records"]));
    renderPage();

    await waitFor(() => {
      expect(document.getElementById("lead-detail-title")).toBeInTheDocument();
    });
    expect(document.getElementById("lead-detail-actions")).toBeNull();
  });
});

describe("LeadDetailPage duplicate panel", () => {
  it("shows the duplicate panel with the matched lead and resolve controls", async () => {
    // The flagged lead is fetched first, then its match.
    getLeadMock.mockImplementation((id: string) => {
      if (id === "lead-1") {
        return Promise.resolve(
          makeLead({
            id: "lead-1",
            status: "New",
            duplicate_of_lead_id: "prior-lead",
            duplicate_resolution: null,
          }),
        );
      }
      return Promise.resolve(
        makeLead({
          id: "prior-lead",
          first_name: "Jordan",
          last_name: "Rivera",
          status: "Working",
          created_at: "2026-06-10T08:00:00Z",
        }),
      );
    });
    renderPage();

    await waitFor(() => {
      expect(
        document.getElementById("lead-detail-duplicate-panel"),
      ).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(
        document.getElementById("lead-detail-duplicate-match-name"),
      ).toHaveTextContent("Jordan Rivera");
    });
    expect(
      document.getElementById("lead-detail-duplicate-match-view"),
    ).toHaveAttribute("href", "/app/leads/prior-lead");
    // A New flagged lead can be rejected as a duplicate.
    expect(
      document.getElementById("lead-detail-duplicate-reject-button"),
    ).toBeInTheDocument();
  });

  it("resolves the duplicate as new and clears the flag", async () => {
    getLeadMock.mockImplementation((id: string) => {
      if (id === "lead-1") {
        return Promise.resolve(
          makeLead({
            id: "lead-1",
            duplicate_of_lead_id: "prior-lead",
            duplicate_resolution: null,
          }),
        );
      }
      return Promise.resolve(makeLead({ id: "prior-lead" }));
    });
    resolveDuplicateMock.mockResolvedValue(
      makeLead({
        id: "lead-1",
        duplicate_of_lead_id: null,
        duplicate_resolution: "new",
      }),
    );
    renderPage();

    await waitFor(() => {
      expect(
        document.getElementById("lead-detail-duplicate-new-button"),
      ).toBeInTheDocument();
    });
    fireEvent.click(document.getElementById("lead-detail-duplicate-new-button")!);

    await waitFor(() => {
      expect(
        document.getElementById("lead-detail-duplicate-panel"),
      ).toBeNull();
    });
    expect(resolveDuplicateMock).toHaveBeenCalledWith("lead-1", { action: "new" });
  });
});

describe("LeadDetailPage demo-session markers (Epic 6)", () => {
  it("marks the visitor's own record with a neutral YOUR SESSION header stamp", async () => {
    getLeadMock.mockResolvedValue(makeLead({ is_session_record: true }));
    renderPage();

    await waitFor(() => {
      expect(document.getElementById("lead-detail-title")).toBeInTheDocument();
    });
    expect(
      document.getElementById("lead-detail-session-stamp-label"),
    ).toHaveTextContent("Your session");
    expect(document.getElementById("lead-detail-seed-stamp")).toBeNull();
  });

  it("marks a shared seed row SHARED SAMPLE (with a tooltip) in the header", async () => {
    getLeadMock.mockResolvedValue(makeLead({ is_seed: true }));
    renderPage();

    await waitFor(() => {
      expect(document.getElementById("lead-detail-title")).toBeInTheDocument();
    });
    expect(
      document.getElementById("lead-detail-seed-stamp-label"),
    ).toHaveTextContent("Shared sample");
    expect(document.getElementById("lead-detail-seed-stamp")).toHaveAttribute(
      "title",
      "Shared sample data — visible to every visitor, not editable",
    );
    expect(document.getElementById("lead-detail-session-stamp")).toBeNull();
  });

  it("hides qualify/reject on a seed row but keeps the reveal control", async () => {
    getLeadMock.mockResolvedValue(makeLead({ status: "Working", is_seed: true }));
    renderPage();

    await waitFor(() => {
      expect(document.getElementById("lead-detail-title")).toBeInTheDocument();
    });
    // The mutating actions are gone on a read-only shared seed row...
    expect(document.getElementById("lead-detail-actions")).toBeNull();
    // ...but reveal stays (it is a read — Epic 5 contract).
    expect(
      document.getElementById("lead-detail-email-unseal"),
    ).toBeInTheDocument();
  });

  it("hides the duplicate resolve controls on a seed row (panel still shows)", async () => {
    getLeadMock.mockImplementation((id: string) => {
      if (id === "lead-1") {
        return Promise.resolve(
          makeLead({
            id: "lead-1",
            status: "New",
            is_seed: true,
            duplicate_of_lead_id: "prior-lead",
            duplicate_resolution: null,
          }),
        );
      }
      return Promise.resolve(makeLead({ id: "prior-lead" }));
    });
    renderPage();

    await waitFor(() => {
      expect(
        document.getElementById("lead-detail-duplicate-panel"),
      ).toBeInTheDocument();
    });
    // The match still renders, but no resolve controls on a seed row.
    expect(
      document.getElementById("lead-detail-duplicate-actions"),
    ).toBeNull();
    expect(
      document.getElementById("lead-detail-duplicate-new-button"),
    ).toBeNull();
  });
});
