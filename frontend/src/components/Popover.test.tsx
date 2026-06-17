// Tests for the Popover / margin-note primitive. Uses the suite's pattern —
// @testing-library/react + fireEvent (no user-event, which is not a project
// dependency). Popover is interactive and correctness-critical (the keyboard /
// focus contract, Guide §7), so these assert the open/close state machine, the
// ARIA wiring, focus movement, and the hand-rolled focus trap. jsdom does not
// natively move focus on Tab, so the trap tests fire a Tab keydown and assert
// our handler's explicit .focus() landed on the wrapped edge element.

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Popover from "./Popover.tsx";

function renderPopover(children = <p id="margin-note-body">Margin note text.</p>) {
  return render(
    <Popover
      id="explainer-landing"
      trigger="i"
      triggerLabel="Explain this surface"
      surfaceLabel="How this surface is built"
    >
      {children}
    </Popover>,
  );
}

describe("Popover", () => {
  it("renders the root and derived trigger id, closed by default", () => {
    renderPopover();

    expect(document.getElementById("explainer-landing")).toBeInTheDocument();
    const trigger = document.getElementById("explainer-landing-trigger");
    expect(trigger).toBeInTheDocument();
    // No surface until opened.
    expect(document.getElementById("explainer-landing-surface")).toBeNull();
  });

  it("wires the closed trigger's ARIA (haspopup dialog, not expanded)", () => {
    renderPopover();

    const trigger = document.getElementById("explainer-landing-trigger");
    expect(trigger).toHaveAttribute("type", "button");
    expect(trigger).toHaveAttribute("aria-haspopup", "dialog");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).not.toHaveAttribute("aria-controls");
    expect(trigger).toHaveAttribute("aria-label", "Explain this surface");
  });

  it("opens on trigger click: surface is a labelled dialog, expanded, focused", () => {
    renderPopover();
    const trigger = document.getElementById("explainer-landing-trigger")!;

    fireEvent.click(trigger);

    const surface = document.getElementById("explainer-landing-surface");
    expect(surface).toBeInTheDocument();
    expect(surface).toHaveAttribute("role", "dialog");
    expect(surface).toHaveAttribute("aria-label", "How this surface is built");
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(trigger).toHaveAttribute("aria-controls", "explainer-landing-surface");
    // Focus moved into the surface so its label is announced.
    expect(surface).toHaveFocus();
  });

  it("closes again on a second trigger click", () => {
    renderPopover();
    const trigger = document.getElementById("explainer-landing-trigger")!;

    fireEvent.click(trigger);
    expect(document.getElementById("explainer-landing-surface")).toBeInTheDocument();

    fireEvent.click(trigger);
    expect(document.getElementById("explainer-landing-surface")).toBeNull();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("closes on Esc and restores focus to the trigger", () => {
    renderPopover();
    const trigger = document.getElementById("explainer-landing-trigger")!;

    fireEvent.click(trigger);
    const surface = document.getElementById("explainer-landing-surface")!;

    fireEvent.keyDown(surface, { key: "Escape" });

    expect(document.getElementById("explainer-landing-surface")).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("closes on an outside mousedown (focus follows the click, not the trigger)", () => {
    renderPopover();
    const trigger = document.getElementById("explainer-landing-trigger")!;

    fireEvent.click(trigger);
    expect(document.getElementById("explainer-landing-surface")).toBeInTheDocument();

    fireEvent.mouseDown(document.body);

    expect(document.getElementById("explainer-landing-surface")).toBeNull();
    // Outside-click does not yank focus back to the trigger.
    expect(trigger).not.toHaveFocus();
  });

  it("stays open on a mousedown inside the surface", () => {
    renderPopover(
      <button id="margin-note-action" type="button">
        Acknowledge
      </button>,
    );
    const trigger = document.getElementById("explainer-landing-trigger")!;

    fireEvent.click(trigger);
    const action = document.getElementById("margin-note-action")!;

    fireEvent.mouseDown(action);

    expect(document.getElementById("explainer-landing-surface")).toBeInTheDocument();
  });

  it("traps Tab: from the last focusable wraps back to the first", () => {
    renderPopover(
      <>
        <button id="margin-note-first" type="button">
          First
        </button>
        <button id="margin-note-last" type="button">
          Last
        </button>
      </>,
    );
    const trigger = document.getElementById("explainer-landing-trigger")!;
    fireEvent.click(trigger);

    const surface = document.getElementById("explainer-landing-surface")!;
    const firstButton = document.getElementById("margin-note-first")!;
    const lastButton = document.getElementById("margin-note-last")!;

    // Simulate the focus being on the last element, then Tab forward.
    lastButton.focus();
    fireEvent.keyDown(surface, { key: "Tab" });

    expect(firstButton).toHaveFocus();
  });

  it("traps Shift+Tab: from the first focusable wraps to the last", () => {
    renderPopover(
      <>
        <button id="margin-note-first" type="button">
          First
        </button>
        <button id="margin-note-last" type="button">
          Last
        </button>
      </>,
    );
    const trigger = document.getElementById("explainer-landing-trigger")!;
    fireEvent.click(trigger);

    const surface = document.getElementById("explainer-landing-surface")!;
    const firstButton = document.getElementById("margin-note-first")!;
    const lastButton = document.getElementById("margin-note-last")!;

    firstButton.focus();
    fireEvent.keyDown(surface, { key: "Tab", shiftKey: true });

    expect(lastButton).toHaveFocus();
  });

  it("keeps focus on the container when the surface has no focusable controls", () => {
    renderPopover();
    const trigger = document.getElementById("explainer-landing-trigger")!;
    fireEvent.click(trigger);

    const surface = document.getElementById("explainer-landing-surface")!;
    expect(surface).toHaveFocus();

    fireEvent.keyDown(surface, { key: "Tab" });
    expect(surface).toHaveFocus();
  });

  it("renders the children inside the open surface", () => {
    renderPopover();
    const trigger = document.getElementById("explainer-landing-trigger")!;

    fireEvent.click(trigger);

    expect(screen.getByText("Margin note text.")).toBeInTheDocument();
  });
});
