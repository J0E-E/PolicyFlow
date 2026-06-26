// Tests for the OpportunityCard component: the enriched fields (contact name,
// product-line label, value fields em-dash, owner, Medicare eligibility marker)
// and the Advance / Mark Lost actions (shown per next_stage / can_mark_lost /
// capability, calling the handlers).

import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import OpportunityCard from "./OpportunityCard.tsx";
import type { OpportunityRow } from "../api";

function makeRow(overrides: Partial<OpportunityRow>): OpportunityRow {
  return {
    id: "opp-1",
    contact_id: "contact-1",
    household_id: "household-1",
    product_line: "medicare_advantage",
    product_line_label: "Medicare Advantage",
    stage: "Qualified",
    next_stage: "Quoted",
    can_mark_lost: true,
    estimated_annual_premium: null,
    target_close_date: null,
    contact_first_name: "Mara",
    contact_last_name: "Lopez",
    owner_username: "agent@sunshine.example",
    eligibility: { medicare_gated: false, age_eligible: false },
    ...overrides,
  };
}

function renderCard(opportunity: OpportunityRow, overrides = {}) {
  const props = {
    canAdvance: true,
    isChanging: false,
    onAdvance: vi.fn(),
    onMarkLost: vi.fn(),
    labelForStage: (key: string) => (key === "Quoted" ? "Proposal Sent" : key),
    ...overrides,
  };
  const utils = render(<OpportunityCard opportunity={opportunity} {...props} />);
  const getById = (id: string): HTMLElement => {
    const element = utils.container.ownerDocument.getElementById(id);
    if (element === null) {
      throw new Error(`No element with id "${id}"`);
    }
    return element;
  };
  const queryById = (id: string) =>
    utils.container.ownerDocument.getElementById(id);
  return { ...props, getById, queryById };
}

describe("OpportunityCard", () => {
  it("renders the contact name, product-line label, value fields, and owner", () => {
    const { getById } = renderCard(makeRow({}));
    expect(getById("opportunity-card-opp-1-title").textContent).toBe("Mara Lopez");
    expect(getById("opportunity-card-opp-1-product-line").textContent).toBe(
      "Medicare Advantage",
    );
    expect(getById("opportunity-card-opp-1-values-premium-value").textContent).toBe(
      "—",
    );
    expect(getById("opportunity-card-opp-1-owner").textContent).toContain(
      "agent@sunshine.example",
    );
  });

  it("labels Advance with the tenant stage label and calls onAdvance", () => {
    const { getById, onAdvance } = renderCard(makeRow({}));
    expect(getById("opportunity-advance-opp-1-label").textContent).toContain(
      "Advance to Proposal Sent",
    );
    fireEvent.click(getById("opportunity-advance-opp-1"));
    expect(onAdvance).toHaveBeenCalledTimes(1);
  });

  it("calls onMarkLost from the Mark Lost button", () => {
    const { getById, onMarkLost } = renderCard(makeRow({}));
    fireEvent.click(getById("opportunity-mark-lost-opp-1"));
    expect(onMarkLost).toHaveBeenCalledTimes(1);
  });

  it("hides the actions for a user without create_edit_records", () => {
    const { queryById } = renderCard(makeRow({}), { canAdvance: false });
    expect(queryById("opportunity-advance-opp-1")).toBeNull();
    expect(queryById("opportunity-mark-lost-opp-1")).toBeNull();
  });

  it("shows the terminal note when the card has no actions", () => {
    const { getById, queryById } = renderCard(
      makeRow({ stage: "Policy Active", next_stage: null, can_mark_lost: false }),
    );
    expect(getById("opportunity-card-opp-1-terminal")).toBeTruthy();
    expect(queryById("opportunity-advance-opp-1")).toBeNull();
  });

  it("shows a warning eligibility marker for a gated under-65 opportunity", () => {
    const { getById } = renderCard(
      makeRow({ eligibility: { medicare_gated: true, age_eligible: false } }),
    );
    expect(getById("opportunity-card-opp-1-eligibility-label").textContent).toBe(
      "Medicare · 65+ required",
    );
  });

  it("omits the eligibility marker for a non-gated opportunity", () => {
    const { queryById } = renderCard(
      makeRow({ eligibility: { medicare_gated: false, age_eligible: false } }),
    );
    expect(queryById("opportunity-card-opp-1-eligibility")).toBeNull();
  });
});
