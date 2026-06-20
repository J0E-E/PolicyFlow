// Tests for the reusable CheckboxGroup (Guide §5 grouped control). Asserts the
// fieldset/legend grouping, controlled selection, toggle (add + remove, order
// preserved), and the error state.

import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import CheckboxGroup from "./CheckboxGroup.tsx";

const options = [
  { value: "medicare_advantage", label: "Medicare Advantage" },
  { value: "final_expense", label: "Final Expense" },
  { value: "dental_vision_hearing", label: "Dental, Vision & Hearing" },
];

describe("CheckboxGroup", () => {
  it("renders as a fieldset with a legend", () => {
    render(
      <CheckboxGroup
        id="lines"
        label="Coverage interests"
        options={options}
        selectedValues={[]}
        onChange={() => {}}
      />,
    );

    const group = document.getElementById("lines");
    expect(group?.tagName).toBe("FIELDSET");
    expect(document.getElementById("lines-legend")).toHaveTextContent(
      "Coverage interests",
    );
  });

  it("reflects the selected values as checked boxes", () => {
    render(
      <CheckboxGroup
        id="lines"
        label="Coverage interests"
        options={options}
        selectedValues={["final_expense"]}
        onChange={() => {}}
      />,
    );

    expect(
      document.getElementById("lines-option-final_expense"),
    ).toBeChecked();
    expect(
      document.getElementById("lines-option-medicare_advantage"),
    ).not.toBeChecked();
  });

  it("adds a value when an unchecked box is clicked, preserving option order", () => {
    const handleChange = vi.fn();
    render(
      <CheckboxGroup
        id="lines"
        label="Coverage interests"
        options={options}
        selectedValues={["dental_vision_hearing"]}
        onChange={handleChange}
      />,
    );

    fireEvent.click(
      document.getElementById("lines-option-medicare_advantage") as HTMLInputElement,
    );
    // Order follows the options array, not click order.
    expect(handleChange).toHaveBeenCalledWith([
      "medicare_advantage",
      "dental_vision_hearing",
    ]);
  });

  it("removes a value when a checked box is clicked", () => {
    const handleChange = vi.fn();
    render(
      <CheckboxGroup
        id="lines"
        label="Coverage interests"
        options={options}
        selectedValues={["medicare_advantage", "final_expense"]}
        onChange={handleChange}
      />,
    );

    fireEvent.click(
      document.getElementById("lines-option-medicare_advantage") as HTMLInputElement,
    );
    expect(handleChange).toHaveBeenCalledWith(["final_expense"]);
  });

  it("renders the error and wires aria-invalid on the fieldset", () => {
    render(
      <CheckboxGroup
        id="lines"
        label="Coverage interests"
        options={options}
        selectedValues={[]}
        onChange={() => {}}
        error="Choose at least one coverage interest."
      />,
    );

    expect(document.getElementById("lines")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(document.getElementById("lines-error")).toHaveTextContent(
      "Choose at least one coverage interest.",
    );
  });
});
