// Tests for the review-and-confirm convert screen (P2.1 Epic 6). jsdom has no
// backend, so `../api` is mocked: getLead drives the lead, listTenants the
// product-line labels, convertLead the commit. The page reads the session via
// `../session` (a fixed agent identity + per-capability), and reads `:id` from the
// route, so it mounts inside a MemoryRouter + Routes at `/app/leads/:id/convert` with
// a sibling `/app/leads/:id` route as the post-convert navigation target.

import { fireEvent, render, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ConvertLeadPage from "./ConvertLeadPage.tsx";
import type { Capability, Identity, MaskedLead, Tenant } from "../api";

vi.mock("../api", () => ({
  getLead: vi.fn(),
  listTenants: vi.fn(),
  convertLead: vi.fn(),
  getHouseholds: vi.fn(),
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

import { convertLead, getHouseholds, getLead, listTenants } from "../api";
import { useCapability, useSession } from "../session";

const getLeadMock = vi.mocked(getLead);
const listTenantsMock = vi.mocked(listTenants);
const convertLeadMock = vi.mocked(convertLead);
const getHouseholdsMock = vi.mocked(getHouseholds);
const useCapabilityMock = vi.mocked(useCapability);
const useSessionMock = vi.mocked(useSession);

const AGENT_USER_ID = "11111111-1111-1111-1111-111111111111";

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
    id: AGENT_USER_ID,
    username: "agent.one@sunshine.example",
    role: "agent",
    tenant_id: "22222222-2222-2222-2222-222222222222",
    tenant_slug: "sunshine-senior-benefits",
    tenant_name: "Sunshine Senior Benefits",
  },
  capabilities: ["create_edit_records", "reveal_pii"],
};

function makeLead(overrides: Partial<MaskedLead> = {}): MaskedLead {
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
    status: "Qualified",
    owner_user_id: AGENT_USER_ID,
    owner_username: "agent.one@sunshine.example",
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

function capabilitySet(held: Capability[]) {
  return (capability: Capability) => held.includes(capability);
}

function renderPage(leadId = "lead-1") {
  return render(
    <MemoryRouter initialEntries={[`/app/leads/${leadId}/convert`]}>
      <Routes>
        <Route path="/app/leads/:id/convert" element={<ConvertLeadPage />} />
        <Route
          path="/app/leads/:id"
          element={<div data-testid="lead-detail">frozen lead detail</div>}
        />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  getLeadMock.mockReset();
  listTenantsMock.mockReset();
  convertLeadMock.mockReset();
  getHouseholdsMock.mockReset();
  useCapabilityMock.mockReset();
  useSessionMock.mockReset();
  useSessionMock.mockReturnValue(sessionFor(agentIdentity));
  useCapabilityMock.mockImplementation(capabilitySet(["create_edit_records", "reveal_pii"]));
  listTenantsMock.mockResolvedValue([sunshineTenant]);
  getLeadMock.mockResolvedValue(makeLead());
  getHouseholdsMock.mockResolvedValue([]);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("ConvertLeadPage", () => {
  it("renders the contact summary and pre-selects the lead's product lines", async () => {
    renderPage();

    await waitFor(() => {
      expect(document.getElementById("convert-lead-commit-button")).toBeInTheDocument();
    });
    expect(document.getElementById("convert-lead-contact-name")).toHaveTextContent(
      "Maria Lopez",
    );
    // The lead's own line is pre-checked; the other tenant line is not.
    expect(
      document.getElementById("convert-lead-product-lines-option-medicare_advantage"),
    ).toBeChecked();
    expect(
      document.getElementById("convert-lead-product-lines-option-final_expense"),
    ).not.toBeChecked();
  });

  it("commits with the selected lines and navigates to the frozen lead", async () => {
    convertLeadMock.mockResolvedValue(makeLead({ status: "Converted" }));
    renderPage();

    await waitFor(() => {
      expect(document.getElementById("convert-lead-commit-button")).toBeInTheDocument();
    });
    // Add the second product line, then commit.
    fireEvent.click(
      document.getElementById("convert-lead-product-lines-option-final_expense")!,
    );
    fireEvent.click(document.getElementById("convert-lead-commit-button")!);

    await waitFor(() => {
      expect(document.querySelector('[data-testid="lead-detail"]')).toBeInTheDocument();
    });
    expect(convertLeadMock).toHaveBeenCalledWith("lead-1", {
      household: { mode: "new" },
      product_lines: ["medicare_advantage", "final_expense"],
    });
  });

  it("blocks the commit when no product line is selected", async () => {
    renderPage();

    await waitFor(() => {
      expect(document.getElementById("convert-lead-commit-button")).toBeInTheDocument();
    });
    // Uncheck the only pre-selected line — the commit is now disabled.
    fireEvent.click(
      document.getElementById("convert-lead-product-lines-option-medicare_advantage")!,
    );

    expect(document.getElementById("convert-lead-commit-button")).toBeDisabled();
    expect(
      document.getElementById("convert-lead-product-lines-error"),
    ).toBeInTheDocument();
    expect(convertLeadMock).not.toHaveBeenCalled();
  });

  it("shows an ineligible notice for a lead that is not Qualified", async () => {
    getLeadMock.mockResolvedValue(makeLead({ status: "Working" }));
    renderPage();

    await waitFor(() => {
      expect(document.getElementById("convert-lead-ineligible")).toBeInTheDocument();
    });
    expect(document.getElementById("convert-lead-commit-button")).toBeNull();
  });

  it("shows an ineligible notice when the caller is not the holder", async () => {
    getLeadMock.mockResolvedValue(makeLead({ owner_user_id: "someone-else" }));
    renderPage();

    await waitFor(() => {
      expect(document.getElementById("convert-lead-ineligible")).toBeInTheDocument();
    });
    expect(document.getElementById("convert-lead-commit-button")).toBeNull();
  });

  it("links to a searched household and commits with the link choice", async () => {
    convertLeadMock.mockResolvedValue(makeLead({ status: "Converted" }));
    getHouseholdsMock.mockResolvedValue([
      {
        id: "household-7",
        name: "Garcia Household",
        members: [{ first_name: "Ana", last_name: "Garcia" }],
      },
    ]);
    renderPage();

    await waitFor(() => {
      expect(document.getElementById("convert-lead-commit-button")).toBeInTheDocument();
    });
    // Switch to link mode, search, and pick the match.
    fireEvent.click(document.getElementById("convert-lead-household-link")!);
    fireEvent.change(document.getElementById("convert-lead-household-search")!, {
      target: { value: "Garcia" },
    });
    await waitFor(() => {
      expect(
        document.getElementById("convert-lead-household-option-household-7"),
      ).toBeInTheDocument();
    });
    fireEvent.click(
      document.getElementById("convert-lead-household-option-household-7")!,
    );
    fireEvent.click(document.getElementById("convert-lead-commit-button")!);

    await waitFor(() => {
      expect(document.querySelector('[data-testid="lead-detail"]')).toBeInTheDocument();
    });
    expect(convertLeadMock).toHaveBeenCalledWith("lead-1", {
      household: { mode: "link", household_id: "household-7" },
      product_lines: ["medicare_advantage"],
    });
  });

  it("blocks the commit in link mode until a household is picked", async () => {
    renderPage();

    await waitFor(() => {
      expect(document.getElementById("convert-lead-commit-button")).toBeInTheDocument();
    });
    // New mode commits freely; switching to link with nothing picked disables commit.
    expect(document.getElementById("convert-lead-commit-button")).not.toBeDisabled();
    fireEvent.click(document.getElementById("convert-lead-household-link")!);
    expect(document.getElementById("convert-lead-commit-button")).toBeDisabled();
  });

  it("surfaces an inline error and stays on the page when the commit fails", async () => {
    convertLeadMock.mockRejectedValue(new Error("boom"));
    renderPage();

    await waitFor(() => {
      expect(document.getElementById("convert-lead-commit-button")).toBeInTheDocument();
    });
    fireEvent.click(document.getElementById("convert-lead-commit-button")!);

    await waitFor(() => {
      expect(document.getElementById("convert-lead-commit-error")).toBeInTheDocument();
    });
    expect(document.querySelector('[data-testid="lead-detail"]')).toBeNull();
  });
});
