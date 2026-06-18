// Tests for the ExplainerPopover (Epic 19). It wraps the Epic 9 Popover (whose own
// keyboard/focus contract is covered in Popover.test.tsx), so these focus on what
// this layer adds: the four fixed small-caps sections render with their labels, the
// mono runs render as <code>, CRM PARALLEL is omitted when a surface supplies none,
// and the open -> Esc-closes / focus-trap path works through the wrapper. Uses the
// suite's pattern — @testing-library/react + fireEvent (no user-event, which is not
// a project dependency).

import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ExplainerPopover from "./ExplainerPopover.tsx";
import type { ExplainerContent } from "./explainerContent.ts";

// A four-section fixture (with CRM PARALLEL) carrying a mono run in every section
// so the <code> rendering is exercised.
const fullContent: ExplainerContent = {
  pattern: ["A pattern with a ", { mono: "mechanism" }, " term."],
  how: ["It uses an ", { mono: "outbox" }, " under the hood."],
  realVsSimulated: ["Real ", { mono: "code" }, " vs simulated data."],
  crmParallel: ["Salesforce ", { mono: "Platform Events" }, "."],
};

// The same shape minus CRM PARALLEL (the session-model surface omits it).
const noCrmContent: ExplainerContent = {
  pattern: ["Pattern only."],
  how: ["How only."],
  realVsSimulated: ["Real vs simulated only."],
};

function renderExplainer(content: ExplainerContent = fullContent) {
  return render(
    <ExplainerPopover
      id="explainer-test"
      surfaceLabel="the test surface"
      content={content}
    />,
  );
}

describe("ExplainerPopover", () => {
  it("renders an info-icon trigger with an accessible name, closed by default", () => {
    renderExplainer();

    const trigger = document.getElementById("explainer-test-trigger");
    expect(trigger).toBeInTheDocument();
    expect(trigger).toHaveAttribute("aria-label", "Explain: the test surface");
    // The decorative glyph is present but the surface is closed.
    expect(document.getElementById("explainer-test-icon")).toBeInTheDocument();
    expect(document.getElementById("explainer-test-surface")).toBeNull();
  });

  it("opens to a labelled dialog showing all four sections with their labels", () => {
    renderExplainer();
    fireEvent.click(document.getElementById("explainer-test-trigger")!);

    const surface = document.getElementById("explainer-test-surface");
    expect(surface).toHaveAttribute("role", "dialog");
    expect(surface).toHaveAttribute(
      "aria-label",
      "How this works: the test surface",
    );

    expect(
      document.getElementById("explainer-test-label-pattern"),
    ).toHaveTextContent("PATTERN");
    expect(
      document.getElementById("explainer-test-label-how"),
    ).toHaveTextContent("HOW POLICYFLOW DOES IT");
    expect(
      document.getElementById("explainer-test-label-realVsSimulated"),
    ).toHaveTextContent("REAL VS SIMULATED");
    expect(
      document.getElementById("explainer-test-label-crmParallel"),
    ).toHaveTextContent("CRM PARALLEL");
  });

  it("renders mono runs as <code> in the mono register", () => {
    renderExplainer();
    fireEvent.click(document.getElementById("explainer-test-trigger")!);

    const monoTerm = document.getElementById("explainer-test-mono-how-1");
    expect(monoTerm).toBeInTheDocument();
    expect(monoTerm?.tagName).toBe("CODE");
    expect(monoTerm).toHaveTextContent("outbox");
    expect(monoTerm).toHaveClass("explainer-mono");

    // The surrounding prose still reads as a single sentence with the term inline.
    expect(
      document.getElementById("explainer-test-body-how"),
    ).toHaveTextContent("It uses an outbox under the hood.");
  });

  it("omits the CRM PARALLEL section when a surface supplies no copy", () => {
    renderExplainer(noCrmContent);
    fireEvent.click(document.getElementById("explainer-test-trigger")!);

    // The first three sections still render…
    expect(
      document.getElementById("explainer-test-label-pattern"),
    ).toBeInTheDocument();
    expect(
      document.getElementById("explainer-test-label-realVsSimulated"),
    ).toBeInTheDocument();
    // …but CRM PARALLEL is absent.
    expect(
      document.getElementById("explainer-test-label-crmParallel"),
    ).toBeNull();
  });

  it("closes on Esc and restores focus to the trigger (through the wrapper)", () => {
    renderExplainer();
    const trigger = document.getElementById("explainer-test-trigger")!;

    fireEvent.click(trigger);
    const surface = document.getElementById("explainer-test-surface")!;
    expect(surface).toHaveFocus();

    fireEvent.keyDown(surface, { key: "Escape" });

    expect(document.getElementById("explainer-test-surface")).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("traps focus on the surface (no interior controls) on Tab", () => {
    renderExplainer();
    fireEvent.click(document.getElementById("explainer-test-trigger")!);

    const surface = document.getElementById("explainer-test-surface")!;
    expect(surface).toHaveFocus();
    // The explainer body is text-only, so Tab pins focus to the panel container.
    fireEvent.keyDown(surface, { key: "Tab" });
    expect(surface).toHaveFocus();
  });

  it("forwards a triggerClassName onto the wrapped trigger", () => {
    render(
      <ExplainerPopover
        id="explainer-test"
        surfaceLabel="the test surface"
        content={fullContent}
        triggerClassName="masthead-explainer-trigger"
      />,
    );

    const trigger = document.getElementById("explainer-test-trigger");
    expect(trigger).toHaveClass("explainer-trigger", "masthead-explainer-trigger");
  });
});
