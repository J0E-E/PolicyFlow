// Tests for the public "How it's built" page (Epic 21). Uses the suite's existing
// pattern — @testing-library/react (no user-event, which is not a project
// dependency). The page renders react-router <Link>s (the back-home link, via
// PageLayout's Footer), so it is wrapped in a MemoryRouter.

import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import HowItsBuiltPage from "./HowItsBuiltPage.tsx";
import { howItsBuiltPatterns } from "./howItsBuiltContent.ts";

function renderPage(initialPath = "/how-its-built") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/how-its-built" element={<HowItsBuiltPage />} />
        {/* A stand-in landing so the back-home link has somewhere to resolve. */}
        <Route
          path="/"
          element={<div id="test-landing-stub">Landing</div>}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("HowItsBuiltPage", () => {
  it("renders publicly with the hero + Why PolicyFlow motivation (no guard/redirect)", () => {
    renderPage();

    // The page renders directly — it sits OUTSIDE RequireSession, so no session and
    // no redirect: the hero and motivation are present.
    expect(
      document.getElementById("how-its-built-hero-title"),
    ).toHaveTextContent("How it's built");
    expect(
      document.getElementById("how-its-built-motivation"),
    ).toHaveTextContent(/working portrait of the engineering/i);
    // It is the page heading (h1), so the cards can nest under it.
    expect(
      screen.getByRole("heading", { level: 1, name: "How it's built" }),
    ).toBeInTheDocument();
  });

  it("carries a back-home link to /", () => {
    renderPage();

    const backLink = document.getElementById("how-its-built-back-link");
    expect(backLink).toHaveTextContent(/Back to PolicyFlow/);
    expect(backLink).toHaveAttribute("href", "/");
  });

  it("renders the five pattern cards, each deep-linking to its real GitHub source", () => {
    renderPage();

    const expectedHrefs: Record<string, string> = {
      auth: "https://github.com/J0E-E/PolicyFlow/tree/main/core/app/auth",
      tenancy: "https://github.com/J0E-E/PolicyFlow/tree/main/core/app/tenancy",
      pii: "https://github.com/J0E-E/PolicyFlow/tree/main/core/app/pii",
      audit: "https://github.com/J0E-E/PolicyFlow/tree/main/core/app/audit",
      events: "https://github.com/J0E-E/PolicyFlow/tree/main/core/app/events",
    };

    expect(howItsBuiltPatterns).toHaveLength(5);

    for (const pattern of howItsBuiltPatterns) {
      // The card and its title render.
      expect(
        document.getElementById(`how-its-built-pattern-${pattern.key}-title`),
      ).toHaveTextContent(pattern.title);
      // Its GitHub deep link points at the verified directory, in a new tab.
      const link = document.getElementById(
        `how-its-built-pattern-${pattern.key}-link`,
      );
      expect(link).toHaveAttribute("href", expectedHrefs[pattern.key]);
      expect(link).toHaveAttribute("target", "_blank");
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
      expect(link).toHaveTextContent("View the code on GitHub");
    }
  });

  it("renders mechanism terms in the cards as mono <code>", () => {
    renderPage();

    // The tenancy card sets "schema-per-tenant" in mono.
    const mono = document.getElementById("how-its-built-pattern-tenancy-mono-1");
    expect(mono?.tagName).toBe("CODE");
    expect(mono).toHaveTextContent("schema-per-tenant");
  });

  it("renders the ink-console architecture placeholder + real-vs-simulated legend", () => {
    renderPage();

    // The console panel titled with its stamp overline + placeholder note.
    expect(
      document.getElementById("how-its-built-architecture"),
    ).toBeInTheDocument();
    expect(
      document.getElementById("how-its-built-architecture-overline"),
    ).toHaveTextContent("Architecture");
    expect(
      document.getElementById("how-its-built-architecture-note"),
    ).toHaveTextContent(/annotated architecture diagram arrives/i);

    // The "Real engine" legend row: a swatch + its label + description.
    expect(
      document.getElementById("how-its-built-architecture-legend-real-label"),
    ).toHaveTextContent("Real engine");
    expect(
      document.getElementById(
        "how-its-built-architecture-legend-real-description",
      ),
    ).toHaveTextContent(/outbox, event bus, retries, DLQ/i);

    // The Simulated legend row: the Epic 20 SimulatedBadge trigger + description.
    const simulatedTrigger = document.getElementById(
      "how-its-built-architecture-legend-simulated-badge-trigger",
    );
    expect(simulatedTrigger).toBeInTheDocument();
    expect(simulatedTrigger).toHaveAttribute(
      "aria-label",
      "Simulated: the external adapters — what is mocked vs real",
    );
    expect(
      document.getElementById(
        "how-its-built-architecture-legend-simulated-description",
      ),
    ).toHaveTextContent(/carrier \/ enrichment \/ CRM adapters/i);
  });

  it("mounts the global footer (the public PageLayout path)", () => {
    renderPage();

    expect(document.getElementById("app-footer")).toBeInTheDocument();
  });
});
