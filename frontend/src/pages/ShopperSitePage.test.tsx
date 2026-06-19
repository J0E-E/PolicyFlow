// Tests for the public Shopper site shell and its robust states. jsdom has no
// backend, so `../api` is mocked: `listTenants` is driven per test. The Shopper
// zone is UNAUTHENTICATED — it renders purely from the route slug, with no guard
// and no redirect. The page DOES read `useSession().status` (Epic 24) only to gate
// the surface toggle, so the route is wrapped in a SessionProvider whose `/me`
// (getCurrentIdentity) is driven per test: rejecting → signed-out (no toggle),
// resolving → signed-in (toggle to /app). These still assert no guard / redirect.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Identity, Tenant } from "../api";
import App from "../App.tsx";
import ShopperSitePage from "./ShopperSitePage.tsx";
import { SessionProvider } from "../session";

vi.mock("../api", () => ({
  getCurrentIdentity: vi.fn(),
  listTenants: vi.fn(),
  assumePersona: vi.fn(),
  signOut: vi.fn(),
}));

import { getCurrentIdentity, listTenants } from "../api";

const listTenantsMock = vi.mocked(listTenants);
const getCurrentIdentityMock = vi.mocked(getCurrentIdentity);

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

// A signed-in agent identity — used to drive the SessionProvider's /me to
// `signed-in` so the Epic 24 surface toggle gates on.
const signedInIdentity: Identity = {
  user: {
    id: "11111111-1111-1111-1111-111111111111",
    username: "agent.one@sunshine.example",
    role: "agent",
    tenant_id: "22222222-2222-2222-2222-222222222222",
    tenant_slug: "sunshine-senior-benefits",
    tenant_name: "Sunshine Senior Benefits",
  },
  capabilities: [],
};

/** Render the Shopper route at `/site/:slug` for the given slug. Wrapped in a
 *  SessionProvider — the page reads session status to gate the Epic 24 toggle (the
 *  surface stays public; status only decides whether the toggle shows). */
function renderShopperSite(slug: string) {
  return render(
    <SessionProvider>
      <MemoryRouter initialEntries={[`/site/${slug}`]}>
        <Routes>
          <Route path="/site/:slug" element={<ShopperSitePage />} />
        </Routes>
      </MemoryRouter>
    </SessionProvider>,
  );
}

beforeEach(() => {
  listTenantsMock.mockReset();
  getCurrentIdentityMock.mockReset();
  // The /site redirect lands on /select-tenant, which mounts inside a
  // SessionProvider whose mount effect calls /me — signed-out on mount.
  getCurrentIdentityMock.mockRejectedValue(new Error("not signed in"));
});

afterEach(() => {
  vi.clearAllMocks();
  // Theming writes data-tenant onto the document root; clear it between tests.
  document.documentElement.removeAttribute("data-tenant");
  document.documentElement.removeAttribute("data-persona");
});

