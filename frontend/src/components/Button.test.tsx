// Tests for the Button primitive and its ButtonLink sibling. Uses the suite's
// existing pattern — @testing-library/react + fireEvent (no user-event, which is
// not a project dependency). ButtonLink renders a react-router <Link>, so it is
// wrapped in a MemoryRouter.

import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import Button from "./Button.tsx";
import ButtonLink from "./ButtonLink.tsx";
import type { ButtonVariant } from "./buttonVariants.ts";

describe("Button", () => {
  const variants: ButtonVariant[] = ["filled", "tonal", "outlined", "text"];

  it.each(variants)("renders the %s variant with its variant class", (variant) => {
    render(
      <Button id="action-button" variant={variant}>
        Do the thing
      </Button>,
    );

    const button = screen.getByRole("button", { name: "Do the thing" });
    expect(button).toHaveClass("button", `button-${variant}`);
  });

  it("defaults to type='button' so it never submits a surrounding form", () => {
    render(
      <Button id="action-button" variant="filled">
        Do the thing
      </Button>,
    );

    expect(screen.getByRole("button")).toHaveAttribute("type", "button");
  });

  it("renders the button id and the derived label-span id", () => {
    render(
      <Button id="action-button" variant="filled">
        Do the thing
      </Button>,
    );

    expect(document.getElementById("action-button")).toBeInTheDocument();
    const label = document.getElementById("action-button-label");
    expect(label).toBeInTheDocument();
    expect(label).toHaveTextContent("Do the thing");
  });

  it("fires onClick when clicked", () => {
    const handleClick = vi.fn();
    render(
      <Button id="action-button" variant="filled" onClick={handleClick}>
        Do the thing
      </Button>,
    );

    fireEvent.click(screen.getByRole("button"));
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it("does not fire onClick while disabled", () => {
    const handleClick = vi.fn();
    render(
      <Button id="action-button" variant="filled" disabled onClick={handleClick}>
        Do the thing
      </Button>,
    );

    const button = screen.getByRole("button");
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(handleClick).not.toHaveBeenCalled();
  });

  it("shows the spinner, marks itself busy, and blocks clicks while pending", () => {
    const handleClick = vi.fn();
    render(
      <Button
        id="action-button"
        variant="filled"
        isPending
        onClick={handleClick}
      >
        Do the thing
      </Button>,
    );

    const button = screen.getByRole("button");
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(document.getElementById("action-button-spinner")).toBeInTheDocument();

    fireEvent.click(button);
    expect(handleClick).not.toHaveBeenCalled();
  });

  it("renders no spinner when not pending", () => {
    render(
      <Button id="action-button" variant="filled">
        Do the thing
      </Button>,
    );

    expect(document.getElementById("action-button-spinner")).toBeNull();
    expect(screen.getByRole("button")).toHaveAttribute("aria-busy", "false");
  });
});

describe("ButtonLink", () => {
  it("renders an <a> pointing at `to` with the variant class", () => {
    render(
      <MemoryRouter>
        <ButtonLink id="nav-button" variant="tonal" to="/select-tenant">
          Select a tenant
        </ButtonLink>
      </MemoryRouter>,
    );

    const link = screen.getByRole("link", { name: "Select a tenant" });
    expect(link).toHaveAttribute("href", "/select-tenant");
    expect(link).toHaveClass("button", "button-tonal");
    expect(link).toHaveAttribute("id", "nav-button");
    expect(document.getElementById("nav-button-label")).toHaveTextContent(
      "Select a tenant",
    );
  });
});
