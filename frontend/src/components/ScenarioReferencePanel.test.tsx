// Tests for the scenario-reference modal (Epic 18). Follows the suite's pattern —
// @testing-library/react + fireEvent (no @testing-library/user-event, which is not a
// project dependency). The panel is a true MODAL (unlike the non-modal Popover), so
// these assert the Guide §5 / §7 dialog contract — role/aria-modal/labelledby, focus
// into the dialog on open, the focus trap, and Esc / close-button / scrim-click close
// always restoring focus to the opener — plus the catalog render and its STEP /
// DEMO CONTROL markers.
//
// A tiny harness holds the open flag (as AppShell does) and an opener button, so the
// focus-restoration assertions can prove focus returns to the real opener element.

import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ScenarioReferencePanel from "./ScenarioReferencePanel.tsx";
import {
  SCENARIO_CATEGORIES,
  SCENARIO_REFERENCE_INTRO,
} from "./scenarioReference.ts";

// Harness: an opener button + the panel sharing one open flag, mirroring AppShell.
function PanelHarness() {
  const [isOpen, setIsOpen] = useState(false);
  return (
    <>
      <button id="harness-opener" type="button" onClick={() => setIsOpen(true)}>
        Open scenario reference
      </button>
      <ScenarioReferencePanel
        isOpen={isOpen}
        onClose={() => setIsOpen(false)}
      />
    </>
  );
}

function openPanel() {
  render(<PanelHarness />);
  const opener = document.getElementById("harness-opener")!;
  opener.focus();
  fireEvent.click(opener);
  return opener;
}

describe("ScenarioReferencePanel", () => {
  it("renders nothing while closed", () => {
    render(<PanelHarness />);
    expect(document.getElementById("scenario-reference-dialog")).toBeNull();
    expect(document.getElementById("scenario-reference-scrim")).toBeNull();
  });

  it("opens as a labelled, modal dialog described by its intro", () => {
    openPanel();

    const dialog = screen.getByRole("dialog");
    expect(dialog).toBe(document.getElementById("scenario-reference-dialog"));
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAttribute(
      "aria-labelledby",
      "scenario-reference-title",
    );
    expect(dialog).toHaveAttribute(
      "aria-describedby",
      "scenario-reference-intro",
    );
    expect(document.getElementById("scenario-reference-title")).toHaveTextContent(
      "Scenario reference",
    );
    expect(document.getElementById("scenario-reference-intro")).toHaveTextContent(
      SCENARIO_REFERENCE_INTRO,
    );
    // Focus moved into the dialog on open (Guide §7).
    expect(dialog).toHaveFocus();
  });

  it("renders the three categories with every entry as a card + its marker", () => {
    openPanel();

    for (const category of SCENARIO_CATEGORIES) {
      expect(
        document.getElementById(`scenario-reference-category-${category.slug}`),
      ).toBeInTheDocument();
      expect(
        document.getElementById(
          `scenario-reference-category-${category.slug}-title`,
        ),
      ).toHaveTextContent(category.title);

      for (const entry of category.entries) {
        const cardId = `scenario-reference-entry-${entry.slug}-card`;
        expect(document.getElementById(`${cardId}-title`)).toHaveTextContent(
          entry.title,
        );
        expect(document.getElementById(`${cardId}-trigger`)).toHaveTextContent(
          entry.trigger,
        );
        expect(document.getElementById(`${cardId}-outcome`)).toHaveTextContent(
          entry.outcome,
        );
        // The neutral marker names the STEP (or the DEMO CONTROL fallback).
        expect(
          document.getElementById(`${cardId}-marker-label`),
        ).toHaveTextContent(entry.marker);
      }
    }
  });

  it("marks each entry with a STEP or DEMO CONTROL stamp (no internal phase IDs)", () => {
    openPanel();

    const markers = SCENARIO_CATEGORIES.flatMap((category) =>
      category.entries.map((entry) => entry.marker),
    );
    // Exactly the resolved-plan set: six STEP markers + two DEMO CONTROL fallbacks.
    expect(markers).toEqual([
      "STEP 03",
      "STEP 05",
      "STEP 12",
      "STEP 14",
      "DEMO CONTROL",
      "STEP 14",
      "STEP 15",
      "DEMO CONTROL",
    ]);
    // No marker leaks an internal build-phase ID (the Epic 12 / Epic 17 rule).
    for (const marker of markers) {
      expect(marker).not.toMatch(/P\d/);
      expect(marker).toMatch(/^(STEP \d{2}|DEMO CONTROL)$/);
    }
  });

  it("closes on the close button and restores focus to the opener", () => {
    const opener = openPanel();

    fireEvent.click(document.getElementById("scenario-reference-close")!);

    expect(document.getElementById("scenario-reference-dialog")).toBeNull();
    expect(opener).toHaveFocus();
  });

  it("closes on Esc and restores focus to the opener", () => {
    const opener = openPanel();

    fireEvent.keyDown(document.getElementById("scenario-reference-dialog")!, {
      key: "Escape",
    });

    expect(document.getElementById("scenario-reference-dialog")).toBeNull();
    expect(opener).toHaveFocus();
  });

  it("closes on a scrim (outside) mousedown and restores focus to the opener", () => {
    const opener = openPanel();

    // A mousedown outside the dialog (on the scrim/body) closes the modal; unlike the
    // non-modal popover, a modal still returns focus to its opener.
    fireEvent.mouseDown(document.getElementById("scenario-reference-scrim")!);

    expect(document.getElementById("scenario-reference-dialog")).toBeNull();
    expect(opener).toHaveFocus();
  });

  it("traps Tab inside the dialog (wraps last focusable back to first)", () => {
    openPanel();

    const dialog = document.getElementById("scenario-reference-dialog")!;
    const closeButton = document.getElementById("scenario-reference-close")!;
    // The close button is the only interior focusable control (the entries are static
    // text), so a Tab off it wraps back to itself — focus never escapes the dialog.
    closeButton.focus();
    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(closeButton).toHaveFocus();
  });
});

describe("SCENARIO_CATEGORIES catalog", () => {
  it("holds exactly three categories totalling eight entries", () => {
    expect(SCENARIO_CATEGORIES).toHaveLength(3);
    const total = SCENARIO_CATEGORIES.reduce(
      (sum, category) => sum + category.entries.length,
      0,
    );
    expect(total).toBe(8);
  });

  it("has a trigger, outcome, and marker on every entry, with unique slugs", () => {
    const slugs = new Set<string>();
    for (const category of SCENARIO_CATEGORIES) {
      for (const entry of category.entries) {
        expect(entry.title.length).toBeGreaterThan(0);
        expect(entry.trigger.length).toBeGreaterThan(0);
        expect(entry.outcome.length).toBeGreaterThan(0);
        expect(entry.marker.length).toBeGreaterThan(0);
        expect(slugs.has(entry.slug)).toBe(false);
        slugs.add(entry.slug);
      }
    }
    expect(slugs.size).toBe(8);
  });
});