describe("Shopper site branded shell", () => {
  it("renders the tenant-branded shell + buyer home for a valid slug", async () => {
    listTenantsMock.mockResolvedValue(sampleTenants);

    renderShopperSite("sunshine-senior-benefits");

    // The consumer masthead carries the tenant name as the wordmark.
    await waitFor(() => {
      expect(
        document.getElementById("shopper-masthead-wordmark"),
      ).toHaveTextContent("Sunshine Senior Benefits");
    });

    // The surface is themed by slug — data-tenant is set on the document root,
    // so the [data-tenant] brand ramp paints --primary.
    expect(document.documentElement).toHaveAttribute(
      "data-tenant",
      "sunshine-senior-benefits",
    );
    // Persona-free: the Shopper never sets data-persona.
    expect(document.documentElement).not.toHaveAttribute("data-persona");

    // The per-tenant buyer-home hero + quote placeholder render.
    expect(
      document.getElementById("shopper-home-hero-title"),
    ).toHaveTextContent("Medicare coverage that fits your life");
    expect(
      document.getElementById("shopper-home-quote-card-title"),
    ).toHaveTextContent("Get your free quote");
  });

  it("renders distinct per-tenant hero copy for the other tenant", async () => {
    listTenantsMock.mockResolvedValue(sampleTenants);

    renderShopperSite("florida-family-planning");

    await waitFor(() => {
      expect(
        document.getElementById("shopper-home-hero-title"),
      ).toHaveTextContent("Protect the people who count on you");
    });
    expect(document.documentElement).toHaveAttribute(
      "data-tenant",
      "florida-family-planning",
    );
  });

  it("is unauthenticated — no agent chrome (role switcher / left nav)", async () => {
    listTenantsMock.mockResolvedValue(sampleTenants);

    renderShopperSite("sunshine-senior-benefits");

    await waitFor(() => {
      expect(document.getElementById("shopper-masthead")).toBeInTheDocument();
    });

    // None of the agent workspace chrome leaks onto the consumer surface.
    expect(
      document.getElementById("app-masthead-role-switcher"),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Primary" })).toBeNull();
    expect(
      document.getElementById("app-masthead-session-stamp"),
    ).not.toBeInTheDocument();
    // No session was ever asked for — the visitor is signed-out yet sees the site.
    expect(
      document.getElementById("app-session-skeleton"),
    ).not.toBeInTheDocument();
  });
});

describe("Shopper site surface toggle (Epic 24)", () => {
  it("shows the toggle back to /app for a signed-in visitor", async () => {
    listTenantsMock.mockResolvedValue(sampleTenants);
    // /me resolves → the SessionProvider lands signed-in.
    getCurrentIdentityMock.mockResolvedValue(signedInIdentity);

    renderShopperSite("sunshine-senior-benefits");

    // The branded shell renders, and the toggle to the workspace is present.
    const toggleLink = await screen.findByRole("link", {
      name: "Back to the agent workspace",
    });
    expect(toggleLink).toHaveAttribute("href", "/app");
    // The surface stayed public — no redirect away from the storefront.
    expect(
      document.getElementById("shopper-masthead-wordmark"),
    ).toHaveTextContent("Sunshine Senior Benefits");
  });

  it("shows no toggle for a signed-out shopper (the public default)", async () => {
    listTenantsMock.mockResolvedValue(sampleTenants);
    // /me rejects (the beforeEach default) → signed-out.

    renderShopperSite("sunshine-senior-benefits");

    await waitFor(() => {
      expect(
        document.getElementById("shopper-masthead-wordmark"),
      ).toHaveTextContent("Sunshine Senior Benefits");
    });
    // A signed-out shopper browses freely with no workspace toggle.
    expect(
      document.getElementById("shopper-masthead-surface-toggle"),
    ).toBeNull();
  });
});

describe("Shopper site robust states", () => {
  it("shows a loading state while the tenant list is in flight", async () => {
    // A never-settling promise holds the page in its loading state.
    listTenantsMock.mockReturnValue(new Promise<Tenant[]>(() => {}));

    renderShopperSite("sunshine-senior-benefits");

    await waitFor(() => {
      expect(
        document.getElementById("shopper-loading-skeleton"),
      ).toBeInTheDocument();
    });
  });

  it("shows a friendly not-found for an unknown slug, linking to the picker", async () => {
    listTenantsMock.mockResolvedValue(sampleTenants);

    renderShopperSite("acme-nonexistent");

    await waitFor(() => {
      expect(
        document.getElementById("shopper-not-found"),
      ).toBeInTheDocument();
    });
    // The branded shell never rendered for the bad slug.
    expect(document.getElementById("shopper-masthead")).not.toBeInTheDocument();
    // The recovery link points back to the tenant picker.
    expect(document.getElementById("shopper-not-found-link")).toHaveAttribute(
      "href",
      "/select-tenant",
    );
  });

  it("shows an error and retries the fetch when listTenants rejects", async () => {
    listTenantsMock
      .mockRejectedValueOnce(new Error("server error"))
      .mockResolvedValueOnce(sampleTenants);

    renderShopperSite("sunshine-senior-benefits");

    const retryButton = await screen.findByRole("button", { name: "Retry" });
    expect(document.getElementById("shopper-error")).toBeInTheDocument();

    fireEvent.click(retryButton);

    // The retry loaded the tenants — the branded shell now renders.
    await waitFor(() => {
      expect(
        document.getElementById("shopper-masthead-wordmark"),
      ).toHaveTextContent("Sunshine Senior Benefits");
    });
  });
});

describe("Shopper site routing", () => {
  it("redirects /site (no slug) to the tenant picker", async () => {
    listTenantsMock.mockResolvedValue(sampleTenants);

    render(
      <SessionProvider>
        <MemoryRouter initialEntries={["/site"]}>
          <App />
        </MemoryRouter>
      </SessionProvider>,
    );

    // The select-tenant page renders instead of the Shopper shell.
    await waitFor(() => {
      expect(
        document.getElementById("select-tenant-headline"),
      ).toBeInTheDocument();
    });
    expect(document.getElementById("shopper-masthead")).not.toBeInTheDocument();
  });
});
