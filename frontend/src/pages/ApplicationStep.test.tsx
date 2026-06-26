// Tests for the product-specific application step form (P2.3 Epic 6). jsdom has no
// backend, so `../api` is mocked: patchApplication captures the step. Covers the
// beneficiary form (life lines) and the health questionnaire (health lines),
// including the captured payload shape and the onCaptured callback.

import { fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ApplicationStep from "./ApplicationStep.tsx";
import type { Application } from "../api";

vi.mock("../api", () => ({
  patchApplication: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

import { patchApplication } from "../api";

const patchApplicationMock = vi.mocked(patchApplication);

function makeApplication(overrides: Partial<Application>): Application {
  return {
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
    application_step: "beneficiary",
    beneficiary: null,
    health_answers: null,
    decision: null,
    decided_at: null,
    collects_medicare_id: false,
    medicare_id_masked: null,
    ...overrides,
  };
}

beforeEach(() => {
  patchApplicationMock.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("ApplicationStep", () => {
  it("captures the beneficiary details and fires onCaptured", async () => {
    const captured = makeApplication({
      beneficiary: { full_name: "Jordan Rivera", relationship: "spouse", date_of_birth: "1972-04-18" },
    });
    patchApplicationMock.mockResolvedValue(captured);
    const onCaptured = vi.fn();
    render(
      <ApplicationStep id="step" application={makeApplication({})} onCaptured={onCaptured} />,
    );

    fireEvent.change(document.getElementById("step-full-name")!, {
      target: { value: "Jordan Rivera" },
    });
    fireEvent.change(document.getElementById("step-relationship")!, {
      target: { value: "spouse" },
    });
    fireEvent.change(document.getElementById("step-date-of-birth")!, {
      target: { value: "1972-04-18" },
    });
    fireEvent.click(document.getElementById("step-submit")!);

    await waitFor(() => {
      expect(onCaptured).toHaveBeenCalledWith(captured);
    });
    expect(patchApplicationMock).toHaveBeenCalledWith("app-1", {
      beneficiary: {
        full_name: "Jordan Rivera",
        relationship: "spouse",
        date_of_birth: "1972-04-18",
      },
    });
  });

  it("renders the five health questions and captures their yes/no answers", async () => {
    const application = makeApplication({ product_line: "health", application_step: "health" });
    patchApplicationMock.mockResolvedValue(makeApplication({ application_step: "health" }));
    const onCaptured = vi.fn();
    render(<ApplicationStep id="step" application={application} onCaptured={onCaptured} />);

    // All five questions render.
    for (const key of [
      "tobacco_use",
      "hospitalized_recently",
      "chronic_condition",
      "prescription_medications",
      "family_history",
    ]) {
      expect(document.getElementById(`step-${key}`)).toBeInTheDocument();
    }

    // Check two answers true, leave the rest false, then submit.
    fireEvent.click(document.getElementById("step-chronic_condition")!);
    fireEvent.click(document.getElementById("step-prescription_medications")!);
    fireEvent.click(document.getElementById("step-submit")!);

    await waitFor(() => {
      expect(onCaptured).toHaveBeenCalled();
    });
    expect(patchApplicationMock).toHaveBeenCalledWith("app-1", {
      health_answers: {
        tobacco_use: false,
        hospitalized_recently: false,
        chronic_condition: true,
        prescription_medications: true,
        family_history: false,
      },
    });
  });
});
