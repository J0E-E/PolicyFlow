// Tests for the "Converted to" panel (P2.1 Epic 7). jsdom has no backend, so `../api`
// is mocked: getConversion drives the summary. The panel does its own fetch on mount
// and renders the contact name, household name, and opportunities by product-line
// label + stage; a failed fetch shows a calm error line.

import { render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import LeadConvertedPanel from "./LeadConvertedPanel.tsx";
import type { ConversionSummary, ProductLine } from "../api";

vi.mock("../api", () => ({
  getConversion: vi.fn(),
}));

import { getConversion } from "../api";

const getConversionMock = vi.mocked(getConversion);

const productLines: ProductLine[] = [
  { key: "medicare_advantage", label: "Medicare Advantage" },
  { key: "final_expense", label: "Final Expense" },
];

const summary: ConversionSummary = {
  contact: { id: "contact-1", first_name: "Maria", last_name: "Lopez" },
  household: { id: "household-1", name: "Lopez Household" },
  opportunities: [
    { id: "opp-1", product_line: "medicare_advantage", stage: "New" },
    { id: "opp-2", product_line: "final_expense", stage: "New" },
  ],
};

afterEach(() => {
  vi.clearAllMocks();
});

describe("LeadConvertedPanel", () => {
  it("renders the contact, household, and opportunities by label + stage", async () => {
    getConversionMock.mockResolvedValue(summary);

    render(<LeadConvertedPanel leadId="lead-1" productLines={productLines} />);

    await waitFor(() => {
      expect(
        document.getElementById("lead-converted-summary"),
      ).toBeInTheDocument();
    });
    expect(getConversionMock).toHaveBeenCalledWith("lead-1");
    expect(
      document.getElementById("lead-converted-contact-name"),
    ).toHaveTextContent("Maria Lopez");
    expect(
      document.getElementById("lead-converted-household-name"),
    ).toHaveTextContent("Lopez Household");
    // The product-line key is shown by its human label.
    expect(
      document.getElementById("lead-converted-opportunity-opp-1-line"),
    ).toHaveTextContent("Medicare Advantage");
    expect(
      document.getElementById("lead-converted-opportunity-opp-2-line"),
    ).toHaveTextContent("Final Expense");
  });

  it("falls back to the raw key for an unknown product line", async () => {
    getConversionMock.mockResolvedValue({
      ...summary,
      opportunities: [{ id: "opp-9", product_line: "mystery_line", stage: "New" }],
    });

    render(<LeadConvertedPanel leadId="lead-1" productLines={productLines} />);

    await waitFor(() => {
      expect(
        document.getElementById("lead-converted-opportunity-opp-9-line"),
      ).toHaveTextContent("mystery_line");
    });
  });

  it("shows a calm error line when the summary fails to load", async () => {
    getConversionMock.mockRejectedValue(new Error("boom"));

    render(<LeadConvertedPanel leadId="lead-1" productLines={productLines} />);

    await waitFor(() => {
      expect(document.getElementById("lead-converted-error")).toBeInTheDocument();
    });
    expect(document.getElementById("lead-converted-summary")).toBeNull();
  });
});
