// Tests for the SimulatedBadge (Epic 20). It wraps the Epic 9 Popover (whose own
// keyboard/focus contract is covered in Popover.test.tsx), so these focus on what
// this layer adds: the dashed warning-stamp trigger (flask icon + "Simulated"
// label, reusing the Epic 8 StampTag warning styling per Guide §6.3), the three
// fixed small-caps sections render with their labels, the mono runs render as
// <code>, and the open -> Esc-closes / focus-trap path works through the wrapper.
// Uses the suite's pattern — @testing-library/react + fireEvent (no user-event,
// which is not a project dependency).

import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import SimulatedBadge from "./SimulatedBadge.tsx";
import type { SimulatedNotice } from "./simulatedNotice.ts";

// A three-section fixture carrying a mono run so the <code> rendering is exercised.
const fixtureNotice: SimulatedNotice = {
  whatIsMocked: ["The outside systems return ", { mono: "canned" }, " answers."],
  whatIsReal: ["The ", { mono: "outbox" }, " is real, working code."],
  theAdapterSeam: ["One small ", { mono: "adapter" }, " interface, a drop-in swap."],
};

function renderBadge(notice?: SimulatedNotice) {
  return render(
    <SimulatedBadge
      id="simulated-test"
      surfaceLabel="the test surface"
      notice={notice}
    />,
  );
}

describe("SimulatedBadge", () => {
  it("renders a dashed warning-stamp trigger with an accessible name, closed by default", () => {
    renderBadge(fixtureNotice);

    const trigger = document.getElementById("simulated-test-trigger");
    expect(trigger).toBeInTheDocument();
    expect(trigger).toHaveClass("simulated-badge-trigger");
    expect(trigger).toHaveAttribute(
      "aria-label",
      "Simulated: the test surface — what is mocked vs real",
    );

    // The stamp reuses the StampTag warning styling (the dashed border is the CSS
    // override per Guide §6.3); its always-present text label carries meaning.
    const stamp = document.getElementById("simulated-test-stamp");
    expect(stamp).toHaveClass("stamp-tag", "stamp-tag-warning");
    expect(document.getElementById("simulated-test-stamp-label")).toHaveTextContent(
      "Simulated",
    );

    // Closed by default — no notice surface yet.
    expect(document.getElementById("simulated-test-surface")).toBeNull();
  });

  it("opens to a labelled dialog showing the three official-notice sections", () => {
    renderBadge(fixtureNotice);
    fireEvent.click(document.getElementById("simulated-test-trigger")!);

    const surface = document.getElementById("simulated-test-surface");
    expect(surface).toHaveAttribute("role", "dialog");
    expect(surface).toHaveAttribute("aria-label", "Simulated: the test surface");

    expect(
      document.getElementById("simulated-test-label-whatIsMocked"),
    ).toHaveTextContent("WHAT IS MOCKED");
    expect(
      document.getElementById("simulated-test-label-whatIsReal"),
    ).toHaveTextContent("WHAT IS REAL");
    expect(
      document.getElementById("simulated-test-label-theAdapterSeam"),
    ).toHaveTextContent("THE ADAPTER SEAM");
  });

  it("renders mono runs as <code> in the mono register", () => {
    renderBadge(fixtureNotice);
    fireEvent.click(document.getElementById("simulated-test-trigger")!);

    const monoTerm = document.getElementById("simulated-test-mono-whatIsReal-1");
    expect(monoTerm).toBeInTheDocument();
    expect(monoTerm?.tagName).toBe("CODE");
    expect(monoTerm).toHaveTextContent("outbox");
    expect(monoTerm).toHaveClass("simulated-notice-mono");

    // The surrounding prose still reads as one sentence with the term inline.
    expect(
      document.getElementById("simulated-test-body-whatIsReal"),
    ).toHaveTextContent("The outbox is real, working code.");
  });

  it("falls back to the foundational notice copy when no notice is supplied", () => {
    renderBadge();
    fireEvent.click(document.getElementById("simulated-test-trigger")!);

    // The default notice's WHAT IS REAL section carries the real `outbox` engine.
    expect(
      document.getElementById("simulated-test-body-whatIsReal"),
    ).toHaveTextContent("The PolicyFlow engine driving them is real, working code.");
    expect(
      document.getElementById("simulated-test-mono-whatIsReal-1"),
    ).toHaveTextContent("outbox");
  });

  it("closes on Esc and restores focus to the trigger (through the wrapper)", () => {
    renderBadge(fixtureNotice);
    const trigger = document.getElementById("simulated-test-trigger")!;

    fireEvent.click(trigger);
    const surface = document.getElementById("simulated-test-surface")!;
    expect(surface).toHaveFocus();

    fireEvent.keyDown(surface, { key: "Escape" });

    expect(document.getElementById("simulated-test-surface")).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("traps focus on the surface (no interior controls) on Tab", () => {
    renderBadge(fixtureNotice);
    fireEvent.click(document.getElementById("simulated-test-trigger")!);

    const surface = document.getElementById("simulated-test-surface")!;
    expect(surface).toHaveFocus();
    // The notice body is text-only, so Tab pins focus to the panel container.
    fireEvent.keyDown(surface, { key: "Tab" });
    expect(surface).toHaveFocus();
  });
});
