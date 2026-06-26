// Tests for the pipeline board page (P2.2). jsdom has no backend, so `../api` is
// mocked: getOpportunityBoard drives the board fetch (pipeline columns +
// opportunities) and changeOpportunityStage drives the advance action. The page
// reads the session via `../session`, so useCapability is mocked per capability
// (create_edit_records). Covers: loading, the stage-grouped columns with tenant
// labels, a card in its stage's column, the skip-aware Advance label, advance +
// refetch, a terminal card, the capability-gated advance, an empty stage column,
// the empty board, a fetch error + retry, and the advance-error banner.

import { fireEvent, render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
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

// A Florida-like pipeline (Quoted relabeled, Approved disabled) so the tests can
// assert tenant labels and a skipped optional stage.
const STAGES: PipelineStage[] = [
  { key: "New", label: "New", is_optional: false },
  { key: "Qualified", label: "Qualified", is_optional: false },
  { key: "Quoted", label: "Proposal Sent", is_optional: true },
  { key: "Application Started", label: "App In Progress", is_optional: false },
  { key: "Submitted", label: "Submitted", is_optional: false },
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

function makeBoard(opportunities: OpportunityRow[]): OpportunityBoard {
  return { pipeline: { stages: STAGES }, opportunities };
}

afterEach(() => {
  vi.clearAllMocks();
});

// Render and return id-scoped query helpers (every element has a unique id).
function renderPage() {
  const utils = render(
    <MemoryRouter>
      <OpportunityPipelinePage />
    </MemoryRouter>,
  );
  const getById = (id: string): HTMLElement => {
    const element = utils.container.ownerDocument.getElementById(id);
    if (element === null) {
      throw new Error(`No element with id "${id}"`);
    }
    return element;
  };
  const queryById = (id: string): HTMLElement | null =>
    utils.container.ownerDocument.getElementById(id);
  return { ...utils, getById, queryById };
}

describe("OpportunityPipelinePage", () => {
  it("renders a column per enabled stage with tenant labels", async () => {
    useCapabilityMock.mockReturnValue(true);
    getOpportunityBoardMock.mockResolvedValue(makeBoard([makeRow({})]));

    const { getById } = renderPage();
    await waitFor(() => getById("opportunities-board"));

    expect(getById("pipeline-column-Quoted-heading").textContent).toBe(
      "Proposal Sent",
    );
    expect(
      getById("pipeline-column-Application Started-heading").textContent,
    ).toBe("App In Progress");
  });

  it("places a card in its stage's column and labels Advance with the next tenant label", async () => {
    useCapabilityMock.mockReturnValue(true);
    getOpportunityBoardMock.mockResolvedValue(
      makeBoard([makeRow({ stage: "Application Started", next_stage: "Submitted" })]),
    );

    const { getById, queryById } = renderPage();
    await waitFor(() => getById("opportunity-card-opp-1"));

    const column = getById("pipeline-column-Application Started-cards");
    expect(column.contains(getById("opportunity-card-opp-1"))).toBe(true);
    expect(getById("opportunity-advance-opp-1-label").textContent).toContain(
      "Advance to Submitted",
    );
    // The New column has no card and shows its empty marker.
    expect(queryById("pipeline-column-New-empty")).toBeTruthy();
  });

  it("uses the tenant relabel in the Advance target", async () => {
    useCapabilityMock.mockReturnValue(true);
    getOpportunityBoardMock.mockResolvedValue(
      makeBoard([makeRow({ stage: "Qualified", next_stage: "Quoted" })]),
    );

    const { getById } = renderPage();
    await waitFor(() => getById("opportunity-advance-opp-1"));
    // next_stage "Quoted" → the tenant label "Proposal Sent".
    expect(getById("opportunity-advance-opp-1-label").textContent).toContain(
      "Advance to Proposal Sent",
    );
  });

  it("advances an opportunity then refetches the board", async () => {
    useCapabilityMock.mockReturnValue(true);
    getOpportunityBoardMock
      .mockResolvedValueOnce(
        makeBoard([makeRow({ stage: "New", next_stage: "Qualified" })]),
      )
      .mockResolvedValueOnce(
        makeBoard([makeRow({ stage: "Qualified", next_stage: "Quoted" })]),
      );
    changeOpportunityStageMock.mockResolvedValue(
      makeRow({ stage: "Qualified", next_stage: "Quoted" }),
    );

    const { getById } = renderPage();
    await waitFor(() => getById("opportunity-advance-opp-1"));

    fireEvent.click(getById("opportunity-advance-opp-1"));

    await waitFor(() =>
      expect(changeOpportunityStageMock).toHaveBeenCalledWith("opp-1", "Qualified"),
    );
    await waitFor(() =>
      expect(
        getById("pipeline-column-Qualified-cards").contains(
          getById("opportunity-card-opp-1"),
        ),
      ).toBe(true),
    );
    expect(getOpportunityBoardMock).toHaveBeenCalledTimes(2);
  });

  it("shows no actions on a terminal card (no next stage, not Lost-able)", async () => {
    useCapabilityMock.mockReturnValue(true);
    getOpportunityBoardMock.mockResolvedValue(
      makeBoard([
        makeRow({ stage: "Policy Active", next_stage: null, can_mark_lost: false }),
      ]),
    );

    const { getById, queryById } = renderPage();
    await waitFor(() => getById("opportunity-card-opp-1"));

    expect(queryById("opportunity-advance-opp-1")).toBeNull();
    expect(queryById("opportunity-mark-lost-opp-1")).toBeNull();
    expect(getById("opportunity-card-opp-1-terminal")).toBeTruthy();
  });

  it("marks an opportunity Lost then refetches, showing it in the Lost lane", async () => {
    useCapabilityMock.mockReturnValue(true);
    getOpportunityBoardMock
      .mockResolvedValueOnce(
        makeBoard([makeRow({ stage: "New", next_stage: "Qualified" })]),
      )
      .mockResolvedValueOnce(
        makeBoard([
          makeRow({ stage: "Lost", next_stage: null, can_mark_lost: false }),
        ]),
      );
    changeOpportunityStageMock.mockResolvedValue(
      makeRow({ stage: "Lost", next_stage: null, can_mark_lost: false }),
    );

    const { getById } = renderPage();
    await waitFor(() => getById("opportunity-mark-lost-opp-1"));

    fireEvent.click(getById("opportunity-mark-lost-opp-1"));

    await waitFor(() =>
      expect(changeOpportunityStageMock).toHaveBeenCalledWith("opp-1", "Lost"),
    );
    // After the refetch the card sits in the Lost lane.
    await waitFor(() =>
      expect(
        getById("pipeline-column-lost-cards").contains(
          getById("opportunity-card-opp-1"),
        ),
      ).toBe(true),
    );
  });

  it("hides Advance for a user without create_edit_records", async () => {
    useCapabilityMock.mockReturnValue(false);
    getOpportunityBoardMock.mockResolvedValue(makeBoard([makeRow({})]));

    const { getById, queryById } = renderPage();
    await waitFor(() => getById("opportunity-card-opp-1"));

    expect(queryById("opportunity-advance-opp-1")).toBeNull();
  });

  it("renders an empty marker for a stage column with no cards", async () => {
    useCapabilityMock.mockReturnValue(true);
    getOpportunityBoardMock.mockResolvedValue(
      makeBoard([makeRow({ stage: "New", next_stage: "Qualified" })]),
    );

    const { getById } = renderPage();
    await waitFor(() => getById("opportunities-board"));
    expect(getById("pipeline-column-Submitted-empty")).toBeTruthy();
  });

  it("shows a non-destructive error when an advance fails, keeping the board", async () => {
    useCapabilityMock.mockReturnValue(true);
    getOpportunityBoardMock.mockResolvedValue(makeBoard([makeRow({})]));
    changeOpportunityStageMock.mockRejectedValue(new Error("boom"));

    const { getById } = renderPage();
    await waitFor(() => getById("opportunity-advance-opp-1"));

    fireEvent.click(getById("opportunity-advance-opp-1"));

    await waitFor(() => getById("opportunities-advance-error"));
    // A non-ApiError shows the generic fallback, not the raw error text.
    expect(getById("opportunities-advance-error").textContent).toContain(
      "Could not change",
    );
    expect(getById("opportunity-card-opp-1")).toBeTruthy();
  });

  it("surfaces the server's reason inline when an advance is gated (422)", async () => {
    useCapabilityMock.mockReturnValue(true);
    getOpportunityBoardMock.mockResolvedValue(
      makeBoard([makeRow({ stage: "Qualified", next_stage: "Quoted" })]),
    );
    const reason =
      "Medicare-gated product line 'medicare_advantage' cannot be quoted for a customer under 65";
    changeOpportunityStageMock.mockRejectedValue(new ApiError(422, reason));

    const { getById } = renderPage();
    await waitFor(() => getById("opportunity-advance-opp-1"));

    fireEvent.click(getById("opportunity-advance-opp-1"));

    await waitFor(() => getById("opportunities-advance-error"));
    expect(getById("opportunities-advance-error").textContent).toBe(reason);
  });

  it("renders the Medicare-gate explainer trigger", async () => {
    useCapabilityMock.mockReturnValue(true);
    getOpportunityBoardMock.mockResolvedValue(makeBoard([makeRow({})]));

    const { getById } = renderPage();
    await waitFor(() => getById("opportunities-board"));
    expect(getById("opportunities-medicare-explainer-trigger")).toBeTruthy();
  });

  it("renders the empty state when there are no opportunities", async () => {
    useCapabilityMock.mockReturnValue(true);
    getOpportunityBoardMock.mockResolvedValue(makeBoard([]));

    const { getById } = renderPage();
    await waitFor(() => getById("opportunities-empty"));
    expect(getById("opportunities-empty-message")).toBeTruthy();
  });

  it("shows an error with a working retry on a failed fetch", async () => {
    useCapabilityMock.mockReturnValue(true);
    getOpportunityBoardMock
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce(makeBoard([makeRow({})]));

    const { getById } = renderPage();
    await waitFor(() => getById("opportunities-error"));

    fireEvent.click(getById("opportunities-retry"));
    await waitFor(() => getById("opportunities-board"));
  });
});
