// Tests for the editorial landing page. Uses the suite's existing pattern —
// @testing-library/react (no user-event, which is not a project dependency). The
// CTA renders a react-router <Link>, so the page is wrapped in a MemoryRouter.

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import LandingPage from "./LandingPage.tsx";

function renderLanding() {
  return render(
    <MemoryRouter>
      <LandingPage />
    </MemoryRouter>,
  );
}

describe("LandingPage", () => {
  it("renders the CTA as a link into tenant selection", () => {
    renderLanding();

    const cta = screen.getByRole("link", { name: "Choose a demo tenant" });
    expect(cta).toHaveAttribute("href", "/select-tenant");
  });

  it("mounts the global footer (the PageLayout path)", () => {
    renderLanding();

    expect(document.getElementById("app-footer")).toBeInTheDocument();
  });
});
