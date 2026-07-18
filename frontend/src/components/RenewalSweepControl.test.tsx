// Tests for the Platform-Admin AEP renewal-sweep control (P2.4 Epic 6). It is a
// self-contained control (its own popover flag + its own `runAepSweep` call + its
// own feedback), so it renders in isolation with the api mocked. Follows the suite's
// pattern — @testing-library/react + fireEvent (no @testing-library/user-event, not
// a project dependency). Covers: the masthead trigger opens the popover; Run shows
// the {generated, skipped} result via the aria-live region; and a failed sweep shows
// an inline aria-live error while the surface stays open with Run ready to retry.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import RenewalSweepControl from "./RenewalSweepControl.tsx";
import { runAepSweep } from "../api";

// Mock the api module — the control calls `runAepSweep`; every test sets its own
// resolved/rejected behavior. (No real backend exists under jsdom.)
vi.mock("../api", () => ({
  runAepSweep: vi.fn(),
}));

const mockedRunAepSweep = vi.mocked(runAepSweep);

afterEach(() => {
  vi.clearAllMocks();
});

function openSurface() {
  render(<RenewalSweepControl />);
  const trigger = document.getElementById("app-masthead-aep-sweep-button")!;
  trigger.focus();
  fireEvent.click(trigger);
  return trigger;
}

describe("RenewalSweepControl", () => {
  it("renders a labelled trigger and no surface until opened", () => {
    render(<RenewalSweepControl />);

    const trigger = screen.getByRole("button", { name: "Run AEP renewal sweep" });
    expect(trigger).toBe(document.getElementById("app-masthead-aep-sweep-button"));
    // Closed by default — no surface in the DOM.
    expect(document.getElementById("app-masthead-aep-sweep-surface")).toBeNull();
  });

  it("opens the popover with the Run action on trigger click", () => {
    openSurface();

    const surface = document.getElementById("app-masthead-aep-sweep-surface")!;
    expect(surface).toBeInTheDocument();
    expect(surface).toHaveAttribute("role", "dialog");
    expect(surface).toHaveAttribute("aria-labelledby", "renewal-sweep-title");
    expect(document.getElementById("renewal-sweep-run")).toBeInTheDocument();
  });

  it("runs the sweep and shows the generated/skipped result", async () => {
    mockedRunAepSweep.mockResolvedValue({ generated: 1, skipped: 0 });
    openSurface();

    fireEvent.click(document.getElementById("renewal-sweep-run")!);

    await waitFor(() => {
      expect(document.getElementById("renewal-sweep-result")).toHaveTextContent(
        "Generated 1 renewal, skipped 0.",
      );
    });
    expect(mockedRunAepSweep).toHaveBeenCalledTimes(1);
    // The surface stays open so the admin can read the counts.
    expect(
      document.getElementById("app-masthead-aep-sweep-surface"),
    ).toBeInTheDocument();
  });

  it("pluralizes the renewal count for a multi-renewal result", async () => {
    mockedRunAepSweep.mockResolvedValue({ generated: 3, skipped: 2 });
    openSurface();

    fireEvent.click(document.getElementById("renewal-sweep-run")!);

    await waitFor(() => {
      expect(document.getElementById("renewal-sweep-result")).toHaveTextContent(
        "Generated 3 renewals, skipped 2.",
      );
    });
  });

  it("shows an inline error and keeps the surface open when the sweep fails", async () => {
    mockedRunAepSweep.mockRejectedValue(new Error("boom"));
    openSurface();

    fireEvent.click(document.getElementById("renewal-sweep-run")!);

    await waitFor(() => {
      expect(document.getElementById("renewal-sweep-error")).toHaveTextContent(
        "Could not run the sweep. Please try again.",
      );
    });
    // The surface stays open and Run is interactive again for a retry.
    expect(
      document.getElementById("app-masthead-aep-sweep-surface"),
    ).toBeInTheDocument();
    expect(document.getElementById("renewal-sweep-run")).not.toBeDisabled();
  });
});
