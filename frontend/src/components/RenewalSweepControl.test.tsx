// Tests for the Platform-Admin renewal-sweep control (P2.4 Epic 6/8). It is a
// variant-driven, self-contained control (its own popover flag + its own sweep call +
// its own feedback), so it renders in isolation with the api mocked. Follows the
// suite's pattern — @testing-library/react + fireEvent (no @testing-library/user-event,
// not a project dependency). Covers, for the AEP variant: the masthead trigger opens
// the popover; Run shows the {generated, skipped} result via the aria-live region; a
// failed sweep shows an inline aria-live error while the surface stays open with Run
// ready to retry — plus the anniversary variant's distinct ids + its own sweep call.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import RenewalSweepControl, {
  AEP_SWEEP_VARIANT,
  ANNIVERSARY_SWEEP_VARIANT,
} from "./RenewalSweepControl.tsx";
import { runAepSweep, runAnniversarySweep } from "../api";

// Mock the api module — the variants call `runAepSweep` / `runAnniversarySweep`; every
// test sets its own resolved/rejected behavior. (No real backend exists under jsdom.)
vi.mock("../api", () => ({
  runAepSweep: vi.fn(),
  runAnniversarySweep: vi.fn(),
}));

const mockedRunAepSweep = vi.mocked(runAepSweep);
const mockedRunAnniversarySweep = vi.mocked(runAnniversarySweep);

afterEach(() => {
  vi.clearAllMocks();
});

function openSurface(variant = AEP_SWEEP_VARIANT) {
  render(<RenewalSweepControl variant={variant} />);
  const trigger = document.getElementById(
    `app-masthead-${variant.key}-sweep-button`,
  )!;
  trigger.focus();
  fireEvent.click(trigger);
  return trigger;
}

describe("RenewalSweepControl", () => {
  it("renders a labelled trigger and no surface until opened", () => {
    render(<RenewalSweepControl variant={AEP_SWEEP_VARIANT} />);

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
    expect(surface).toHaveAttribute("aria-labelledby", "aep-renewal-sweep-title");
    expect(document.getElementById("aep-renewal-sweep-run")).toBeInTheDocument();
  });

  it("runs the sweep and shows the generated/skipped result", async () => {
    mockedRunAepSweep.mockResolvedValue({ generated: 1, skipped: 0 });
    openSurface();

    fireEvent.click(document.getElementById("aep-renewal-sweep-run")!);

    await waitFor(() => {
      expect(document.getElementById("aep-renewal-sweep-result")).toHaveTextContent(
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

    fireEvent.click(document.getElementById("aep-renewal-sweep-run")!);

    await waitFor(() => {
      expect(document.getElementById("aep-renewal-sweep-result")).toHaveTextContent(
        "Generated 3 renewals, skipped 2.",
      );
    });
  });

  it("shows an inline error and keeps the surface open when the sweep fails", async () => {
    mockedRunAepSweep.mockRejectedValue(new Error("boom"));
    openSurface();

    fireEvent.click(document.getElementById("aep-renewal-sweep-run")!);

    await waitFor(() => {
      expect(document.getElementById("aep-renewal-sweep-error")).toHaveTextContent(
        "Could not run the sweep. Please try again.",
      );
    });
    // The surface stays open and Run is interactive again for a retry.
    expect(
      document.getElementById("app-masthead-aep-sweep-surface"),
    ).toBeInTheDocument();
    expect(document.getElementById("aep-renewal-sweep-run")).not.toBeDisabled();
  });

  it("renders the anniversary variant with its own ids and fires its own sweep", async () => {
    mockedRunAnniversarySweep.mockResolvedValue({ generated: 1, skipped: 0 });
    openSurface(ANNIVERSARY_SWEEP_VARIANT);

    // The anniversary instance carries its own key-prefixed ids and its own label.
    const trigger = screen.getByRole("button", {
      name: "Run anniversary renewal sweep",
    });
    expect(trigger).toBe(
      document.getElementById("app-masthead-anniversary-sweep-button"),
    );

    fireEvent.click(document.getElementById("anniversary-renewal-sweep-run")!);

    await waitFor(() => {
      expect(
        document.getElementById("anniversary-renewal-sweep-result"),
      ).toHaveTextContent("Generated 1 renewal, skipped 0.");
    });
    // It calls the anniversary endpoint, not the AEP one.
    expect(mockedRunAnniversarySweep).toHaveBeenCalledTimes(1);
    expect(mockedRunAepSweep).not.toHaveBeenCalled();
  });
});
