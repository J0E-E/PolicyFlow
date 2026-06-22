// Tests for the branded select-tenant flow and its robust states. jsdom has no
// backend, so `../api` is mocked: `getCurrentIdentity` rejects (the visitor is
// signed-out on mount), `listTenants` and `assumePersona` are driven per test.
// The page + the guarded `/app` zone render inside a real `<SessionProvider>`
// and a `MemoryRouter`, so the full select -> assume -> demo-home flow is
// exercised end-to-end.
//
// Each card's footer button now carries the same accessible name ("Enter the
// agent workspace →"), so the per-card button is targeted by its derived id
// (`select-tenant-card-<slug>-enter-button`) rather than by tenant name.

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
  // The happy path lands on `/app`, mounting the masthead's
  // <DemoSessionCountdown />, which fetches on mount; resolve it to `none` so it
  // shows the plain stamp and fires no unmocked network.
  getDemoSession: vi.fn().mockResolvedValue({ status: "none" }),
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
    product_lines: [],
  },
  {
    slug: "florida-family-planning",
    display_name: "Florida Family Planning",
    brand_primary_color: "#0F6A72",
    product_lines: [],
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

/** Wait for the tenant cards to render, then return the Sunshine card's footer
 * button by its derived id (the accessible name is shared across cards). */
async function findSunshineEnterButton(): Promise<HTMLElement> {
  await waitFor(() => {
    expect(
      document.getElementById("select-tenant-card-sunshine-senior-benefits"),
    ).toBeInTheDocument();
  });
  const button = document.getElementById(
    "select-tenant-card-sunshine-senior-benefits-enter-button",
  );
  if (button === null) {
    throw new Error("Sunshine enter-the-workspace button not found");
  }
  return button;
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

describe("select-tenant branded render", () => {
  it("renders the why-two-tenants block and a branded card per tenant", async () => {
    listTenantsMock.mockResolvedValue(sampleTenants);

    renderSelectTenantFlow();

    // The "Why two tenants?" framing copy is present (Epic 19 anchors here).
    await waitFor(() => {
      expect(
        document.getElementById("select-tenant-why-heading"),
      ).toHaveTextContent("Why two tenants?");
    });
    expect(document.getElementById("select-tenant-why-body")).toHaveTextContent(
      /neither can ever see the other's records/,
    );

    // Each card carries its tenant's display name, specialization blurb,
    // `data-tenant` brand scope, and the shared footer button label.
    const sunshineItem = document.getElementById(
      "select-tenant-card-item-sunshine-senior-benefits",
    );
    expect(sunshineItem).toHaveAttribute(
      "data-tenant",
      "sunshine-senior-benefits",
    );
    expect(
      document.getElementById("select-tenant-card-sunshine-senior-benefits-title"),
    ).toHaveTextContent("Sunshine Senior Benefits");
    expect(
      document.getElementById("select-tenant-card-sunshine-senior-benefits-blurb"),
    ).toHaveTextContent(/Medicare and senior-market coverage/);

    const floridaItem = document.getElementById(
      "select-tenant-card-item-florida-family-planning",
    );
    expect(floridaItem).toHaveAttribute("data-tenant", "florida-family-planning");
    expect(
      document.getElementById("select-tenant-card-florida-family-planning-blurb"),
    ).toHaveTextContent(/Life and protection planning for growing households/);

    // Both footer buttons share the "Enter the agent workspace →" label.
    expect(
      screen.getAllByRole("button", { name: /Enter the agent workspace/ }),
    ).toHaveLength(2);

    // Epic 19 seeds the multi-tenant-isolation explainer at the why-two-tenants block.
    const explainerTrigger = document.getElementById(
      "explainer-select-tenant-why-trigger",
    );
    expect(explainerTrigger).toBeInTheDocument();
    expect(explainerTrigger).toHaveAttribute(
      "aria-label",
      "Explain: multi-tenant isolation",
    );
  });
});

describe("select-tenant happy path", () => {
  it("on click, assumes Agent and lands on the demo home", async () => {
    listTenantsMock.mockResolvedValue(sampleTenants);
    assumePersonaMock.mockResolvedValue(sunshineAgentIdentity);

    renderSelectTenantFlow();

    const sunshineButton = await findSunshineEnterButton();
    fireEvent.click(sunshineButton);

    expect(assumePersonaMock).toHaveBeenCalledWith(
      "sunshine-senior-benefits",
      "agent",
    );
    await waitFor(() => {
      // The demo home now opens with the welcome headline (Epic 16). Target the
      // page title by id — the LeftNav rail still carries a "Demo home" label, so
      // the id keeps this unambiguous (the id-targeting deviation Epics 10/12 recorded).
      expect(document.getElementById("demo-home-title")).toHaveTextContent(
        "Welcome to the PolicyFlow demo",
      );
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

    // The retry loaded the tenants successfully — the branded cards render.
    await waitFor(() => {
      expect(
        document.getElementById("select-tenant-card-sunshine-senior-benefits"),
      ).toBeInTheDocument();
    });
  });

  it("re-enables the controls and shows a message when assume fails", async () => {
    listTenantsMock.mockResolvedValue(sampleTenants);
    assumePersonaMock.mockRejectedValue(new ApiErrorLike(403, "denied"));

    renderSelectTenantFlow();

    const sunshineButton = await findSunshineEnterButton();
    fireEvent.click(sunshineButton);

    await waitFor(() => {
      expect(
        screen.getByText("Could not sign you in. Please try again."),
      ).toBeInTheDocument();
    });
    // The controls are re-enabled and the visitor is still on the select page —
    // the demo home (whose welcome headline would prove the redirect) never rendered.
    expect(sunshineButton).not.toBeDisabled();
    expect(
      screen.queryByText("Welcome to the PolicyFlow demo"),
    ).not.toBeInTheDocument();
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
