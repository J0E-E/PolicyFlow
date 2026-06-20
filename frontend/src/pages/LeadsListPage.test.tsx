// Tests for the authenticated leads list page (Epic 20). jsdom has no backend, so
// `../api` is mocked: listTenants drives the product-line registry, listLeads
// drives each tab, claimLead drives the claim action. The page reads the session
// via `../session`, so that is mocked too — useSession returns a fixed agent
// identity and useCapability is driven per capability (create_edit_records,
// claim_leads_manage_tasks). The page renders react-router links, so it is wrapped
// in a MemoryRouter. Covers: loading, loaded table, tab switch + queue filter,
// empty (both tabs), fetch error + retry, the duplicate stamp, claim happy path,
// and a failed claim's non-destructive inline error.

import { fireEvent, render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import LeadsListPage from "./LeadsListPage.tsx";
import type { Capability, Identity, MaskedLead, Tenant } from "../api";

vi.mock("../api", () => ({
  listTenants: vi.fn(),
  listLeads: vi.fn(),
  claimLead: vi.fn(),
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

import { claimLead, listLeads, listTenants } from "../api";
import { useCapability, useSession } from "../session";

const listTenantsMock = vi.mocked(listTenants);
const listLeadsMock = vi.mocked(listLeads);
const claimLeadMock = vi.mocked(claimLead);
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
  capabilities: ["create_edit_records", "claim_leads_manage_tasks"],
};

// A masked lead with sensible defaults; each test overrides only what it asserts.
function makeLead(overrides: Partial<MaskedLead>): MaskedLead {
  return {
    id: "lead-default",
    first_name: "Pat",
    last_name: "Quincy",
    email: "p***@example.com",
    phone: "***-***-0000",
    date_of_birth: "****-**-**",
    age_band: "65-74",
    zip_code: "33101",
    street_address: null,
    product_lines_of_interest: ["medicare_advantage"],
    preferred_contact_method: null,
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

function renderPage() {
  return render(
    <MemoryRouter>
      <LeadsListPage />
    </MemoryRouter>,
  );
}

// Drive useCapability off the agent identity's capability set by default; a test
// flips one capability by overriding the implementation.
function capabilitySet(held: Capability[]) {
  return (capability: Capability) => held.includes(capability);
}

beforeEach(() => {
  listTenantsMock.mockReset();
  listLeadsMock.mockReset();
  claimLeadMock.mockReset();
  useCapabilityMock.mockReset();
  useSessionMock.mockReset();
  useSessionMock.mockReturnValue(sessionFor(agentIdentity));
  useCapabilityMock.mockImplementation(
    capabilitySet(["create_edit_records", "claim_leads_manage_tasks"]),
  );
  // Default: the tenant resolves, and both tabs start empty unless a test says otherwise.
  listTenantsMock.mockResolvedValue([sunshineTenant]);
  listLeadsMock.mockResolvedValue([]);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("LeadsListPage header + loading", () => {
  it("shows a loading state while the tenant list is in flight", () => {
    listTenantsMock.mockReturnValue(new Promise<Tenant[]>(() => {}));

    renderPage();

    expect(document.getElementById("leads-list-loading")).toBeInTheDocument();
    expect(document.getElementById("leads-list-title")).toHaveTextContent("Leads");
  });

  it("shows the gated New-lead link for an agent who can create leads", async () => {
    renderPage();

    await waitFor(() => {
      expect(
        document.getElementById("leads-list-new-lead-link"),
      ).toBeInTheDocument();
    });
    expect(document.getElementById("leads-list-new-lead-link")).toHaveAttribute(
      "href",
      "/app/leads/new",
    );
  });

  it("hides the New-lead link for a Read-Only agent", async () => {
    useCapabilityMock.mockImplementation(capabilitySet(["view_tenant_records"]));

    renderPage();

    await waitFor(() => {
      expect(document.getElementById("leads-list-tablist")).toBeInTheDocument();
    });
    expect(document.getElementById("leads-list-new-lead-link")).toBeNull();
  });
});

describe("LeadsListPage loaded table", () => {
  it("renders a row per lead with status stamp, source, owner and created date", async () => {
    listLeadsMock.mockResolvedValue([
      makeLead({
        id: "lead-a",
        first_name: "Maria",
        last_name: "Lopez",
        status: "New",
        lead_source: "public_form",
        owner_username: null,
        created_at: "2026-06-18T14:30:00Z",
      }),
      makeLead({
        id: "lead-b",
        first_name: "John",
        last_name: "Reed",
        status: "Working",
        lead_source: "agent_entered",
        owner_user_id: "owner-1",
        owner_username: "agent.two@sunshine.example",
        created_at: "2026-06-17T09:00:00Z",
      }),
    ]);

    renderPage();

    await waitFor(() => {
      expect(document.getElementById("leads-list-row-lead-a")).toBeInTheDocument();
    });

    // Row A: a New public unowned lead. The name is a link to the lead detail
    // page (Epic 21) — its own id-bearing element (the hard CLAUDE.md id rule).
    expect(document.getElementById("leads-list-row-lead-a-name")).toHaveTextContent(
      "Maria Lopez",
    );
    const nameLink = document.getElementById("leads-list-row-lead-a-name-link");
    expect(nameLink).toHaveTextContent("Maria Lopez");
    expect(nameLink).toHaveAttribute("href", "/app/leads/lead-a");
    expect(
      document.getElementById("leads-list-row-lead-a-status-stamp-label"),
    ).toHaveTextContent("New");
    expect(
      document.getElementById("leads-list-row-lead-a-source"),
    ).toHaveTextContent("Public");
    expect(document.getElementById("leads-list-row-lead-a-owner")).toHaveTextContent(
      "—",
    );
    expect(
      document.getElementById("leads-list-row-lead-a-created"),
    ).toHaveTextContent("2026-06-18");
    expect(
      document.getElementById("leads-list-row-lead-a-product-lines"),
    ).toHaveTextContent("Medicare Advantage");

    // Row B: a Working agent-entered owned lead — owner shown, no Claim button.
    expect(
      document.getElementById("leads-list-row-lead-b-status-stamp-label"),
    ).toHaveTextContent("Working");
    expect(
      document.getElementById("leads-list-row-lead-b-source"),
    ).toHaveTextContent("Agent");
    expect(document.getElementById("leads-list-row-lead-b-owner")).toHaveTextContent(
      "agent.two@sunshine.example",
    );
    expect(
      document.getElementById("leads-list-row-lead-b-claim-button"),
    ).toBeNull();

    // The active "All leads" tab shows the count.
    expect(document.getElementById("leads-list-tab-all-count")).toHaveTextContent(
      "2",
    );
  });

  it("flags an unresolved possible-duplicate row with a warning stamp", async () => {
    listLeadsMock.mockResolvedValue([
      makeLead({
        id: "dup",
        duplicate_of_lead_id: "prior-lead",
        duplicate_resolution: null,
      }),
      makeLead({
        id: "resolved",
        duplicate_of_lead_id: "prior-lead",
        duplicate_resolution: "new",
      }),
    ]);

    renderPage();

    await waitFor(() => {
      expect(document.getElementById("leads-list-row-dup")).toBeInTheDocument();
    });
    expect(
      document.getElementById("leads-list-row-dup-duplicate"),
    ).toHaveTextContent("Possible duplicate");
    // A resolved duplicate carries no flag.
    expect(
      document.getElementById("leads-list-row-resolved-duplicate"),
    ).toBeNull();
  });

  it("queries the queue filter when the Unassigned queue tab is selected", async () => {
    listLeadsMock.mockResolvedValue([makeLead({ id: "lead-a" })]);

    renderPage();

    await waitFor(() => {
      expect(document.getElementById("leads-list-row-lead-a")).toBeInTheDocument();
    });
    // First load is the All tab (unassigned false/undefined).
    expect(listLeadsMock).toHaveBeenLastCalledWith(false);

    fireEvent.click(document.getElementById("leads-list-tab-queue")!);

    await waitFor(() => {
      expect(listLeadsMock).toHaveBeenLastCalledWith(true);
    });
  });

  it("roves between tabs with the Left/Right arrow keys (WAI-ARIA tablist)", async () => {
    listLeadsMock.mockResolvedValue([makeLead({ id: "lead-a" })]);

    renderPage();

    await waitFor(() => {
      expect(document.getElementById("leads-list-row-lead-a")).toBeInTheDocument();
    });
    expect(listLeadsMock).toHaveBeenLastCalledWith(false);

    // ArrowRight from the active All tab selects the queue tab and moves focus.
    const allTab = document.getElementById("leads-list-tab-all")!;
    fireEvent.keyDown(allTab, { key: "ArrowRight" });

    await waitFor(() => {
      expect(listLeadsMock).toHaveBeenLastCalledWith(true);
    });
    const queueTab = document.getElementById("leads-list-tab-queue")!;
    expect(queueTab).toHaveAttribute("aria-selected", "true");
    expect(document.activeElement).toBe(queueTab);

    // ArrowLeft wraps focus + selection back to the All tab.
    fireEvent.keyDown(queueTab, { key: "ArrowLeft" });

    await waitFor(() => {
      expect(listLeadsMock).toHaveBeenLastCalledWith(false);
    });
    expect(allTab).toHaveAttribute("aria-selected", "true");
    expect(document.activeElement).toBe(allTab);
  });
});

describe("LeadsListPage empty + error states", () => {
  it("shows the All-tab empty note with a New-lead CTA when there are no leads", async () => {
    listLeadsMock.mockResolvedValue([]);

    renderPage();

    await waitFor(() => {
      expect(document.getElementById("leads-list-empty-all")).toBeInTheDocument();
    });
    expect(
      document.getElementById("leads-list-empty-all-message"),
    ).toHaveTextContent("No leads yet.");
    // Guide §5 empty state leads with an aria-hidden icon glyph.
    const allEmptyIcon = document.getElementById("leads-list-empty-all-icon");
    expect(allEmptyIcon).toBeInTheDocument();
    expect(allEmptyIcon).toHaveAttribute("aria-hidden", "true");
    expect(
      document.getElementById("leads-list-empty-new-lead-link"),
    ).toHaveAttribute("href", "/app/leads/new");
  });

  it("shows the calm queue-clear note on the empty queue tab", async () => {
    listLeadsMock.mockResolvedValue([]);

    renderPage();

    await waitFor(() => {
      expect(document.getElementById("leads-list-empty-all")).toBeInTheDocument();
    });

    fireEvent.click(document.getElementById("leads-list-tab-queue")!);

    await waitFor(() => {
      expect(
        document.getElementById("leads-list-empty-queue"),
      ).toBeInTheDocument();
    });
    expect(
      document.getElementById("leads-list-empty-queue-message"),
    ).toHaveTextContent("The queue is clear");
    // The queue empty state also leads with an aria-hidden icon glyph (Guide §5).
    const queueEmptyIcon = document.getElementById("leads-list-empty-queue-icon");
    expect(queueEmptyIcon).toBeInTheDocument();
    expect(queueEmptyIcon).toHaveAttribute("aria-hidden", "true");
    // The calm queue note carries no New-lead CTA.
    expect(document.getElementById("leads-list-empty-new-lead-link")).toBeNull();
  });

  it("shows a leads fetch error and retries", async () => {
    listLeadsMock
      .mockRejectedValueOnce(new Error("server error"))
      .mockResolvedValueOnce([makeLead({ id: "lead-a" })]);

    renderPage();

    await waitFor(() => {
      expect(
        document.getElementById("leads-list-leads-error"),
      ).toBeInTheDocument();
    });

    fireEvent.click(
      document.getElementById("leads-list-leads-error-retry-button")!,
    );

    await waitFor(() => {
      expect(document.getElementById("leads-list-row-lead-a")).toBeInTheDocument();
    });
  });

  it("shows a tenant error and retries", async () => {
    listTenantsMock
      .mockRejectedValueOnce(new Error("server error"))
      .mockResolvedValueOnce([sunshineTenant]);

    renderPage();

    await waitFor(() => {
      expect(document.getElementById("leads-list-error")).toBeInTheDocument();
    });

    fireEvent.click(document.getElementById("leads-list-error-retry-button")!);

    await waitFor(() => {
      expect(document.getElementById("leads-list-tablist")).toBeInTheDocument();
    });
  });
});

describe("LeadsListPage claim action", () => {
  it("shows a Claim button on a claimable row only for a claim-capable agent", async () => {
    listLeadsMock.mockResolvedValue([
      makeLead({ id: "claimable", status: "New", owner_user_id: null }),
    ]);

    renderPage();

    await waitFor(() => {
      expect(
        document.getElementById("leads-list-row-claimable-claim-button"),
      ).toBeInTheDocument();
    });
  });

  it("hides the Claim button when the agent lacks claim_leads_manage_tasks", async () => {
    useCapabilityMock.mockImplementation(
      capabilitySet(["view_tenant_records", "create_edit_records"]),
    );
    listLeadsMock.mockResolvedValue([
      makeLead({ id: "claimable", status: "New", owner_user_id: null }),
    ]);

    renderPage();

    await waitFor(() => {
      expect(document.getElementById("leads-list-row-claimable")).toBeInTheDocument();
    });
    expect(
      document.getElementById("leads-list-row-claimable-claim-button"),
    ).toBeNull();
  });

  it("claims a lead then refetches the active tab to reconcile", async () => {
    // First (All-tab) load: one claimable New lead. After claiming it, the refetch
    // returns it flipped to Working + owned.
    listLeadsMock
      .mockResolvedValueOnce([
        makeLead({ id: "claimable", status: "New", owner_user_id: null }),
      ])
      .mockResolvedValueOnce([
        makeLead({
          id: "claimable",
          status: "Working",
          owner_user_id: "11111111-1111-1111-1111-111111111111",
          owner_username: "agent.one@sunshine.example",
        }),
      ]);
    claimLeadMock.mockResolvedValue(
      makeLead({ id: "claimable", status: "Working" }),
    );

    renderPage();

    await waitFor(() => {
      expect(
        document.getElementById("leads-list-row-claimable-claim-button"),
      ).toBeInTheDocument();
    });

    fireEvent.click(
      document.getElementById("leads-list-row-claimable-claim-button")!,
    );

    expect(claimLeadMock).toHaveBeenCalledWith("claimable");

    // After the refetch, the row is Working + owned and no longer claimable.
    await waitFor(() => {
      expect(
        document.getElementById("leads-list-row-claimable-status-stamp-label"),
      ).toHaveTextContent("Working");
    });
    expect(
      document.getElementById("leads-list-row-claimable-claim-button"),
    ).toBeNull();
    expect(
      document.getElementById("leads-list-row-claimable-owner"),
    ).toHaveTextContent("agent.one@sunshine.example");
  });

  it("surfaces a non-destructive inline error and keeps the list when a claim fails", async () => {
    listLeadsMock.mockResolvedValue([
      makeLead({ id: "claimable", status: "New", owner_user_id: null }),
    ]);
    claimLeadMock.mockRejectedValue(new Error("409 already claimed"));

    renderPage();

    await waitFor(() => {
      expect(
        document.getElementById("leads-list-row-claimable-claim-button"),
      ).toBeInTheDocument();
    });

    fireEvent.click(
      document.getElementById("leads-list-row-claimable-claim-button")!,
    );

    await waitFor(() => {
      expect(document.getElementById("leads-list-claim-error")).toBeInTheDocument();
    });
    // The list stays intact and the row's Claim button re-enables (no full-page error).
    expect(document.getElementById("leads-list-row-claimable")).toBeInTheDocument();
    const claimButton = document.getElementById(
      "leads-list-row-claimable-claim-button",
    ) as HTMLButtonElement | null;
    expect(claimButton).not.toBeNull();
    expect(claimButton!.disabled).toBe(false);
  });
});
