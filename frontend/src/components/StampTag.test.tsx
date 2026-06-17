// Tests for the StampTag primitive. Uses the suite's pattern —
// @testing-library/react (no user-event, which is not a project dependency).
// StampTag is pure and non-interactive, so these assert structure, classes, and
// the accessibility contract (always-present natural-case label, aria-hidden icon).

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import StampTag from "./StampTag.tsx";
import type { StampStatus } from "./StampTag.tsx";

describe("StampTag", () => {
  const statuses: StampStatus[] = [
    "success",
    "pending",
    "warning",
    "error",
    "neutral",
  ];

  it.each(statuses)("renders the %s status with its status class", (status) => {
    render(
      <StampTag id="record-status" status={status}>
        Approved
      </StampTag>,
    );

    const stamp = document.getElementById("record-status");
    expect(stamp).toHaveClass("stamp-tag", `stamp-tag-${status}`);
  });

  it("defaults to the status variant", () => {
    render(
      <StampTag id="record-status" status="warning">
        Pending review
      </StampTag>,
    );

    const stamp = document.getElementById("record-status");
    expect(stamp).toHaveClass("stamp-tag-warning");
    expect(stamp).not.toHaveClass("stamp-tag-overline");
  });

  it("renders the overline variant with no status class", () => {
    render(
      <StampTag id="section-overline" variant="overline">
        Event timeline
      </StampTag>,
    );

    const stamp = document.getElementById("section-overline");
    expect(stamp).toHaveClass("stamp-tag", "stamp-tag-overline");
    expect(stamp?.className).not.toMatch(/stamp-tag-(success|pending|warning|error|neutral)/);
  });

  it("renders the id and the derived label-span id with natural-case text", () => {
    render(
      <StampTag id="record-status" status="neutral">
        Awaiting review
      </StampTag>,
    );

    expect(document.getElementById("record-status")).toBeInTheDocument();
    const label = document.getElementById("record-status-label");
    expect(label).toBeInTheDocument();
    // Authored natural-case; CSS does the uppercasing, so the DOM text is words.
    expect(label).toHaveTextContent("Awaiting review");
  });

  it("renders the icon slot aria-hidden when an icon is given", () => {
    render(
      <StampTag id="record-status" status="warning" icon={<svg data-testid="glyph" />}>
        Caution
      </StampTag>,
    );

    const icon = document.getElementById("record-status-icon");
    expect(icon).toBeInTheDocument();
    expect(icon).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByTestId("glyph")).toBeInTheDocument();
  });

  it("renders no icon slot when no icon is given", () => {
    render(
      <StampTag id="record-status" status="warning">
        Caution
      </StampTag>,
    );

    expect(document.getElementById("record-status-icon")).toBeNull();
  });
});
