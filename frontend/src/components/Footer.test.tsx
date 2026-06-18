// Tests for the global Footer chrome. Uses the suite's existing pattern —
// @testing-library/react (no user-event, which is not a project dependency).
// Footer renders plain anchors, so no MemoryRouter is needed.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Footer from "./Footer.tsx";

describe("Footer", () => {
  it("renders a single contentinfo landmark", () => {
    render(<Footer />);

    expect(screen.getByRole("contentinfo")).toBeInTheDocument();
    expect(document.getElementById("app-footer")).toBeInTheDocument();
  });

  it("links to the repository with the correct href", () => {
    render(<Footer />);

    const repoLink = screen.getByRole("link", { name: "PolicyFlow on GitHub" });
    expect(repoLink).toHaveAttribute(
      "href",
      "https://github.com/J0E-E/PolicyFlow",
    );
  });

  it("links to the author with the correct href", () => {
    render(<Footer />);

    const authorLink = screen.getByRole("link", { name: "Joey Iglesias" });
    expect(authorLink).toHaveAttribute("href", "https://github.com/J0E-E");
  });

  it("opens both external links safely in a new tab", () => {
    render(<Footer />);

    for (const link of screen.getAllByRole("link")) {
      expect(link).toHaveAttribute("target", "_blank");
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
    }
  });
});
