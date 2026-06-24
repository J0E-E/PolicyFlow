// Tests for the Platform-Admin workspace reset control (P1.8 Epic 11). It is a
// self-contained control (its own modal flag + its own `resetDemoSession` call +
// its own feedback), so it renders in isolation with the api mocked. Follows the
// suite's pattern — @testing-library/react + fireEvent (no @testing-library/user-event,
// not a project dependency). Covers: the masthead trigger opens the confirm dialog;
// Cancel and Esc dismiss it without calling the api; Reset shows pending, then the
// success confirmation + the switch-to-Agent nudge (and auto-closes); and a failed
// reset shows an inline aria-live error and keeps the dialog open to retry.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import WorkspaceResetControl from "./WorkspaceResetControl.tsx";
import { resetDemoSession } from "../api";

// Mock the api module — the control calls `resetDemoSession`; every test sets its
// own resolved/rejected behavior. (No real backend exists under jsdom.)
vi.mock("../api", () => ({
  resetDemoSession: vi.fn(),
}));

const mockedResetDemoSession = vi.mocked(resetDemoSession);

afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
});

function openDialog() {
  render(<WorkspaceResetControl />);
  const trigger = document.getElementById("app-masthead-reset-button")!;
  trigger.focus();
  fireEvent.click(trigger);
  return trigger;
}

describe("WorkspaceResetControl", () => {
  it("renders a labelled, live trigger and no dialog until opened", () => {
    render(<WorkspaceResetControl />);

    const trigger = screen.getByRole("button", { name: "Reset demo session" });
    expect(trigger).toBe(document.getElementById("app-masthead-reset-button"));
    expect(trigger).not.toBeDisabled();
    // Closed by default — no dialog in the DOM.
    expect(document.getElementById("workspace-reset-dialog")).toBeNull();
  });

  it("opens the confirm dialog with the destructive Reset and quiet Cancel", () => {
    openDialog();

    const dialog = document.getElementById("workspace-reset-dialog")!;
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveAttribute("role", "dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAttribute(
      "aria-labelledby",
      "workspace-reset-title",
    );
    // The copy states what is deleted and that the session stays alive.
    expect(
      document.getElementById("workspace-reset-description"),
    ).toHaveTextContent(/clears every lead .* session and its countdown stay alive/i);
    // Both action buttons are present.
    expect(document.getElementById("workspace-reset-confirm")).toBeInTheDocument();
    expect(document.getElementById("workspace-reset-cancel")).toBeInTheDocument();
  });

  it("closes on Cancel without calling the api", () => {
    openDialog();

    fireEvent.click(document.getElementById("workspace-reset-cancel")!);

    expect(document.getElementById("workspace-reset-dialog")).toBeNull();
    expect(mockedResetDemoSession).not.toHaveBeenCalled();
  });

  it("closes on Esc without calling the api", () => {
    openDialog();

    fireEvent.keyDown(document.getElementById("workspace-reset-dialog")!, {
      key: "Escape",
    });

    expect(document.getElementById("workspace-reset-dialog")).toBeNull();
    expect(mockedResetDemoSession).not.toHaveBeenCalled();
  });

  it("shows the pending state on the Reset button while the call is in flight", async () => {
    // A never-settling promise holds the control in its pending state.
    mockedResetDemoSession.mockReturnValue(new Promise(() => {}));
    openDialog();

    fireEvent.click(document.getElementById("workspace-reset-confirm")!);

    await waitFor(() => {
      const confirm = document.getElementById("workspace-reset-confirm")!;
      expect(confirm).toBeDisabled();
      expect(confirm).toHaveAttribute("aria-busy", "true");
    });
    // Cancel is disabled mid-flight so the dialog cannot be dismissed underneath.
    expect(document.getElementById("workspace-reset-cancel")).toBeDisabled();
  });

  it("shows the success confirmation with the switch-to-Agent nudge, then closes", async () => {
    vi.useFakeTimers();
    mockedResetDemoSession.mockResolvedValue({
      leads_deleted: 4,
      ledger_deleted: 1,
    });
    render(<WorkspaceResetControl />);
    const trigger = document.getElementById("app-masthead-reset-button")!;
    fireEvent.click(trigger);

    fireEvent.click(document.getElementById("workspace-reset-confirm")!);

    // The resolved api promise flushes; the body swaps to the success screen.
    await vi.waitFor(() => {
      expect(
        document.getElementById("workspace-reset-success"),
      ).toBeInTheDocument();
    });
    expect(
      document.getElementById("workspace-reset-success-nudge"),
    ).toHaveTextContent(/switch to agent/i);
    // The confirm controls are gone on the success screen.
    expect(document.getElementById("workspace-reset-confirm")).toBeNull();

    // After the lingering delay the dialog auto-closes.
    await vi.advanceTimersByTimeAsync(2_500);
    expect(document.getElementById("workspace-reset-dialog")).toBeNull();
  });

  it("shows an inline error and keeps the dialog open when the reset fails", async () => {
    mockedResetDemoSession.mockRejectedValue(new Error("boom"));
    openDialog();

    fireEvent.click(document.getElementById("workspace-reset-confirm")!);

    await waitFor(() => {
      expect(
        document.getElementById("workspace-reset-error"),
      ).toHaveTextContent("Could not reset your session. Please try again.");
    });
    // The dialog stays open and the Reset button is interactive again for a retry.
    expect(document.getElementById("workspace-reset-dialog")).toBeInTheDocument();
    expect(document.getElementById("workspace-reset-confirm")).not.toBeDisabled();
  });
});
