// Tests for the presentational persona chip. It is pure (no provider/router), so
// it renders directly with a stub onSelect. Covers the active vs inactive marking,
// the label + id, the decorative (aria-hidden) icon, and that a click fires
// onSelect with the chip's role.

import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import PersonaChip from "./PersonaChip.tsx";

describe("PersonaChip", () => {
  it("renders the label, id, and a per-role accent class", () => {
    render(
      <PersonaChip
        id="chip-agent"
        role="agent"
        label="Agent"
        icon={<svg data-testid="chip-glyph" />}
        isActive={false}
        isPending={false}
        onSelect={vi.fn()}
      />,
    );

    const chip = document.getElementById("chip-agent");
    expect(chip).toBeInTheDocument();
    expect(chip).toHaveClass("persona-chip", "persona-chip-agent");
    expect(document.getElementById("chip-agent-label")).toHaveTextContent("Agent");
  });

  it("marks the active chip with aria-pressed=true and an inactive one false", () => {
    const { rerender } = render(
      <PersonaChip
        id="chip-tenant"
        role="tenant_admin"
        label="Tenant Admin"
        icon={<svg />}
        isActive={true}
        isPending={false}
        onSelect={vi.fn()}
      />,
    );
    expect(document.getElementById("chip-tenant")).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    rerender(
      <PersonaChip
        id="chip-tenant"
        role="tenant_admin"
        label="Tenant Admin"
        icon={<svg />}
        isActive={false}
        isPending={false}
        onSelect={vi.fn()}
      />,
    );
    expect(document.getElementById("chip-tenant")).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("wraps the icon aria-hidden so the text label carries the meaning", () => {
    render(
      <PersonaChip
        id="chip-readonly"
        role="read_only"
        label="Read-Only"
        icon={<svg data-testid="chip-glyph" />}
        isActive={false}
        isPending={false}
        onSelect={vi.fn()}
      />,
    );

    const iconSlot = document.getElementById("chip-readonly-icon");
    expect(iconSlot).toHaveAttribute("aria-hidden", "true");
  });

  it("fires onSelect with the chip's role when clicked", () => {
    const onSelect = vi.fn();
    render(
      <PersonaChip
        id="chip-platform"
        role="platform_admin"
        label="Platform Admin"
        icon={<svg />}
        isActive={false}
        isPending={false}
        onSelect={onSelect}
      />,
    );

    fireEvent.click(document.getElementById("chip-platform")!);
    expect(onSelect).toHaveBeenCalledWith("platform_admin");
  });

  it("is disabled while a switch is in flight (isPending)", () => {
    const onSelect = vi.fn();
    render(
      <PersonaChip
        id="chip-agent"
        role="agent"
        label="Agent"
        icon={<svg />}
        isActive={false}
        isPending={true}
        onSelect={onSelect}
      />,
    );

    const chip = document.getElementById("chip-agent")!;
    expect(chip).toBeDisabled();
    fireEvent.click(chip);
    expect(onSelect).not.toHaveBeenCalled();
  });
});
