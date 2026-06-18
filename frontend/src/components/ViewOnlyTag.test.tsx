// Tests for the ViewOnlyTag posture tag. Uses the suite's pattern —
// @testing-library/react (no user-event, which is not a project dependency).
// The tag is pure and non-interactive, so these assert structure, the derived
// ids, and the accessibility contract (always-present natural-case label, an
// aria-hidden glyph — meaning never by icon alone, Guide §7).

import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ViewOnlyTag from "./ViewOnlyTag.tsx";

describe("ViewOnlyTag", () => {
  it("renders the natural-case label under the derived label-span id", () => {
    render(<ViewOnlyTag id="app-masthead-view-only" />);

    expect(document.getElementById("app-masthead-view-only")).toBeInTheDocument();
    const label = document.getElementById("app-masthead-view-only-label");
    expect(label).toBeInTheDocument();
    // Authored natural-case; CSS uppercases it so screen readers read words.
    expect(label).toHaveTextContent("View only");
  });

  it("renders the lock glyph aria-hidden under the derived icon-span id", () => {
    render(<ViewOnlyTag id="app-masthead-view-only" />);

    const icon = document.getElementById("app-masthead-view-only-icon");
    expect(icon).toBeInTheDocument();
    expect(icon).toHaveAttribute("aria-hidden", "true");
    // The glyph is decoration; the icon span carries no text.
    expect(icon).toHaveTextContent("");
  });
});
