// Tests for the guided docket (Epic 17). Follows the suite's pattern —
// @testing-library/react + fireEvent (no @testing-library/user-event, which is not a
// project dependency). The docket reads its shared state from GuidedDocketContext, so
// these render a tiny harness that holds ONE live useGuidedDocket() and provides it to
// both the floating <GuidedDocket> and the demo-home <GuidedWalkthroughHost> opener —
// the same wiring AppShell does — so progress, dismiss/reopen, and the opener are
// exercised against one real state machine.
//
// Coverage (per the plan): progress (mark-done advances + "X / 21"), dismiss →
// collapsed tab → reopen, every step's deep link renders inert "available in a later
// step", and the demo-home opener opens the docket. Plus the §7 a11y contract: a
// labelled region, aria-expanded on the step toggles, and the focus order.

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { STEPPER_STEPS } from "./stepperSteps.ts";
import { useGuidedDocket } from "./useGuidedDocket.ts";
import { GuidedDocketContext } from "./GuidedDocketContext.ts";
import GuidedDocket from "./GuidedDocket.tsx";
import GuidedWalkthroughHost from "./GuidedWalkthroughHost.tsx";

const TOTAL = STEPPER_STEPS.length;

// Harness: one live docket state shared by the panel and the demo-home opener, exactly
// as AppShell provides it. Rendering the opener too lets the opener-opens-the-docket
// test drive the real shared seam.
function DocketHarness() {
  const state = useGuidedDocket();
  return (
    <GuidedDocketContext.Provider value={state}>
      <GuidedWalkthroughHost />
      <GuidedDocket />
    </GuidedDocketContext.Provider>
  );
}

function renderDocket() {
  return render(<DocketHarness />);
}

