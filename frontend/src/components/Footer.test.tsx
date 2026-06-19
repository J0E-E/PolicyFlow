// Tests for the global Footer chrome. Uses the suite's existing pattern —
// @testing-library/react (no user-event, which is not a project dependency). The
// footer now renders an in-app react-router <Link> ("How it's built", Epic 21), so
// it is wrapped in a MemoryRouter.

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import Footer from "./Footer.tsx";

function renderFooter() {
  return render(
    <MemoryRouter>
      <Footer />
    </MemoryRouter>,
  );
}

describe("Footer", () => {
  it("renders a single contentinfo landmark", () => {
    renderFooter();

    expect(screen.getByRole("contentinfo")).toBeInTheDocument();
    expect(document.getElementById("app-footer")).toBeInTheDocument();
  });

  it("links to the public How it's built page in-app (Epic 21)", () => {
    renderFooter();

    const howItsBuiltLink = screen.getByRole("link", { name: "How it's built" });
    expect(howItsBuiltLink).toBe(
      document.getElementById("app-footer-how-its-built-link"),
    );
    // Same-tab SPA nav: a react-router <Link>, so no new-tab target/rel.
    expect(howItsBuiltLink).toHaveAttribute("href", "/how-its-built");
    expect(howItsBuiltLink).not.toHaveAttribute("target");
  });

  it("links to the repository with the correct href", () => {
    renderFooter();

    const repoLink = screen.getByRole("link", { name: "PolicyFlow on GitHub" });
    expect(repoLink).toHaveAttribute(
      "href",
      "https://github.com/J0E-E/PolicyFlow",
    );
  });

  it("links to the author with the correct href", () => {
    renderFooter();

    const authorLink = screen.getByRole("link", { name: "Joey Iglesias" });
    expect(authorLink).toHaveAttribute("href", "https://github.com/J0E-E");
  });

  it("opens both external links safely in a new tab", () => {
    renderFooter();

    for (const link of [
      screen.getByRole("link", { name: "PolicyFlow on GitHub" }),
      screen.getByRole("link", { name: "Joey Iglesias" }),
    ]) {
      expect(link).toHaveAttribute("target", "_blank");
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
    }
  });
});
