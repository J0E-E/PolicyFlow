// Tests for the opportunity value-fields leaf component: the value when present,
// an em-dash when null (D7 — P2.2 leaves both fields null at conversion).

import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import OpportunityValueFields from "./OpportunityValueFields.tsx";

function renderFields(premium: string | null, closeDate: string | null) {
  const utils = render(
    <OpportunityValueFields id="vf" premium={premium} closeDate={closeDate} />,
  );
  const getById = (id: string): HTMLElement => {
    const element = utils.container.ownerDocument.getElementById(id);
    if (element === null) {
      throw new Error(`No element with id "${id}"`);
    }
    return element;
  };
  return { getById };
}

describe("OpportunityValueFields", () => {
  it("renders the premium and close date when present", () => {
    const { getById } = renderFields("1200.00", "2026-09-01");
    expect(getById("vf-premium-value").textContent).toBe("$1200.00");
    expect(getById("vf-close-date-value").textContent).toBe("2026-09-01");
  });

  it("renders an em-dash for each null field", () => {
    const { getById } = renderFields(null, null);
    expect(getById("vf-premium-value").textContent).toBe("—");
    expect(getById("vf-close-date-value").textContent).toBe("—");
  });
});
