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

  it("seeds the event-driven explainer affordance (Epic 19)", () => {
    renderLanding();

    const trigger = document.getElementById("explainer-landing-trigger");
    expect(trigger).toBeInTheDocument();
    expect(trigger).toHaveAttribute("aria-label", "Explain: event-driven operations");
  });

  it("seeds the Simulated badge beside the safe-note (Epic 20)", () => {
    renderLanding();

    // The badge sits inside the "simulated & safe to explore" note.
    const safeNote = document.getElementById("landing-safe-note");
    const trigger = document.getElementById("simulated-landing-trigger");
    expect(trigger).toBeInTheDocument();
    expect(safeNote).toContainElement(trigger);
    expect(trigger).toHaveAttribute(
      "aria-label",
      "Simulated: the whole demo — what is mocked vs real",
    );
    expect(
      document.getElementById("simulated-landing-stamp-label"),
    ).toHaveTextContent("Simulated");
  });
});
