// Tests for the public Shopper site shell and its robust states. jsdom has no
// backend, so `../api` is mocked: `listTenants` is driven per test. The Shopper
// zone is UNAUTHENTICATED — it renders purely from the route slug, with no
// SessionProvider and no `/me` call — so these tests mount only the route under a
// MemoryRouter and assert that no guard / redirect is involved.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Tenant } from "../api";
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

/** Render the Shopper route at `/site/:slug` for the given slug. */
function renderShopperSite(slug: string) {
  return render(
    <MemoryRouter initialEntries={[`/site/${slug}`]}>
      <Routes>
        <Route path="/site/:slug" element={<ShopperSitePage />} />
      </Routes>
    </MemoryRouter>,
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
