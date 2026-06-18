// Tests for the live select-tenant flow and its robust states. jsdom has no
// backend, so `../api` is mocked: `getCurrentIdentity` rejects (the visitor is
// signed-out on mount), `listTenants` and `assumePersona` are driven per test.
// The page + the guarded `/app` zone render inside a real `<SessionProvider>`
// and a `MemoryRouter`, so the full select -> assume -> demo-home flow is
// exercised end-to-end.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Identity, Tenant } from "../api";
import { SessionProvider } from "../session";
import SelectTenantPage from "./SelectTenantPage.tsx";
import DemoHomePage from "./DemoHomePage.tsx";
import RequireSession from "../components/RequireSession.tsx";

vi.mock("../api", () => ({
  getCurrentIdentity: vi.fn(),
  listTenants: vi.fn(),
  assumePersona: vi.fn(),
  signOut: vi.fn(),
}));

import { assumePersona, getCurrentIdentity, listTenants } from "../api";

const getCurrentIdentityMock = vi.mocked(getCurrentIdentity);
const listTenantsMock = vi.mocked(listTenants);
const assumePersonaMock = vi.mocked(assumePersona);

const sampleTenants: Tenant[] = [
  {
    slug: "sunshine-senior-benefits",
    display_name: "Sunshine Senior Benefits",
    brand_primary_color: "#9C4A1E",
  },
  {
    slug: "florida-family-planning",
    display_name: "Florida Family Planning",
    brand_primary_color: "#0F6A72",
  },
];

const sunshineAgentIdentity: Identity = {
  user: {
    id: "11111111-1111-1111-1111-111111111111",
    username: "agent.one@sunshine.example",
    role: "agent",
    tenant_id: "22222222-2222-2222-2222-222222222222",
    tenant_slug: "sunshine-senior-benefits",
    tenant_name: "Sunshine Senior Benefits",
  },
  capabilities: [
    "claim_leads_manage_tasks",
    "create_edit_records",
    "view_tenant_records",
  ],
};

/** Render the select-tenant route plus the guarded `/app` zone, starting at
 * `/select-tenant`. The session is signed-out on mount. */
function renderSelectTenantFlow() {
  return render(
    <SessionProvider>
      <MemoryRouter initialEntries={["/select-tenant"]}>
        <Routes>
          <Route path="/select-tenant" element={<SelectTenantPage />} />
          <Route path="/app" element={<RequireSession />}>
            <Route index element={<DemoHomePage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </SessionProvider>,
  );
}

beforeEach(() => {
  getCurrentIdentityMock.mockReset();
  listTenantsMock.mockReset();
  assumePersonaMock.mockReset();
  // Signed-out on mount so the guard would redirect until a persona is assumed.
  getCurrentIdentityMock.mockRejectedValue(new ApiErrorLike(401, "not signed in"));
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("select-tenant happy path", () => {
  it("lists tenants and, on click, assumes Agent and lands on the demo home", async () => {
    listTenantsMock.mockResolvedValue(sampleTenants);
    assumePersonaMock.mockResolvedValue(sunshineAgentIdentity);

    renderSelectTenantFlow();

    const sunshineButton = await screen.findByRole("button", {
      name: /Sunshine Senior Benefits/,
    });
    fireEvent.click(sunshineButton);

    expect(assumePersonaMock).toHaveBeenCalledWith(
      "sunshine-senior-benefits",
      "agent",
    );
    await waitFor(() => {
      expect(screen.getByText("Demo home")).toBeInTheDocument();
    });
    // The demo home shows the assumed role and tenant from the identity body.
    // The masthead (rendered by the app shell) also shows them, so target the
    // demo-home spans by id to stay unambiguous.
    expect(document.getElementById("demo-home-role")).toHaveTextContent("Agent");
    expect(document.getElementById("demo-home-tenant")).toHaveTextContent(
      "Sunshine Senior Benefits",
    );
  });
});

describe("select-tenant robust states", () => {
  it("shows a loading status while the tenant list is in flight", async () => {
    // A never-settling promise holds the page in its loading state.
    listTenantsMock.mockReturnValue(new Promise(() => {}));

    renderSelectTenantFlow();

    // waitFor lets the mount's signed-out /me rejection settle inside act(),
    // while the never-settling tenant fetch keeps the loading status showing.
    await waitFor(() => {
      expect(screen.getByText("Loading tenants…")).toBeInTheDocument();
    });
  });

  it("shows an error and retries the fetch when listTenants rejects", async () => {
    listTenantsMock
      .mockRejectedValueOnce(new ApiErrorLike(500, "server error"))
      .mockResolvedValueOnce(sampleTenants);

    renderSelectTenantFlow();

    const retryButton = await screen.findByRole("button", { name: "Retry" });
    expect(screen.getByText("Could not load tenants.")).toBeInTheDocument();

    fireEvent.click(retryButton);

    // The retry loaded the tenants successfully.
    expect(
      await screen.findByRole("button", { name: /Sunshine Senior Benefits/ }),
    ).toBeInTheDocument();
  });

  it("re-enables the controls and shows a message when assume fails", async () => {
    listTenantsMock.mockResolvedValue(sampleTenants);
    assumePersonaMock.mockRejectedValue(new ApiErrorLike(403, "denied"));

    renderSelectTenantFlow();

    const sunshineButton = await screen.findByRole("button", {
      name: /Sunshine Senior Benefits/,
    });
    fireEvent.click(sunshineButton);

    await waitFor(() => {
      expect(
        screen.getByText("Could not sign you in. Please try again."),
      ).toBeInTheDocument();
    });
    // The controls are re-enabled and the visitor is still on the select page.
    expect(sunshineButton).not.toBeDisabled();
    expect(screen.queryByText("Demo home")).not.toBeInTheDocument();
  });
});

/** A minimal stand-in for the client's `ApiError`. */
class ApiErrorLike extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}
