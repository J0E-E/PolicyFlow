// Frontend acceptance for the opportunity pipeline board (P2.2 Epic 10). Where the
// per-component tests prove each piece in isolation, this walks the whole board
// journey for one card: it renders in its stage column → Advance moves it to the
// next column → a gated Advance surfaces the server's 422 reason inline (board
// intact) → Mark Lost moves it into the Lost lane. `../api` and `../session` are
// mocked; a stateful `getOpportunityBoard` returns the board after each successful
// change, and `changeOpportunityStage` succeeds, then rejects with a 422, then
// succeeds.

import { fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import OpportunityPipelinePage from "./OpportunityPipelinePage.tsx";
import type { OpportunityBoard, OpportunityRow, PipelineStage } from "../api";

vi.mock("../api", () => ({
  getOpportunityBoard: vi.fn(),
  changeOpportunityStage: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.name = "ApiError";
      this.status = status;
    }
  },
}));

vi.mock("../session", () => ({
  useCapability: vi.fn(),
}));

import { ApiError, changeOpportunityStage, getOpportunityBoard } from "../api";
import { useCapability } from "../session";

const getOpportunityBoardMock = vi.mocked(getOpportunityBoard);
const changeOpportunityStageMock = vi.mocked(changeOpportunityStage);
const useCapabilityMock = vi.mocked(useCapability);

const STAGES: PipelineStage[] = [
  { key: "New", label: "New", is_optional: false },
  { key: "Qualified", label: "Qualified", is_optional: false },
  { key: "Quoted", label: "Proposal Sent", is_optional: true },
  { key: "Submitted", label: "Submitted", is_optional: false },
  { key: "Policy Active", label: "Policy Active", is_optional: false },
];

function row(stage: string, nextStage: string | null): OpportunityRow {
  return {
    id: "opp-1",
    contact_id: "contact-1",
    household_id: "household-1",
    product_line: "medicare_advantage",
    product_line_label: "Medicare Advantage",
    stage,
    next_stage: nextStage,
    can_mark_lost: stage !== "Lost",
    estimated_annual_premium: null,
    target_close_date: null,
    contact_first_name: "Priya",
    contact_last_name: "Nakamura",
    owner_username: "agent@sunshine.example",
    eligibility: { medicare_gated: true, age_eligible: false },
  };
}

function board(opportunity: OpportunityRow): OpportunityBoard {
  return { pipeline: { stages: STAGES }, opportunities: [opportunity] };
}

afterEach(() => {
  vi.clearAllMocks();
});

function renderPage() {
  const utils = render(<OpportunityPipelinePage />);
  const getById = (id: string): HTMLElement => {
    const element = utils.container.ownerDocument.getElementById(id);
    if (element === null) {
      throw new Error(`No element with id "${id}"`);
    }
    return element;
  };
  return { getById };
}

describe("opportunity board acceptance", () => {
  it("renders → advances → blocks at the gate → marks Lost, end to end", async () => {
    useCapabilityMock.mockReturnValue(true);
    // The board after mount (New), after the first advance (Qualified), and after
    // Mark Lost (Lost). The 422 in between does not refetch.
    getOpportunityBoardMock
      .mockResolvedValueOnce(board(row("New", "Qualified")))
      .mockResolvedValueOnce(board(row("Qualified", "Quoted")))
      .mockResolvedValueOnce(board(row("Lost", null)));
    const gateReason =
      "Medicare-gated product line 'medicare_advantage' cannot be quoted for a customer under 65";
    changeOpportunityStageMock
      .mockResolvedValueOnce(row("Qualified", "Quoted"))
      .mockRejectedValueOnce(new ApiError(422, gateReason))
      .mockResolvedValueOnce(row("Lost", null));

    const { getById } = renderPage();

    // 1. The card renders in its New column.
    await waitFor(() => getById("opportunity-card-opp-1"));
    expect(
      getById("pipeline-column-New-cards").contains(getById("opportunity-card-opp-1")),
    ).toBe(true);

    // 2. Advance → moves to the Qualified column (refetch).
    fireEvent.click(getById("opportunity-advance-opp-1"));
    await waitFor(() =>
      expect(changeOpportunityStageMock).toHaveBeenLastCalledWith("opp-1", "Qualified"),
    );
    await waitFor(() =>
      expect(
        getById("pipeline-column-Qualified-cards").contains(
          getById("opportunity-card-opp-1"),
        ),
      ).toBe(true),
    );

    // 3. Advance again (to Quoted/"Proposal Sent") → the server's 422 reason shows
    //    inline; the card stays in the Qualified column.
    expect(getById("opportunity-advance-opp-1-label").textContent).toContain(
      "Advance to Proposal Sent",
    );
    fireEvent.click(getById("opportunity-advance-opp-1"));
    await waitFor(() => getById("opportunities-advance-error"));
    expect(getById("opportunities-advance-error").textContent).toBe(gateReason);
    expect(
      getById("pipeline-column-Qualified-cards").contains(
        getById("opportunity-card-opp-1"),
      ),
    ).toBe(true);

    // 4. Mark Lost → the card moves into the Lost lane (refetch).
    fireEvent.click(getById("opportunity-mark-lost-opp-1"));
    await waitFor(() =>
      expect(changeOpportunityStageMock).toHaveBeenLastCalledWith("opp-1", "Lost"),
    );
    await waitFor(() =>
      expect(
        getById("pipeline-column-lost-cards").contains(
          getById("opportunity-card-opp-1"),
        ),
      ).toBe(true),
    );
  });
});
