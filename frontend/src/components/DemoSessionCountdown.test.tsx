// Tests for the live masthead demo-session countdown (P1.8, Guide §6.5). jsdom has
// no backend, so `../api` is mocked and `getDemoSession` is driven per test. The
// component fetches once on mount and — for an active session — ticks LOCALLY from
// `expires_at` via a 1s timer, so the tick + zero-freeze tests drive Vitest's fake
// timers. Every non-active state (expired / none / loading / error) falls back to
// the plain "DEMO SESSION" overline stamp keeping the `app-masthead-session-stamp`
// id (the same convention SelectTenantPage.test.tsx uses to mock `../api`).

import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DemoSessionState } from "../api";
import DemoSessionCountdown from "./DemoSessionCountdown.tsx";

vi.mock("../api", () => ({
  getDemoSession: vi.fn(),
}));

import { getDemoSession } from "../api";

const getDemoSessionMock = vi.mocked(getDemoSession);

/** An `expires_at` ISO string `minutes` (+ `seconds`) ahead of the fixed clock. */
function expiresInFrom(now: number, minutes: number, seconds = 0): string {
  return new Date(now + minutes * 60_000 + seconds * 1_000).toISOString();
}

// A fixed wall clock so every "remaining" computation is deterministic.
const FIXED_NOW = Date.parse("2026-06-21T12:00:00.000Z");

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(FIXED_NOW);
});

afterEach(() => {
  vi.runOnlyPendingTimers();
  vi.useRealTimers();
  vi.clearAllMocks();
});

/** Render and flush the mount fetch's microtasks so the resolved state paints. */
async function renderResolved(session: DemoSessionState) {
  getDemoSessionMock.mockResolvedValue(session);
  render(<DemoSessionCountdown />);
  await act(async () => {
    await Promise.resolve();
  });
}

describe("DemoSessionCountdown", () => {
  it("renders DEMO SESSION · HH:MM REMAINING for an active session", async () => {
    // 2h 35m ahead → "02:35".
    await renderResolved({
      status: "active",
      demo_session_id: "11111111-1111-1111-1111-111111111111",
      expires_at: expiresInFrom(FIXED_NOW, 155),
    });

    expect(
      document.getElementById("app-masthead-session-countdown"),
    ).toBeInTheDocument();
    expect(
      document.getElementById("app-masthead-session-countdown-label"),
    ).toHaveTextContent("Demo session");
    expect(
      document.getElementById("app-masthead-session-countdown-figure"),
    ).toHaveTextContent("02:35");
    expect(
      document.getElementById("app-masthead-session-countdown-remaining"),
    ).toHaveTextContent("Remaining");
    // No plain fallback stamp while active.
    expect(
      document.getElementById("app-masthead-session-stamp"),
    ).toBeNull();
  });

  it("ticks the minute figure down locally as time passes (no re-fetch)", async () => {
    // 90s short of the 30-minute mark → starts at "29" minutes (floored).
    await renderResolved({
      status: "active",
      demo_session_id: "22222222-2222-2222-2222-222222222222",
      expires_at: expiresInFrom(FIXED_NOW, 29, 30),
    });

    expect(
      document.getElementById("app-masthead-session-countdown-figure"),
    ).toHaveTextContent("00:29");

    // Advance 31s locally — crosses the whole-minute boundary to "28".
    await act(async () => {
      vi.advanceTimersByTime(31_000);
    });
    expect(
      document.getElementById("app-masthead-session-countdown-figure"),
    ).toHaveTextContent("00:28");

    // The countdown is pure-local: it fetched exactly once, never polled.
    expect(getDemoSessionMock).toHaveBeenCalledTimes(1);
  });

  it("freezes at 00:00 when a live tick reaches zero", async () => {
    // 40s of runway → starts at "00:00" (under a minute floors to zero).
    await renderResolved({
      status: "active",
      demo_session_id: "33333333-3333-3333-3333-333333333333",
      expires_at: expiresInFrom(FIXED_NOW, 0, 40),
    });

    expect(
      document.getElementById("app-masthead-session-countdown-figure"),
    ).toHaveTextContent("00:00");

    // Tick past the deadline — it stays frozen at 00:00, never negative.
    await act(async () => {
      vi.advanceTimersByTime(120_000);
    });
    expect(
      document.getElementById("app-masthead-session-countdown-figure"),
    ).toHaveTextContent("00:00");
  });

  it("shows the plain DEMO SESSION stamp for an expired session (no figure)", async () => {
    await renderResolved({
      status: "expired",
      demo_session_id: "44444444-4444-4444-4444-444444444444",
      expires_at: expiresInFrom(FIXED_NOW, -10),
      last_tenant_slug: "sunshine-senior-benefits",
    });

    expect(
      document.getElementById("app-masthead-session-stamp-label"),
    ).toHaveTextContent("Demo session");
    expect(
      document.getElementById("app-masthead-session-countdown"),
    ).toBeNull();
  });

  it("shows the plain DEMO SESSION stamp when there is no session", async () => {
    await renderResolved({ status: "none" });

    expect(
      document.getElementById("app-masthead-session-stamp-label"),
    ).toHaveTextContent("Demo session");
    expect(
      document.getElementById("app-masthead-session-countdown"),
    ).toBeNull();
  });

  it("falls back to the plain stamp when the fetch fails", async () => {
    getDemoSessionMock.mockRejectedValue(new Error("network request failed"));
    render(<DemoSessionCountdown />);
    // Flush the rejected mount fetch's microtasks (fake timers are active, so the
    // error-branch state settles here rather than via a real-timer waitFor).
    await act(async () => {
      await Promise.resolve();
    });

    expect(
      document.getElementById("app-masthead-session-stamp"),
    ).toBeInTheDocument();
    expect(
      document.getElementById("app-masthead-session-countdown"),
    ).toBeNull();
  });
});
