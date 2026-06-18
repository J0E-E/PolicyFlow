// Tests for the `/app` route guard. jsdom has no backend, so `../api` is mocked
// and each test controls `getCurrentIdentity` to drive the session into one of
// its three states (loading / signed-out / signed-in). The guard tree is
// rendered inside a real `<SessionProvider>` and a `MemoryRouter` so the actual
// routing — redirect, skeleton, guarded child — is exercised end-to-end.

import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Identity } from "../api";
import { SessionProvider } from "../session";
import RequireSession from "./RequireSession.tsx";
import DemoHomePage from "../pages/DemoHomePage.tsx";
import LandingPage from "../pages/LandingPage.tsx";

vi.mock("../api", () => ({
  getCurrentIdentity: vi.fn(),
  assumePersona: vi.fn(),
  signOut: vi.fn(),
}));

import { getCurrentIdentity } from "../api";

const getCurrentIdentityMock = vi.mocked(getCurrentIdentity);

const agentIdentity: Identity = {
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

/** Render the public landing route plus the guarded `/app` zone, starting at `/app`. */
function renderGuardedTreeAtApp() {
  return render(
    <SessionProvider>
      <MemoryRouter initialEntries={["/app"]}>
        <Routes>
          <Route path="/" element={<LandingPage />} />
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
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("RequireSession guard", () => {
  it("shows the session-restore skeleton while /me is in flight", () => {
    // A never-settling promise keeps the session in its initial loading state.
    getCurrentIdentityMock.mockReturnValue(new Promise(() => {}));

    renderGuardedTreeAtApp();

    expect(screen.getByText("Restoring your session…")).toBeInTheDocument();
    // The guarded child has not rendered yet.
    expect(screen.queryByText("Demo home")).not.toBeInTheDocument();
  });

  it("redirects a signed-out visitor from /app back to the landing page", async () => {
    getCurrentIdentityMock.mockRejectedValue(
      new ApiErrorLike(401, "not signed in"),
    );

    renderGuardedTreeAtApp();

    await waitFor(() => {
      // The landing subtitle proves the redirect landed on `/`.
      expect(
        screen.getByText(/event-driven insurance operations platform/i),
      ).toBeInTheDocument();
    });
    expect(screen.queryByText("Demo home")).not.toBeInTheDocument();
  });

  it("renders the demo home inside the app shell when signed in", async () => {
    getCurrentIdentityMock.mockResolvedValue(agentIdentity);

    renderGuardedTreeAtApp();

    await waitFor(() => {
      // "Demo home" now appears both as the page heading and the live left-nav
      // item, so target the demo-home page title by id (the LeftNav rail shares
      // the label) — same id-targeting deviation Epic 10 recorded for the masthead.
      expect(document.getElementById("demo-home-title")).toHaveTextContent(
        "Demo home",
      );
    });
    // The role + tenant appear in the demo-home status line (the masthead also
    // shows them, so target the demo-home spans by id to stay unambiguous).
    expect(document.getElementById("demo-home-role")).toHaveTextContent("Agent");
    expect(document.getElementById("demo-home-tenant")).toHaveTextContent(
      "Sunshine Senior Benefits",
    );
    // The branded shell wraps the page: the masthead is present.
    expect(document.getElementById("app-masthead")).toBeInTheDocument();
  });
});

/** A minimal stand-in for the client's `ApiError` — the provider only needs an
 * Error rejection; it does not branch on the status. */
class ApiErrorLike extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}
