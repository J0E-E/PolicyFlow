// Frontend acceptance for the convert flow + frozen panel (P2.1 Epic 11). Where the
// per-page tests prove each screen in isolation, this walks the whole user journey
// across both routes with a real router: a held Qualified lead's detail shows the
// Convert affordance → it routes to the review-and-confirm screen → committing calls
// `convertLead` and returns to the now-frozen lead, where the Convert affordance is
// gone and the "Converted to" panel renders. `../api` and `../session` are mocked; a
// single stateful `getLead` flips Qualified → Converted once the convert is committed.

import { fireEvent, render, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import LeadDetailPage from "./LeadDetailPage.tsx";
import ConvertLeadPage from "./ConvertLeadPage.tsx";
import type { Capability, Identity, MaskedLead, Tenant } from "../api";

vi.mock("../api", () => ({
  getLead: vi.fn(),
  listTenants: vi.fn(),
  getLeadTimeline: vi.fn(),
  getDemoSession: vi.fn(),
  getConversion: vi.fn(),
  getConversionPrefill: vi.fn(),
  getHouseholds: vi.fn(),
  convertLead: vi.fn(),
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
  convertLead,
  getConversion,
  getConversionPrefill,
  getLead,
  getLeadTimeline,
  getDemoSession,
  listTenants,
} from "../api";
import { useCapability, useSession } from "../session";

const getLeadMock = vi.mocked(getLead);
const listTenantsMock = vi.mocked(listTenants);
const getLeadTimelineMock = vi.mocked(getLeadTimeline);
const getDemoSessionMock = vi.mocked(getDemoSession);
const getConversionMock = vi.mocked(getConversion);
const getConversionPrefillMock = vi.mocked(getConversionPrefill);
const convertLeadMock = vi.mocked(convertLead);
const useCapabilityMock = vi.mocked(useCapability);
const useSessionMock = vi.mocked(useSession);

const AGENT_USER_ID = "11111111-1111-1111-1111-111111111111";

const sunshineTenant: Tenant = {
  slug: "sunshine-senior-benefits",
  display_name: "Sunshine Senior Benefits",
  brand_primary_color: "#9C4A1E",
  product_lines: [{ key: "medicare_advantage", label: "Medicare Advantage" }],
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

let isConverted = false;

beforeEach(() => {
  isConverted = false;
  vi.clearAllMocks();
  useSessionMock.mockReturnValue(sessionFor(agentIdentity));
  useCapabilityMock.mockImplementation(capabilitySet(["create_edit_records", "reveal_pii"]));
  listTenantsMock.mockResolvedValue([sunshineTenant]);
  // Stateful lead: Qualified until the convert commits, then Converted.
  getLeadMock.mockImplementation(async () =>
    makeLead({ status: isConverted ? "Converted" : "Qualified" }),
  );
  convertLeadMock.mockImplementation(async () => {
    isConverted = true;
    return makeLead({ status: "Converted" });
  });
  getLeadTimelineMock.mockResolvedValue([]);
  getDemoSessionMock.mockResolvedValue({ status: "active" });
  getConversionPrefillMock.mockResolvedValue({ preselected_household: null });
  getConversionMock.mockResolvedValue({
    contact: { id: "contact-1", first_name: "Maria", last_name: "Lopez" },
    household: { id: "household-1", name: "Lopez Household" },
    opportunities: [
      { id: "opp-1", product_line: "medicare_advantage", stage: "New" },
    ],
  });
});

afterEach(() => {
  vi.clearAllMocks();
});

function renderFlow() {
  return render(
    <MemoryRouter initialEntries={["/app/leads/lead-1"]}>
      <Routes>
        <Route path="/app/leads/:id" element={<LeadDetailPage />} />
        <Route path="/app/leads/:id/convert" element={<ConvertLeadPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("convert flow acceptance", () => {
  it("walks detail → convert → commit → frozen lead with the Converted to panel", async () => {
    renderFlow();

    // 1. The Qualified, held lead detail offers the Convert affordance.
    await waitFor(() => {
      expect(
        document.getElementById("lead-detail-convert-button"),
      ).toBeInTheDocument();
    });

    // 2. Activating it routes to the review-and-confirm screen.
    fireEvent.click(document.getElementById("lead-detail-convert-button")!);
    await waitFor(() => {
      expect(
        document.getElementById("convert-lead-commit-button"),
      ).toBeInTheDocument();
    });

    // 3. Committing converts and routes back to the now-frozen lead.
    fireEvent.click(document.getElementById("convert-lead-commit-button")!);
    await waitFor(() => {
      expect(convertLeadMock).toHaveBeenCalledWith("lead-1", {
        household: { mode: "new" },
        product_lines: ["medicare_advantage"],
      });
    });

    // 4. The frozen lead hides the Convert affordance and shows the "Converted to" panel.
    await waitFor(() => {
      expect(
        document.getElementById("lead-converted-summary"),
      ).toBeInTheDocument();
    });
    expect(document.getElementById("lead-detail-convert")).toBeNull();
    expect(
      document.getElementById("lead-converted-household-name"),
    ).toHaveTextContent("Lopez Household");
  });
});
