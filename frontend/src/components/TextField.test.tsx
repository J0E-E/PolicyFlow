// Tests for the reusable TextField (Guide §5 anatomy). Uses the suite's pattern —
// @testing-library/react + fireEvent (no user-event, which is not a project
// dependency). Asserts the label/input/error structure, the controlled value +
// change, validate-on-blur, and the error-state ARIA contract.

import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import TextField from "./TextField.tsx";

describe("TextField", () => {
  it("renders a label bound to the input by htmlFor/id", () => {
    render(
      <TextField id="first-name" label="First name" value="" onChange={() => {}} />,
    );

    const input = document.getElementById("first-name");
    const label = document.getElementById("first-name-label");
    expect(input?.tagName).toBe("INPUT");
    expect(label).toHaveAttribute("for", "first-name");
  });

  it("is controlled — shows the value and reports changes", () => {
    const handleChange = vi.fn();
    render(
      <TextField
        id="first-name"
        label="First name"
        value="Margaret"
        onChange={handleChange}
      />,
    );

    const input = document.getElementById("first-name") as HTMLInputElement;
    expect(input.value).toBe("Margaret");

    fireEvent.change(input, { target: { value: "Daniel" } });
    expect(handleChange).toHaveBeenCalledWith("Daniel");
  });

  it("fires onBlur for validate-on-blur", () => {
    const handleBlur = vi.fn();
    render(
      <TextField
        id="email"
        label="Email"
        value=""
        onChange={() => {}}
        onBlur={handleBlur}
      />,
    );

    fireEvent.blur(document.getElementById("email") as HTMLInputElement);
    expect(handleBlur).toHaveBeenCalledOnce();
  });

  it("renders an error with the error ARIA contract", () => {
    render(
      <TextField
        id="email"
        label="Email"
        value=""
        onChange={() => {}}
        error="Enter your email address."
      />,
    );

    const input = document.getElementById("email") as HTMLInputElement;
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAttribute("aria-describedby", "email-error");

    const errorText = document.getElementById("email-error");
    expect(errorText).toHaveTextContent("Enter your email address.");
    expect(errorText).toHaveAttribute("role", "alert");
    expect(document.getElementById("email-field")).toHaveClass(
      "form-field-error",
    );
  });

  it("describes by the helper when there is no error, and drops it on error", () => {
    const { rerender } = render(
      <TextField
        id="zip"
        label="ZIP"
        value=""
        onChange={() => {}}
        helper="Optional"
      />,
    );
    expect(document.getElementById("zip")).toHaveAttribute(
      "aria-describedby",
      "zip-helper",
    );

    rerender(
      <TextField
        id="zip"
        label="ZIP"
        value=""
        onChange={() => {}}
        helper="Optional"
        error="Enter your ZIP code."
      />,
    );
    // The error takes the describedby slot; the helper is gone.
    expect(document.getElementById("zip")).toHaveAttribute(
      "aria-describedby",
      "zip-error",
    );
    expect(document.getElementById("zip-helper")).toBeNull();
  });

  it("marks required fields and passes through maxLength", () => {
    render(
      <TextField
        id="first-name"
        label="First name"
        value=""
        onChange={() => {}}
        isRequired
        maxLength={100}
      />,
    );

    const input = document.getElementById("first-name") as HTMLInputElement;
    expect(input).toHaveAttribute("aria-required", "true");
    expect(input).toHaveAttribute("maxlength", "100");
    expect(
      document.getElementById("first-name-required-marker"),
    ).toBeInTheDocument();
  });

  it("honors the date type for the date-of-birth control", () => {
    render(
      <TextField
        id="dob"
        label="Date of birth"
        type="date"
        value="1956-03-12"
        onChange={() => {}}
      />,
    );
    expect(document.getElementById("dob")).toHaveAttribute("type", "date");
  });
});
