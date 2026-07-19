// Tests for the household detail page (Epic 14). jsdom has no backend, so `../api`
// is mocked: getHouseholdDetail drives the page. The page reads a `:id` route param
// and renders react-router links, so it is wrapped in a MemoryRouter + Routes. Covers
// (Phase 3): loading, the loaded header + contacts + active policies (with the
// overlay *Renewal Due* badge), the 404 not-found branch, and the error + retry path.

import { fireEvent, render, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import HouseholdDetailPage from "./HouseholdDetailPage.tsx";
import type { HouseholdDetail, Policy } from "../api";

vi.mock("../api", () => ({
  getHouseholdDetail: vi.fn(),
  acceptCrossSell: vi.fn(),
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

import { ApiError, acceptCrossSell, getHouseholdDetail } from "../api";
import { useCapability } from "../session";

const getHouseholdDetailMock = vi.mocked(getHouseholdDetail);
const acceptCrossSellMock = vi.mocked(acceptCrossSell);
const useCapabilityMock = vi.mocked(useCapability);

// The cross-sell prompt is `create_edit_records`-gated; default holders on, per-test off.
beforeEach(() => {
  useCapabilityMock.mockReturnValue(true);
});

function makePolicy(overrides: Partial<Policy>): Policy {
  return {
    id: "policy-1",
    opportunity_id: "opp-1",
    application_id: "app-1",
    policy_number: "POL-SSB-2026-ABC123",
    status: "Active",
    carrier: "Evergreen Mutual",
    product_label: "Medicare Advantage Complete",
    coverage_amount: 25000,
    premium_monthly: 40,
    premium_annual: 480,
    issued_at: "2026-01-15T12:00:00Z",
    medicare_id_masked: null,
    ...overrides,
  };
}

function makeDetail(overrides: Partial<HouseholdDetail>): HouseholdDetail {
  return {
    household: { id: "household-1", name: "Ramirez Household" },
    contacts: [{ id: "contact-1", first_name: "Rosa", last_name: "Ramirez" }],
    policies: [makePolicy({})],
    cross_sell: [],
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/app/households/household-1"]}>
      <Routes>
        <Route path="/app/households/:id" element={<HouseholdDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("HouseholdDetailPage — view", () => {
  it("shows a loading line while the household resolves", () => {
    getHouseholdDetailMock.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(document.getElementById("household-detail-loading")).not.toBeNull();
  });

  it("fetches the household by its route id", async () => {
    getHouseholdDetailMock.mockResolvedValue(makeDetail({}));
    renderPage();
    await waitFor(() =>
      expect(document.getElementById("household-detail-header")).not.toBeNull(),
    );
    expect(getHouseholdDetailMock).toHaveBeenCalledWith("household-1");
  });

  it("renders the name, contacts, and active policies", async () => {
    getHouseholdDetailMock.mockResolvedValue(makeDetail({}));
    renderPage();

    await waitFor(() =>
      expect(document.getElementById("household-detail-title")).not.toBeNull(),
    );
    expect(document.getElementById("household-detail-title")).toHaveTextContent(
      "Ramirez Household",
    );
    expect(
      document.getElementById("household-detail-contact-contact-1"),
    ).toHaveTextContent("Rosa Ramirez");
    // The policy renders through the shared PolicySummary under its unique id prefix.
    expect(
      document.getElementById("household-detail-policy-policy-1"),
    ).not.toBeNull();
    expect(
      document.getElementById("household-detail-policy-policy-1-status-label"),
    ).toHaveTextContent("Active");
  });

  it("shows the *Renewal Due* overlay badge on a renewed policy", async () => {
    getHouseholdDetailMock.mockResolvedValue(
      makeDetail({ policies: [makePolicy({ status: "Renewal Due" })] }),
    );
    renderPage();

    await waitFor(() =>
      expect(
        document.getElementById("household-detail-policy-policy-1-status-label"),
      ).not.toBeNull(),
    );
    const badge = document.getElementById(
      "household-detail-policy-policy-1-status",
    );
    expect(badge).toHaveTextContent("Renewal Due");
    // The Renewal Due hue is the Guide's warning stamp (Epic 6 convention).
    expect(badge).toHaveClass("stamp-tag-warning");
  });

  it("renders calm empty notes when there are no contacts or policies", async () => {
    getHouseholdDetailMock.mockResolvedValue(
      makeDetail({ contacts: [], policies: [] }),
    );
    renderPage();

    await waitFor(() =>
      expect(
        document.getElementById("household-detail-policies-empty"),
      ).not.toBeNull(),
    );
    expect(
      document.getElementById("household-detail-contacts-empty"),
    ).not.toBeNull();
  });

  it("shows a calm not-found note on a 404", async () => {
    getHouseholdDetailMock.mockRejectedValue(new ApiError(404, "household not found"));
    renderPage();
    await waitFor(() =>
      expect(document.getElementById("household-detail-not-found")).not.toBeNull(),
    );
  });

  it("shows an error with a Retry that refetches on a non-404 failure", async () => {
    getHouseholdDetailMock.mockRejectedValueOnce(new ApiError(500, "boom"));
    renderPage();

    await waitFor(() =>
      expect(document.getElementById("household-detail-error")).not.toBeNull(),
    );

    getHouseholdDetailMock.mockResolvedValueOnce(makeDetail({}));
    fireEvent.click(
      document.getElementById("household-detail-error-retry-button")!,
    );

    await waitFor(() =>
      expect(document.getElementById("household-detail-header")).not.toBeNull(),
    );
    expect(getHouseholdDetailMock).toHaveBeenCalledTimes(2);
  });
});

const dentalGap = {
  product_line: "dental_vision_hearing",
  product_line_label: "Dental, Vision & Hearing",
};

describe("HouseholdDetailPage — cross-sell prompt", () => {
  it("renders a framed note + Create opportunity per uncovered line (Guide §6.14)", async () => {
    getHouseholdDetailMock.mockResolvedValue(
      makeDetail({ cross_sell: [dentalGap] }),
    );
    renderPage();

    await waitFor(() =>
      expect(
        document.getElementById("household-detail-cross-sell"),
      ).not.toBeNull(),
    );
    expect(
      document.getElementById(
        "household-detail-cross-sell-dental_vision_hearing-note",
      ),
    ).toHaveTextContent("This household has no Dental, Vision & Hearing coverage.");
    expect(
      document.getElementById(
        "household-detail-cross-sell-dental_vision_hearing-accept-button",
      ),
    ).toHaveTextContent("Create opportunity");
  });

  it("suppresses the whole prompt block when there are no coverage gaps", async () => {
    getHouseholdDetailMock.mockResolvedValue(makeDetail({ cross_sell: [] }));
    renderPage();
    await waitFor(() =>
      expect(document.getElementById("household-detail-header")).not.toBeNull(),
    );
    expect(document.getElementById("household-detail-cross-sell")).toBeNull();
  });

  it("accepting a line calls the endpoint and flips the card to a terminal state", async () => {
    getHouseholdDetailMock.mockResolvedValue(
      makeDetail({ cross_sell: [dentalGap] }),
    );
    acceptCrossSellMock.mockResolvedValue({
      id: "opp-9",
      household_id: "household-1",
      contact_id: "contact-1",
      product_line: "dental_vision_hearing",
      product_line_label: "Dental, Vision & Hearing",
      stage: "New",
      origin: "cross_sell",
      source_policy_id: "policy-1",
      owner_username: "agent.one",
    });
    renderPage();

    await waitFor(() =>
      expect(
        document.getElementById(
          "household-detail-cross-sell-dental_vision_hearing-accept-button",
        ),
      ).not.toBeNull(),
    );
    fireEvent.click(
      document.getElementById(
        "household-detail-cross-sell-dental_vision_hearing-accept-button",
      )!,
    );

    await waitFor(() =>
      expect(
        document.getElementById(
          "household-detail-cross-sell-dental_vision_hearing-created",
        ),
      ).not.toBeNull(),
    );
    expect(acceptCrossSellMock).toHaveBeenCalledWith(
      "household-1",
      "dental_vision_hearing",
    );
    // The action is gone (client-side terminal — a refetch would still list the line).
    expect(
      document.getElementById(
        "household-detail-cross-sell-dental_vision_hearing-accept-button",
      ),
    ).toBeNull();
  });

  it("shows the note but NO action for a Read-Only caller", async () => {
    useCapabilityMock.mockReturnValue(false);
    getHouseholdDetailMock.mockResolvedValue(
      makeDetail({ cross_sell: [dentalGap] }),
    );
    renderPage();

    await waitFor(() =>
      expect(
        document.getElementById(
          "household-detail-cross-sell-dental_vision_hearing-note",
        ),
      ).not.toBeNull(),
    );
    expect(
      document.getElementById(
        "household-detail-cross-sell-dental_vision_hearing-accept-button",
      ),
    ).toBeNull();
  });

  it("surfaces a non-destructive inline error when accept fails (409)", async () => {
    getHouseholdDetailMock.mockResolvedValue(
      makeDetail({ cross_sell: [dentalGap] }),
    );
    acceptCrossSellMock.mockRejectedValue(
      new ApiError(409, "product line already covered: dental_vision_hearing"),
    );
    renderPage();

    await waitFor(() =>
      expect(
        document.getElementById(
          "household-detail-cross-sell-dental_vision_hearing-accept-button",
        ),
      ).not.toBeNull(),
    );
    fireEvent.click(
      document.getElementById(
        "household-detail-cross-sell-dental_vision_hearing-accept-button",
      )!,
    );

    await waitFor(() =>
      expect(
        document.getElementById("household-detail-cross-sell-error"),
      ).not.toBeNull(),
    );
    expect(
      document.getElementById("household-detail-cross-sell-error"),
    ).toHaveTextContent("already covered");
    // Non-destructive: the card + its action remain (button re-enabled).
    expect(
      document.getElementById(
        "household-detail-cross-sell-dental_vision_hearing-accept-button",
      ),
    ).not.toBeNull();
  });
});
