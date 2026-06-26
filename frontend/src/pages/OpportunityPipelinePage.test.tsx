// Tests for the pipeline board page (P2.2 Epic 2 tracer). jsdom has no backend, so
// `../api` is mocked: listOpportunities drives the board fetch and
// changeOpportunityStage drives the advance action. The page reads the session via
// `../session`, so useCapability is mocked per capability (create_edit_records).
// Covers: loading, loaded grid, advance happy path + refetch, a terminal card with
// no advance, the capability-gated advance, the empty state, and a fetch error +
// retry.

import { fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import OpportunityPipelinePage from "./OpportunityPipelinePage.tsx";
import type { OpportunityRow } from "../api";

vi.mock("../api", () => ({
  listOpportunities: vi.fn(),
  changeOpportunityStage: vi.fn(),
}));

vi.mock("../session", () => ({
  useCapability: vi.fn(),
}));

import { changeOpportunityStage, listOpportunities } from "../api";
import { useCapability } from "../session";

const listOpportunitiesMock = vi.mocked(listOpportunities);
const changeOpportunityStageMock = vi.mocked(changeOpportunityStage);
const useCapabilityMock = vi.mocked(useCapability);

function makeRow(overrides: Partial<OpportunityRow>): OpportunityRow {
  return {
    id: "opp-1",
    contact_id: "contact-1",
    product_line: "medicare_advantage",
    stage: "New",
    next_stage: "Qualified",
    ...overrides,
  };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("OpportunityPipelinePage", () => {
  it("renders the loaded board with a stage stamp and an Advance control", async () => {
    useCapabilityMock.mockReturnValue(true);
    listOpportunitiesMock.mockResolvedValue([makeRow({})]);

    const { getByText, getById } = renderPage();

    await waitFor(() => getByText("medicare_advantage"));
    expect(getByText("New")).toBeTruthy();
    expect(
      getById("opportunity-advance-opp-1-label").textContent,
    ).toContain("Advance to Qualified");
  });

  it("advances an opportunity then refetches the board", async () => {
    useCapabilityMock.mockReturnValue(true);
    listOpportunitiesMock
      .mockResolvedValueOnce([makeRow({ stage: "New", next_stage: "Qualified" })])
      .mockResolvedValueOnce([
        makeRow({ stage: "Qualified", next_stage: "Quoted" }),
      ]);
    changeOpportunityStageMock.mockResolvedValue(
      makeRow({ stage: "Qualified", next_stage: "Quoted" }),
    );

    const { getById, getByText } = renderPage();
    await waitFor(() => getById("opportunity-advance-opp-1"));

    fireEvent.click(getById("opportunity-advance-opp-1"));

    await waitFor(() =>
      expect(changeOpportunityStageMock).toHaveBeenCalledWith("opp-1", "Qualified"),
    );
    await waitFor(() => getByText("Qualified"));
    expect(listOpportunitiesMock).toHaveBeenCalledTimes(2);
  });

  it("shows no Advance control on a terminal card (no next stage)", async () => {
    useCapabilityMock.mockReturnValue(true);
    listOpportunitiesMock.mockResolvedValue([
      makeRow({ stage: "Policy Active", next_stage: null }),
    ]);

    const { getById, queryById } = renderPage();
    await waitFor(() => getById("opportunity-card-opp-1"));

    expect(queryById("opportunity-advance-opp-1")).toBeNull();
    expect(getById("opportunity-terminal-opp-1")).toBeTruthy();
  });

  it("hides Advance for a user without create_edit_records", async () => {
    useCapabilityMock.mockReturnValue(false);
    listOpportunitiesMock.mockResolvedValue([makeRow({})]);

    const { getById, queryById } = renderPage();
    await waitFor(() => getById("opportunity-card-opp-1"));

    expect(queryById("opportunity-advance-opp-1")).toBeNull();
  });

  it("shows a non-destructive error when an advance fails, keeping the board", async () => {
    useCapabilityMock.mockReturnValue(true);
    listOpportunitiesMock.mockResolvedValue([makeRow({})]);
    changeOpportunityStageMock.mockRejectedValue(new Error("boom"));

    const { getById, getByText } = renderPage();
    await waitFor(() => getById("opportunity-advance-opp-1"));

    fireEvent.click(getById("opportunity-advance-opp-1"));

    await waitFor(() => getById("opportunities-advance-error"));
    // The board stays intact — the card (and its Advance) are still present.
    expect(getByText("medicare_advantage")).toBeTruthy();
    expect(getById("opportunity-advance-opp-1")).toBeTruthy();
  });

  it("renders the empty state when there are no opportunities", async () => {
    useCapabilityMock.mockReturnValue(true);
    listOpportunitiesMock.mockResolvedValue([]);

    const { getById } = renderPage();
    await waitFor(() => getById("opportunities-empty"));
    expect(getById("opportunities-empty-message")).toBeTruthy();
  });

  it("shows an error with a working retry on a failed fetch", async () => {
    useCapabilityMock.mockReturnValue(true);
    listOpportunitiesMock
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce([makeRow({})]);

    const { getById, getByText } = renderPage();
    await waitFor(() => getById("opportunities-error"));

    fireEvent.click(getById("opportunities-retry"));
    await waitFor(() => getByText("medicare_advantage"));
  });
});

// Render the page and return id-scoped query helpers over its container (the page
// gives every element a unique id, so id lookups are the natural assertion seam).
function renderPage() {
  const utils = render(<OpportunityPipelinePage />);
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
