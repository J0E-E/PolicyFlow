// Tests for the opportunity detail page (P2.3 Epic 3). jsdom has no backend, so
// `../api` and `../session` are mocked. The page reuses the board fetch and selects
// the row by the `:id` route param. Covers: the loaded header + quote panel for a
// known id, and the not-found note for an unknown one.

import { fireEvent, render, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import OpportunityDetailPage from "./OpportunityDetailPage.tsx";
import type { OpportunityBoard, OpportunityRow } from "../api";

vi.mock("../api", () => ({
  getOpportunityBoard: vi.fn(),
  requestQuotes: vi.fn(),
  getQuoteRequest: vi.fn(),
  selectQuote: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

vi.mock("../session", () => ({
  useCapability: () => true,
}));

import { getOpportunityBoard, getQuoteRequest, requestQuotes, selectQuote } from "../api";

const getOpportunityBoardMock = vi.mocked(getOpportunityBoard);
const requestQuotesMock = vi.mocked(requestQuotes);
const getQuoteRequestMock = vi.mocked(getQuoteRequest);
const selectQuoteMock = vi.mocked(selectQuote);

function makeRow(overrides: Partial<OpportunityRow>): OpportunityRow {
  return {
    id: "opp-1",
    contact_id: "contact-1",
    household_id: "household-1",
    product_line: "final_expense",
    product_line_label: "Final Expense",
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

function makeBoard(rows: OpportunityRow[]): OpportunityBoard {
  return { pipeline: { stages: [] }, opportunities: rows };
}

function renderAt(opportunityId: string) {
  render(
    <MemoryRouter initialEntries={[`/app/opportunities/${opportunityId}`]}>
      <Routes>
        <Route path="/app/opportunities/:id" element={<OpportunityDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  getOpportunityBoardMock.mockReset();
  requestQuotesMock.mockReset();
  getQuoteRequestMock.mockReset();
  selectQuoteMock.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("OpportunityDetailPage", () => {
  it("renders the header and the quote panel for a known opportunity", async () => {
    getOpportunityBoardMock.mockResolvedValue(makeBoard([makeRow({})]));
    renderAt("opp-1");

    await waitFor(() => {
      expect(document.getElementById("opportunity-detail-title")).toBeInTheDocument();
    });
    expect(document.getElementById("opportunity-detail-title")!.textContent).toBe(
      "Mara Lopez",
    );
    expect(
      document.getElementById("opportunity-detail-product-line")!.textContent,
    ).toBe("Final Expense");
    // The Qualified opportunity offers the quote-request control.
    expect(
      document.getElementById("opportunity-detail-quotes-request"),
    ).toBeInTheDocument();
  });

  it("shows a not-found note when the id matches no opportunity", async () => {
    getOpportunityBoardMock.mockResolvedValue(makeBoard([makeRow({ id: "opp-1" })]));
    renderAt("opp-missing");

    await waitFor(() => {
      expect(
        document.getElementById("opportunity-detail-not-found"),
      ).toBeInTheDocument();
    });
  });

  it("selects a quote and renders the Draft Application summary", async () => {
    getOpportunityBoardMock.mockResolvedValue(makeBoard([makeRow({})]));
    requestQuotesMock.mockResolvedValue({
      id: "qr-1",
      opportunity_id: "opp-1",
      status: "pending",
      product_line: "final_expense",
    });
    getQuoteRequestMock.mockResolvedValue({
      quote_request: {
        id: "qr-1",
        opportunity_id: "opp-1",
        status: "completed",
        product_line: "final_expense",
      },
      quotes: [
        {
          id: "quote-1",
          carrier: "Humana",
          product_label: "Gold Plus HMO",
          coverage_amount: 7500,
          premium_monthly: 29,
          premium_annual: 348,
        },
      ],
      opportunity_stage: "Quoted",
    });
    selectQuoteMock.mockResolvedValue({
      id: "app-1",
      opportunity_id: "opp-1",
      product_line: "final_expense",
      selected_quote_id: "quote-1",
      status: "Draft",
      carrier: "Humana",
      product_label: "Gold Plus HMO",
      coverage_amount: 7500,
      premium_monthly: 29,
      premium_annual: 348,
    });
    renderAt("opp-1");

    // Request quotes → poll completes → Select control appears.
    await waitFor(() => {
      expect(
        document.getElementById("opportunity-detail-quotes-request"),
      ).toBeInTheDocument();
    });
    fireEvent.click(document.getElementById("opportunity-detail-quotes-request")!);
    await waitFor(() => {
      expect(
        document.getElementById("opportunity-detail-quotes-quote-quote-1-select"),
      ).toBeInTheDocument();
    });

    // Select the quote → the Draft Application summary renders.
    fireEvent.click(
      document.getElementById("opportunity-detail-quotes-quote-quote-1-select")!,
    );
    await waitFor(() => {
      expect(
        document.getElementById("opportunity-detail-application"),
      ).toBeInTheDocument();
    });
    expect(
      document.getElementById("opportunity-detail-application-status")!.textContent,
    ).toBe("Draft");
    expect(selectQuoteMock).toHaveBeenCalledWith("opp-1", "quote-1");
  });
});
