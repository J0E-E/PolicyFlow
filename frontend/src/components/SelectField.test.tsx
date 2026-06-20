// Tests for the reusable SelectField (Guide §5). Asserts the placeholder option,
// the rendered options, controlled value + change, and the error ARIA contract.

import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import SelectField from "./SelectField.tsx";

const options = [
  { value: "email", label: "Email" },
  { value: "phone", label: "Phone call" },
  { value: "text", label: "Text message" },
];

describe("SelectField", () => {
  it("renders a value-less placeholder option first", () => {
    render(
      <SelectField
        id="contact"
        label="Preferred contact"
        value=""
        onChange={() => {}}
        options={options}
        placeholder="No preference"
      />,
    );

    const placeholder = document.getElementById(
      "contact-option-placeholder",
    ) as HTMLOptionElement;
    expect(placeholder.value).toBe("");
    expect(placeholder).toHaveTextContent("No preference");
  });

  it("renders one option per choice and reports a selection", () => {
    const handleChange = vi.fn();
    render(
      <SelectField
        id="contact"
        label="Preferred contact"
        value=""
        onChange={handleChange}
        options={options}
        placeholder="No preference"
      />,
    );

    expect(document.getElementById("contact-option-email")).toBeInTheDocument();
    expect(document.getElementById("contact-option-text")).toBeInTheDocument();

    fireEvent.change(document.getElementById("contact") as HTMLSelectElement, {
      target: { value: "phone" },
    });
    expect(handleChange).toHaveBeenCalledWith("phone");
  });

  it("renders the error with the error ARIA contract", () => {
    render(
      <SelectField
        id="contact"
        label="Preferred contact"
        value=""
        onChange={() => {}}
        options={options}
        placeholder="No preference"
        error="Pick a contact method."
      />,
    );

    const select = document.getElementById("contact") as HTMLSelectElement;
    expect(select).toHaveAttribute("aria-invalid", "true");
    expect(select).toHaveAttribute("aria-describedby", "contact-error");
    expect(document.getElementById("contact-error")).toHaveTextContent(
      "Pick a contact method.",
    );
  });
});
