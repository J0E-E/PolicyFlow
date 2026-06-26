// Tests for PipelineBoard (and the PipelineColumn it renders): a column per
// enabled stage with the tenant label, cards grouped into their stage's column,
// the Lost lane shown only when there are Lost cards, and an empty-column marker.

import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import PipelineBoard from "./PipelineBoard.tsx";
import type { OpportunityBoard, OpportunityRow, PipelineStage } from "../api";

const STAGES: PipelineStage[] = [
  { key: "New", label: "New", is_optional: false },
  { key: "Qualified", label: "Qualified", is_optional: false },
  { key: "Quoted", label: "Proposal Sent", is_optional: true },
  { key: "Policy Active", label: "Policy Active", is_optional: false },
];

function makeRow(overrides: Partial<OpportunityRow>): OpportunityRow {
  return {
    id: "opp-1",
    contact_id: "contact-1",
    household_id: "household-1",
    product_line: "term_life",
    product_line_label: "Term Life Insurance",
    stage: "New",
    next_stage: "Qualified",
    can_advance: true,
    can_mark_lost: true,
    estimated_annual_premium: null,
    target_close_date: null,
    contact_first_name: "Pat",
    contact_last_name: "Quincy",
    owner_username: "agent@florida.example",
    eligibility: { medicare_gated: false, age_eligible: false },
    ...overrides,
  };
}

function renderBoard(opportunities: OpportunityRow[]) {
  const board: OpportunityBoard = {
    pipeline: { stages: STAGES },
    opportunities,
  };
  const utils = render(
    <MemoryRouter>
      <PipelineBoard
        board={board}
        canAdvance={true}
        changingId={null}
        onAdvance={vi.fn()}
        onMarkLost={vi.fn()}
      />
    </MemoryRouter>,
  );
  const getById = (id: string): HTMLElement => {
    const element = utils.container.ownerDocument.getElementById(id);
    if (element === null) {
      throw new Error(`No element with id "${id}"`);
    }
    return element;
  };
  const queryById = (id: string) =>
    utils.container.ownerDocument.getElementById(id);
  return { getById, queryById };
}

describe("PipelineBoard", () => {
  it("renders one column per enabled stage with its tenant label", () => {
    const { getById } = renderBoard([makeRow({})]);
    expect(getById("pipeline-column-Quoted-heading").textContent).toBe(
      "Proposal Sent",
    );
    expect(getById("pipeline-column-Policy Active-heading").textContent).toBe(
      "Policy Active",
    );
  });

  it("groups a card into its stage's column", () => {
    const { getById } = renderBoard([
      makeRow({ id: "opp-2", stage: "Qualified" }),
    ]);
    expect(
      getById("pipeline-column-Qualified-cards").contains(
        getById("opportunity-card-opp-2"),
      ),
    ).toBe(true);
  });

  it("shows an empty marker for a stage with no cards", () => {
    const { getById } = renderBoard([makeRow({ stage: "New" })]);
    expect(getById("pipeline-column-Qualified-empty")).toBeTruthy();
  });

  it("renders the Lost lane only when there are Lost opportunities", () => {
    const { queryById } = renderBoard([makeRow({ stage: "New" })]);
    expect(queryById("pipeline-column-lost")).toBeNull();

    const withLost = renderBoard([
      makeRow({ id: "opp-3", stage: "Lost", next_stage: null, can_mark_lost: false }),
    ]);
    expect(
      withLost
        .getById("pipeline-column-lost-cards")
        .contains(withLost.getById("opportunity-card-opp-3")),
    ).toBe(true);
  });
});
