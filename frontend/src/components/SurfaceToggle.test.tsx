// Tests for the SurfaceToggle (Epic 24) — the persistent demo control that flips
// between the Shopper storefront and the Agent workspace. It composes the Epic 7
// ButtonLink (a react-router <Link>, so the suite wraps in a MemoryRouter) and the
// Epic 19 ExplainerPopover; these assert the link target + worded accessible name
// (the decorative arrow is NOT part of the name) and that the explainer marks the
// toggle a demo convenience that changes surface, not identity / not a role. Uses
// the suite's pattern — @testing-library/react + fireEvent (no user-event, which is
// not a project dependency).

import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import SurfaceToggle from "./SurfaceToggle.tsx";

function renderToggle(
  props: { to: string; label: string; direction: "forward" | "back" } = {
    to: "/site/sunshine-senior-benefits",
    label: "View the public site",
    direction: "forward",
  },
) {
  return render(
    <MemoryRouter>
      <SurfaceToggle id="surface-toggle-test" {...props} />
    </MemoryRouter>,
  );
}

describe("SurfaceToggle", () => {
  it("renders a link to the given route with the worded label", () => {
    renderToggle({
      to: "/site/sunshine-senior-benefits",
      label: "View the public site",
      direction: "forward",
    });

    const link = document.getElementById("surface-toggle-test-link");
    expect(link?.tagName).toBe("A");
    expect(link).toHaveAttribute("href", "/site/sunshine-senior-benefits");
  });

  it("excludes the decorative arrow from the link's accessible name", () => {
    renderToggle({
      to: "/site/sunshine-senior-benefits",
      label: "View the public site",
      direction: "forward",
    });

    // The accessible name is exactly the words — the arrow is aria-hidden, so it is
    // not announced; the link is found by the worded name alone.
    const link = screen.getByRole("link", { name: "View the public site" });
    expect(link).toBe(document.getElementById("surface-toggle-test-link"));

    // The arrow glyph is present but decorative.
    const arrow = document.getElementById("surface-toggle-test-arrow");
    expect(arrow).toHaveAttribute("aria-hidden", "true");
    expect(arrow).toHaveTextContent("→");
  });

  it("places a leading arrow for the back direction", () => {
    renderToggle({
      to: "/app",
      label: "Back to the agent workspace",
      direction: "back",
    });

    const link = screen.getByRole("link", {
      name: "Back to the agent workspace",
    });
    expect(link).toHaveAttribute("href", "/app");

    const arrow = document.getElementById("surface-toggle-test-arrow");
    expect(arrow).toHaveTextContent("←");
    // Leading: the arrow is the first child inside the link's label, the words
    // follow it (ButtonLink wraps its children in the `${id}-label` span).
    const label = document.getElementById("surface-toggle-test-link-label");
    expect(label?.firstElementChild).toBe(arrow);
  });

  it("opens an explainer marking the toggle a demo convenience (surface, not a role)", () => {
    renderToggle();

    const trigger = document.getElementById(
      "surface-toggle-test-explainer-trigger",
    );
    expect(trigger).toBeInTheDocument();

    fireEvent.click(trigger!);

    const realVsSimulated = document.getElementById(
      "surface-toggle-test-explainer-body-realVsSimulated",
    );
    expect(realVsSimulated).toHaveTextContent("demo convenience");
    // It is explicit that flipping surface never changes WHO you are — not a role.
    expect(realVsSimulated).toHaveTextContent("changes surface, not identity");
    expect(realVsSimulated).toHaveTextContent("never a role");
  });
});
