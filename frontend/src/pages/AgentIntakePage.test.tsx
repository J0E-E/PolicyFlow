// Tests for the authenticated agent intake page. jsdom has no backend, so
// `../api` is mocked (listTenants drives the tenant resolution; createLead is a
// bare mock the form never calls on mount). The page reads the session via
// `../session`, so that module is mocked too: useSession returns a fixed
// identity and useCapability is driven per test to flip the capability gate. The
// page renders a react-router <Link> (through the form's panel) and uses route
// state, so it is wrapped in a MemoryRouter. Covers: capability-denied
// (Read-Only), loading, error + retry, and loaded → form.

import { fireEvent, render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AgentIntakePage from "./AgentIntakePage.tsx";
import type { Identity, Tenant } from "../api";

vi.mock("../api", () => ({
  listTenants: vi.fn(),
  createLead: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.name = "ApiError";
      this.status = status;
    }
  },
}));

// The session is mocked so the page's identity + capability gate are driven per
// test without standing up a real SessionProvider / /me round-trip.
vi.mock("../session", () => ({
  useSession: vi.fn(),
  useCapability: vi.fn(),
}));

import { listTenants } from "../api";
import { useCapability, useSession } from "../session";

const listTenantsMock = vi.mocked(listTenants);
const useCapabilityMock = vi.mocked(useCapability);
const useSessionMock = vi.mocked(useSession);

const sampleTenants: Tenant[] = [
  {
    slug: "sunshine-senior-benefits",
    display_name: "Sunshine Senior Benefits",
    brand_primary_color: "#9C4A1E",
    product_lines: [
      { key: "medicare_advantage", label: "Medicare Advantage" },
    ],
  },
  {
    slug: "florida-family-planning",
    display_name: "Florida Family Planning",
    brand_primary_color: "#0F6A72",
    product_lines: [{ key: "term_life", label: "Term Life" }],
  },
];

const agentIdentity: Identity = {
  user: {
    id: "11111111-1111-1111-1111-111111111111",
    username: "agent.one@sunshine.example",
    role: "agent",
    tenant_id: "22222222-2222-2222-2222-222222222222",
    tenant_slug: "sunshine-senior-benefits",
    tenant_name: "Sunshine Senior Benefits",
  },
  capabilities: ["create_edit_records"],
};

// A minimal session-context stub — only `identity` is read by the page.
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
      <AgentIntakePage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  listTenantsMock.mockReset();
  useCapabilityMock.mockReset();
  useSessionMock.mockReset();
  useSessionMock.mockReturnValue(sessionFor(agentIdentity));
  // Default: a permitted agent (each test that needs Read-Only flips this).
  useCapabilityMock.mockReturnValue(true);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("AgentIntakePage capability gate", () => {
  it("shows a denied notice (not the form) for a Read-Only agent", () => {
    useCapabilityMock.mockReturnValue(false);

    renderPage();

    // The header still renders, but the body is the denied notice.
    expect(document.getElementById("agent-intake-title")).toHaveTextContent(
      "New lead",
    );
    expect(document.getElementById("agent-intake-denied")).toHaveTextContent(
      "You don't have permission to create leads.",
    );
    // The form never mounts, and the tenant list is never fetched.
    expect(document.getElementById("agent-intake-form")).toBeNull();
    expect(listTenantsMock).not.toHaveBeenCalled();
  });
});

describe("AgentIntakePage tenant resolution", () => {
  it("shows a loading state while the tenant list is in flight", () => {
    listTenantsMock.mockReturnValue(new Promise<Tenant[]>(() => {}));

    renderPage();

    expect(document.getElementById("agent-intake-loading")).toBeInTheDocument();
  });

  it("shows an error and retries the fetch when listTenants rejects", async () => {
    listTenantsMock
      .mockRejectedValueOnce(new Error("server error"))
      .mockResolvedValueOnce(sampleTenants);

    renderPage();

    await waitFor(() => {
      expect(document.getElementById("agent-intake-error")).toBeInTheDocument();
    });

    fireEvent.click(
      document.getElementById("agent-intake-error-retry-button")!,
    );

    // The retry resolved → the form for the agent's tenant renders.
    await waitFor(() => {
      expect(document.getElementById("agent-intake-form")).toBeInTheDocument();
    });
  });

  it("renders the form for the agent's tenant once the list loads", async () => {
    listTenantsMock.mockResolvedValue(sampleTenants);

    renderPage();

    await waitFor(() => {
      expect(document.getElementById("agent-intake-form")).toBeInTheDocument();
    });
    // The form's checkbox group is built from the AGENT's tenant (Sunshine),
    // not the other tenant in the list.
    expect(
      document.getElementById(
        "agent-intake-product-lines-option-medicare_advantage",
      ),
    ).toBeInTheDocument();
    expect(
      document.getElementById("agent-intake-product-lines-option-term_life"),
    ).toBeNull();
  });

  it("shows a defensive not-found when no tenant matches the session slug", async () => {
    listTenantsMock.mockResolvedValue(sampleTenants);
    useSessionMock.mockReturnValue(
      sessionFor({
        ...agentIdentity,
        user: { ...agentIdentity.user, tenant_slug: "unknown-agency" },
      }),
    );

    renderPage();

    await waitFor(() => {
      expect(
        document.getElementById("agent-intake-not-found"),
      ).toBeInTheDocument();
    });
    expect(document.getElementById("agent-intake-form")).toBeNull();
  });
});
