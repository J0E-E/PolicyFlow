// Tests for the households index page (Epic 14). jsdom has no backend, so `../api`
// is mocked: getHouseholds drives the list. The page renders react-router links, so
// it is wrapped in a MemoryRouter. Covers: loading, the loaded list with detail
// links + member subtext, the empty state, and the error + retry path.

import { fireEvent, render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import HouseholdsListPage from "./HouseholdsListPage.tsx";
import type { HouseholdSearchResult } from "../api";

vi.mock("../api", () => ({
  getHouseholds: vi.fn(),
}));

import { getHouseholds } from "../api";

const getHouseholdsMock = vi.mocked(getHouseholds);

const sampleHouseholds: HouseholdSearchResult[] = [
  {
    id: "household-1",
    name: "Ramirez Household",
    members: [{ first_name: "Rosa", last_name: "Ramirez" }],
  },
  {
    id: "household-2",
    name: "Familia Household",
    members: [],
  },
];

function renderPage() {
  return render(
    <MemoryRouter>
      <HouseholdsListPage />
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("HouseholdsListPage", () => {
  it("shows a loading line while the households resolve", () => {
    getHouseholdsMock.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(document.getElementById("households-list-loading")).not.toBeNull();
  });

  it("fetches every visible household with an empty query", async () => {
    getHouseholdsMock.mockResolvedValue(sampleHouseholds);
    renderPage();
    await waitFor(() =>
      expect(document.getElementById("households-list")).not.toBeNull(),
    );
    expect(getHouseholdsMock).toHaveBeenCalledWith("");
  });

  it("renders each household as a link to its detail page, with member subtext", async () => {
    getHouseholdsMock.mockResolvedValue(sampleHouseholds);
    renderPage();

    await waitFor(() =>
      expect(document.getElementById("households-list")).not.toBeNull(),
    );

    const firstLink = document.getElementById("households-list-row-household-1-link");
    expect(firstLink?.tagName).toBe("A");
    expect(firstLink).toHaveAttribute("href", "/app/households/household-1");
    expect(
      document.getElementById("households-list-row-household-1-name"),
    ).toHaveTextContent("Ramirez Household");
    expect(
      document.getElementById("households-list-row-household-1-members"),
    ).toHaveTextContent("Rosa Ramirez");

    // A member-less household reads a calm fallback, never a blank.
    expect(
      document.getElementById("households-list-row-household-2-members"),
    ).toHaveTextContent("No members yet");
  });

  it("shows the empty state when no households are visible", async () => {
    getHouseholdsMock.mockResolvedValue([]);
    renderPage();
    await waitFor(() =>
      expect(document.getElementById("households-list-empty")).not.toBeNull(),
    );
    expect(document.getElementById("households-list")).toBeNull();
  });

  it("shows an error with a Retry that refetches", async () => {
    getHouseholdsMock.mockRejectedValueOnce(new Error("boom"));
    renderPage();

    await waitFor(() =>
      expect(document.getElementById("households-list-error")).not.toBeNull(),
    );

    getHouseholdsMock.mockResolvedValueOnce(sampleHouseholds);
    fireEvent.click(
      document.getElementById("households-list-error-retry-button")!,
    );

    await waitFor(() =>
      expect(document.getElementById("households-list")).not.toBeNull(),
    );
    expect(getHouseholdsMock).toHaveBeenCalledTimes(2);
  });
});
