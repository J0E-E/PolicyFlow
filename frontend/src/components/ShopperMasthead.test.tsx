// Tests for the consumer ShopperMasthead and its Epic 24 surface-toggle gating. The
// masthead is pure/props-only (the page reads `useSession` and threads the boolean
// in), so it renders directly under a MemoryRouter (the toggle is a <Link>). These
// assert that a signed-in visitor sees the "← Back to the agent workspace" toggle to
// /app and a signed-out shopper sees none. Uses the suite's pattern —
// @testing-library/react + fireEvent (no user-event, not a project dependency).

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import ShopperMasthead from "./ShopperMasthead.tsx";

function renderMasthead(isSignedIn: boolean) {
  return render(
    <MemoryRouter>
      <ShopperMasthead
        tenantSlug="sunshine-senior-benefits"
        tenantName="Sunshine Senior Benefits"
        isSignedIn={isSignedIn}
      />
    </MemoryRouter>,
  );
}

describe("ShopperMasthead", () => {
  it("always renders the tenant seal + name wordmark", () => {
    renderMasthead(false);

    expect(document.getElementById("shopper-masthead-seal")).toHaveAttribute(
      "src",
      "/seals/sunshine-senior-benefits.svg",
    );
    expect(
      document.getElementById("shopper-masthead-wordmark"),
    ).toHaveTextContent("Sunshine Senior Benefits");
  });

  it("shows the surface toggle to /app for a signed-in visitor (Epic 24)", () => {
    renderMasthead(true);

    const toggleLink = screen.getByRole("link", {
      name: "Back to the agent workspace",
    });
    expect(toggleLink).toBe(
      document.getElementById("shopper-masthead-surface-toggle-link"),
    );
    expect(toggleLink).toHaveAttribute("href", "/app");
  });

  it("shows no surface toggle for a signed-out shopper (Epic 24)", () => {
    renderMasthead(false);

    // A signed-out visitor browses the storefront freely, but there is no workspace
    // to return to — so no toggle.
    expect(
      document.getElementById("shopper-masthead-surface-toggle"),
    ).toBeNull();
    expect(
      screen.queryByRole("link", { name: "Back to the agent workspace" }),
    ).toBeNull();
  });
});
