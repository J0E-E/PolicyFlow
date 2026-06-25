// Tests for the create-new-vs-link household picker (P2.1 Epic 8). `../api` is mocked
// so getHouseholds drives the search. Covers: the search box appears only in link
// mode, a search renders matches with members, picking one reports it up, and a query
// with no matches shows the empty note.

import { fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import HouseholdPicker from "./HouseholdPicker.tsx";

vi.mock("../api", () => ({
  getHouseholds: vi.fn(),
}));

import { getHouseholds } from "../api";

const getHouseholdsMock = vi.mocked(getHouseholds);

afterEach(() => {
  vi.clearAllMocks();
});

function renderPicker(
  overrides: Partial<{
    mode: "new" | "link";
    selectedHouseholdId: string | null;
    onSelectNew: () => void;
    onSelectLinkMode: () => void;
    onSelectHousehold: (id: string) => void;
  }> = {},
) {
  return render(
    <HouseholdPicker
      mode={overrides.mode ?? "new"}
      selectedHouseholdId={overrides.selectedHouseholdId ?? null}
      onSelectNew={overrides.onSelectNew ?? vi.fn()}
      onSelectLinkMode={overrides.onSelectLinkMode ?? vi.fn()}
      onSelectHousehold={overrides.onSelectHousehold ?? vi.fn()}
    />,
  );
}

describe("HouseholdPicker", () => {
  it("hides the search box in new mode and shows it in link mode", () => {
    const { rerender } = renderPicker({ mode: "new" });
    expect(document.getElementById("convert-lead-household-search")).toBeNull();

    rerender(
      <HouseholdPicker
        mode="link"
        selectedHouseholdId={null}
        onSelectNew={vi.fn()}
        onSelectLinkMode={vi.fn()}
        onSelectHousehold={vi.fn()}
      />,
    );
    expect(
      document.getElementById("convert-lead-household-search"),
    ).toBeInTheDocument();
  });

  it("searches and reports the picked household up", async () => {
    getHouseholdsMock.mockResolvedValue([
      {
        id: "household-7",
        name: "Garcia Household",
        members: [{ first_name: "Ana", last_name: "Garcia" }],
      },
    ]);
    const onSelectHousehold = vi.fn();
    renderPicker({ mode: "link", onSelectHousehold });

    fireEvent.change(document.getElementById("convert-lead-household-search")!, {
      target: { value: "Garcia" },
    });

    await waitFor(() => {
      expect(
        document.getElementById("convert-lead-household-option-household-7-name"),
      ).toHaveTextContent("Garcia Household");
    });
    expect(getHouseholdsMock).toHaveBeenCalledWith("Garcia");
    fireEvent.click(
      document.getElementById("convert-lead-household-option-household-7")!,
    );
    expect(onSelectHousehold).toHaveBeenCalledWith("household-7");
  });

  it("shows an empty note when the search matches nothing", async () => {
    getHouseholdsMock.mockResolvedValue([]);
    renderPicker({ mode: "link" });

    fireEvent.change(document.getElementById("convert-lead-household-search")!, {
      target: { value: "no-match" },
    });

    await waitFor(() => {
      expect(
        document.getElementById("convert-lead-household-empty"),
      ).toBeInTheDocument();
    });
  });
});