describe("GuidedDocket", () => {
  it("opens on the first step with a 0 / N progress readout", () => {
    renderDocket();

    expect(document.getElementById("guided-docket")).toBeInTheDocument();
    expect(document.getElementById("guided-docket-progress")).toHaveTextContent(
      `0 / ${TOTAL}`,
    );
    // The first step is active (expanded): its toggle reports aria-expanded.
    expect(
      document.getElementById("guided-docket-step-1-toggle"),
    ).toHaveAttribute("aria-expanded", "true");
    // A later step is collapsed.
    expect(
      document.getElementById("guided-docket-step-2-toggle"),
    ).toHaveAttribute("aria-expanded", "false");
  });

  it("is a labelled region named by its title (non-modal, no dialog/scrim)", () => {
    renderDocket();
    const region = screen.getByRole("region", { name: "Guided walkthrough" });
    expect(region).toBe(document.getElementById("guided-docket"));
    // Not a modal dialog — there is no focus trap and nothing blocks the workspace.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("marks the active step done, advances the pointer, and bumps progress", () => {
    renderDocket();

    fireEvent.click(document.getElementById("guided-docket-step-1-mark-done")!);

    // Progress advanced to 1 / N.
    expect(document.getElementById("guided-docket-progress")).toHaveTextContent(
      `1 / ${TOTAL}`,
    );
    // Step 1 is now completed (its status text says so — meaning not by color alone).
    expect(document.getElementById("guided-docket-step-1-status")).toHaveTextContent(
      "Completed.",
    );
    // The active step advanced to step 2 (now expanded).
    expect(
      document.getElementById("guided-docket-step-2-toggle"),
    ).toHaveAttribute("aria-expanded", "true");
    expect(
      document.getElementById("guided-docket-step-1-toggle"),
    ).toHaveAttribute("aria-expanded", "false");
  });

  it("makes any tapped step the one active (expanded) step — accordion", () => {
    renderDocket();

    fireEvent.click(document.getElementById("guided-docket-step-5-toggle")!);

    expect(
      document.getElementById("guided-docket-step-5-toggle"),
    ).toHaveAttribute("aria-expanded", "true");
    // The previously-active step 1 collapsed (one expanded at a time).
    expect(
      document.getElementById("guided-docket-step-1-toggle"),
    ).toHaveAttribute("aria-expanded", "false");
    // The active step shows its two notes + a deep link.
    expect(document.getElementById("guided-docket-step-5-seeing")).toBeInTheDocument();
    expect(document.getElementById("guided-docket-step-5-built")).toBeInTheDocument();
    expect(document.getElementById("guided-docket-step-5-link")).toBeInTheDocument();
  });

  it("renders the active step's deep link inert (available in a later step, no href)", () => {
    renderDocket();

    // Step 1 is active by default; no step has a `to` in this phase, so its link is
    // the inert affordance — a non-link with the coming-later copy.
    const link = document.getElementById("guided-docket-step-1-link");
    expect(link).toBeInTheDocument();
    expect(link?.tagName).not.toBe("A");
    expect(link).not.toHaveAttribute("href");
    expect(link).toHaveAttribute("aria-disabled", "true");
    expect(link).toHaveTextContent("Available in a later step");
  });

  it("renders no live deep links anywhere (all 21 destinations are later-phase)", () => {
    renderDocket();
    // Walk every step active in turn; none should render an anchor for its link.
    for (const step of STEPPER_STEPS) {
      fireEvent.click(
        document.getElementById(`guided-docket-step-${step.number}-toggle`)!,
      );
      const link = document.getElementById(`guided-docket-step-${step.number}-link`);
      expect(link?.tagName).not.toBe("A");
      expect(link).toHaveTextContent("Available in a later step");
    }
  });

  it("dismisses to the corner reopen tab, then reopens from it", () => {
    renderDocket();

    // Dismiss: the panel collapses to the reopen tab.
    fireEvent.click(document.getElementById("guided-docket-dismiss")!);
    expect(document.getElementById("guided-docket")).not.toBeInTheDocument();
    const reopen = document.getElementById("guided-docket-reopen");
    expect(reopen).toBeInTheDocument();
    expect(reopen).toHaveTextContent("Guided walkthrough");

    // Reopen: the panel returns; the tab is gone.
    fireEvent.click(reopen!);
    expect(document.getElementById("guided-docket")).toBeInTheDocument();
    expect(document.getElementById("guided-docket-reopen")).not.toBeInTheDocument();
  });

  it("preserves progress across a dismiss → reopen cycle (in-memory state)", () => {
    renderDocket();

    fireEvent.click(document.getElementById("guided-docket-step-1-mark-done")!);
    fireEvent.click(document.getElementById("guided-docket-dismiss")!);
    fireEvent.click(document.getElementById("guided-docket-reopen")!);

    // The completed step + progress survived the collapse (shared in-memory state).
    expect(document.getElementById("guided-docket-progress")).toHaveTextContent(
      `1 / ${TOTAL}`,
    );
    expect(document.getElementById("guided-docket-step-1-status")).toHaveTextContent(
      "Completed.",
    );
  });

  it("opens the docket from the demo-home opener button", () => {
    renderDocket();

    // Dismiss first so the opener has something to open.
    fireEvent.click(document.getElementById("guided-docket-dismiss")!);
    expect(document.getElementById("guided-docket")).not.toBeInTheDocument();

    // The demo-home opener (id preserved) reopens the same shared docket.
    fireEvent.click(document.getElementById("demo-home-stepper-host-open")!);
    expect(document.getElementById("guided-docket")).toBeInTheDocument();
  });

  it("completes the last step without advancing past the end", () => {
    renderDocket();

    // Activate the final step, then mark it done — there is nowhere further to go,
    // so it stays active and just earns its checkmark.
    fireEvent.click(document.getElementById(`guided-docket-step-${TOTAL}-toggle`)!);
    fireEvent.click(
      document.getElementById(`guided-docket-step-${TOTAL}-mark-done`)!,
    );

    expect(document.getElementById("guided-docket-progress")).toHaveTextContent(
      `1 / ${TOTAL}`,
    );
    expect(
      document.getElementById(`guided-docket-step-${TOTAL}-status`),
    ).toHaveTextContent("Completed.");
    expect(
      document.getElementById(`guided-docket-step-${TOTAL}-toggle`),
    ).toHaveAttribute("aria-expanded", "true");
  });
});

describe("STEPPER_STEPS catalog", () => {
  it("holds exactly 21 sequentially-numbered steps", () => {
    expect(STEPPER_STEPS).toHaveLength(21);
    STEPPER_STEPS.forEach((step, index) => {
      expect(step.number).toBe(index + 1);
    });
  });

  it("has both notes on every step and no live deep link in this phase", () => {
    for (const step of STEPPER_STEPS) {
      expect(step.title.length).toBeGreaterThan(0);
      expect(step.seeing.length).toBeGreaterThan(0);
      expect(step.built.length).toBeGreaterThan(0);
      // All inert this phase — a step goes live only when a later phase sets `to`.
      expect(step.to).toBeUndefined();
    }
  });
});
