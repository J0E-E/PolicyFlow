// Tests for the Card primitive. Uses the suite's pattern —
// @testing-library/react (no user-event, which is not a project dependency).
// Card is pure and non-interactive, so these assert structure, the heading-level
// option, and the accessibility contract (aria-labelledby only when titled).

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Card from "./Card.tsx";

describe("Card", () => {
  it("renders a <section> carrying the card class", () => {
    render(<Card id="summary-card">Body content</Card>);

    const card = document.getElementById("summary-card");
    expect(card).toBeInTheDocument();
    expect(card?.tagName).toBe("SECTION");
    expect(card).toHaveClass("card");
  });

  it("renders the title as an h2 and labels the section by it", () => {
    render(
      <Card id="summary-card" title="Account summary">
        Body content
      </Card>,
    );

    const heading = screen.getByRole("heading", { name: "Account summary" });
    expect(heading.tagName).toBe("H2");
    expect(heading).toHaveAttribute("id", "summary-card-title");

    const card = document.getElementById("summary-card");
    expect(card).toHaveAttribute("aria-labelledby", "summary-card-title");
  });

  it("honors headingLevel for the title tag", () => {
    render(
      <Card id="summary-card" title="Account summary" headingLevel={3}>
        Body content
      </Card>,
    );

    const heading = screen.getByRole("heading", { name: "Account summary" });
    expect(heading.tagName).toBe("H3");
  });

  it("renders no title element and no aria-labelledby when untitled", () => {
    render(<Card id="summary-card">Body content</Card>);

    expect(document.getElementById("summary-card-title")).toBeNull();
    expect(document.getElementById("summary-card")).not.toHaveAttribute(
      "aria-labelledby",
    );
  });

  it("renders children inside the body", () => {
    render(
      <Card id="summary-card">
        <span data-testid="child">Body content</span>
      </Card>,
    );

    const body = document.getElementById("summary-card-body");
    expect(body).toBeInTheDocument();
    expect(body).toContainElement(screen.getByTestId("child"));
  });

  it("renders the footer only when provided", () => {
    const { rerender } = render(<Card id="summary-card">Body content</Card>);
    expect(document.getElementById("summary-card-footer")).toBeNull();

    rerender(
      <Card id="summary-card" footer={<button type="button">Save</button>}>
        Body content
      </Card>,
    );
    const footer = document.getElementById("summary-card-footer");
    expect(footer).toBeInTheDocument();
    expect(footer).toContainElement(screen.getByRole("button", { name: "Save" }));
  });
});
