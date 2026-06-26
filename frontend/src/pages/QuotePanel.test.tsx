// Tests for the carrier-quote round-trip panel (P2.3 Epic 3). jsdom has no backend,
// so `../api` is mocked: requestQuotes opens the round-trip and getQuoteRequest is
// polled. Covers the gating of the Request control (stage + capability), the
// request → pending → completed flow rendering the options, the poll re-arm while
// pending, and the opportunity-stage callback on completion.

import { act, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import QuotePanel from "./QuotePanel.tsx";
import type { QuoteOption, QuoteRequestPoll } from "../api";

vi.mock("../api", () => ({
  requestQuotes: vi.fn(),
  getQuoteRequest: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

import { getQuoteRequest, requestQuotes } from "../api";

const requestQuotesMock = vi.mocked(requestQuotes);
const getQuoteRequestMock = vi.mocked(getQuoteRequest);

function makeQuote(overrides: Partial<QuoteOption>): QuoteOption {
  return {
    id: "quote-1",
    carrier: "Humana",
    product_label: "Gold Plus HMO",
    coverage_amount: 7500,
    premium_monthly: 29,
    premium_annual: 348,
    ...overrides,
  };
}

function makePoll(overrides: Partial<QuoteRequestPoll>): QuoteRequestPoll {
  return {
    quote_request: {
      id: "qr-1",
      opportunity_id: "opp-1",
      status: "completed",
      product_line: "final_expense",
    },
    quotes: [makeQuote({})],
    opportunity_stage: "Quoted",
    ...overrides,
  };
}

function renderPanel(overrides = {}) {
  const props = {
    id: "quotes",
    opportunityId: "opp-1",
    stage: "Qualified",
    canRequest: true,
    onOpportunityStageChange: vi.fn(),
    ...overrides,
  };
  render(<QuotePanel {...props} />);
  return props;
}

beforeEach(() => {
  requestQuotesMock.mockReset();
  getQuoteRequestMock.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("QuotePanel", () => {
  it("offers the Request control when the opportunity is Qualified and the caller may act", () => {
    renderPanel();
    expect(document.getElementById("quotes-request")).toBeInTheDocument();
  });

  it("hides the Request control and explains when the opportunity is not Qualified", () => {
    renderPanel({ stage: "New" });
    expect(document.getElementById("quotes-request")).not.toBeInTheDocument();
    expect(document.getElementById("quotes-not-quotable")).toBeInTheDocument();
  });

  it("hides the Request control for a read-only caller", () => {
    renderPanel({ canRequest: false });
    expect(document.getElementById("quotes-request")).not.toBeInTheDocument();
    expect(document.getElementById("quotes-read-only")).toBeInTheDocument();
  });

  it("requests quotes, polls to completion, renders the options, and surfaces the stage move", async () => {
    requestQuotesMock.mockResolvedValue({
      id: "qr-1",
      opportunity_id: "opp-1",
      status: "pending",
      product_line: "final_expense",
    });
    getQuoteRequestMock.mockResolvedValue(makePoll({}));
    const props = renderPanel();

    fireEvent.click(document.getElementById("quotes-request")!);

    await waitFor(() => {
      expect(document.getElementById("quotes-list")).toBeInTheDocument();
    });
    // The option renders its carrier, label, and monthly + annual premium.
    expect(document.getElementById("quotes-quote-quote-1-carrier")!.textContent).toBe(
      "Humana",
    );
    expect(
      document.getElementById("quotes-quote-quote-1-premium")!.textContent,
    ).toContain("$29/mo");
    // The completion surfaced the opportunity's Quoted move to the page.
    expect(props.onOpportunityStageChange).toHaveBeenCalledWith("Quoted");
  });

  it("keeps polling while the request is still pending, then renders on completion", async () => {
    vi.useFakeTimers();
    requestQuotesMock.mockResolvedValue({
      id: "qr-1",
      opportunity_id: "opp-1",
      status: "pending",
      product_line: "final_expense",
    });
    // First poll still pending; the second (after the interval) completes.
    getQuoteRequestMock
      .mockResolvedValueOnce(
        makePoll({
          quote_request: {
            id: "qr-1",
            opportunity_id: "opp-1",
            status: "pending",
            product_line: "final_expense",
          },
          quotes: [],
          opportunity_stage: "Qualified",
        }),
      )
      .mockResolvedValueOnce(makePoll({}));
    renderPanel();

    fireEvent.click(document.getElementById("quotes-request")!);
    // Flush the request promise + the first (pending) poll (advanceTimersByTimeAsync
    // drains the chained microtasks as it goes — waitFor can't run under fake timers).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(document.getElementById("quotes-pending")).toBeInTheDocument();
    expect(getQuoteRequestMock).toHaveBeenCalledTimes(1);

    // Advance past the poll interval; the second poll completes and renders.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    expect(document.getElementById("quotes-list")).toBeInTheDocument();
    expect(getQuoteRequestMock).toHaveBeenCalledTimes(2);
  });
});
