import { useEffect, useState } from "react";
import StampTag from "./StampTag.tsx";
import { getDemoSession } from "../api";
import type { DemoSessionState } from "../api";

// The live masthead countdown (Guide §6.5), replacing the static P1.6 "DEMO
// SESSION" stamp. It is SELF-CONTAINED — it owns its own data, so the Masthead
// stays props-only and gains no new prop.
//
// It fetches `GET /api/demo/session` ONCE on mount, then — for an `active`
// session — counts down LOCALLY from `expires_at` via a 1s timer (no polling).
// The figure shows hours:minutes left as `DEMO SESSION · HH:MM REMAINING` in a
// tabular mono register, so the minute digits tick in place without reflow. A
// live tick that reaches zero FREEZES at `00:00` (the friendly "session ended"
// notice is a later epic, not here).
//
// Every other state — `expired`, `none`, the in-flight load, and a fetch error —
// falls back to the plain "DEMO SESSION" overline stamp (no number), keeping the
// stable `app-masthead-session-stamp` id so existing anchors still resolve.

// What the fetch is currently doing, so the loading / loaded / error branches
// render exactly once and never overlap (mirrors SelectTenantPage's LoadState).
type LoadState =
  | { kind: "loading" }
  | { kind: "loaded"; session: DemoSessionState }
  | { kind: "error" };

/**
 * Whole minutes left until `expiresAt`, floored at zero (a passed deadline reads
 * `0`, never negative). Returns `null` when the timestamp is unparseable, so the
 * caller falls back to the plain stamp rather than rendering a broken figure.
 */
function minutesRemaining(expiresAt: string, now: number): number | null {
  const expiryMilliseconds = Date.parse(expiresAt);
  if (Number.isNaN(expiryMilliseconds)) {
    return null;
  }
  const remainingMilliseconds = expiryMilliseconds - now;
  if (remainingMilliseconds <= 0) {
    return 0;
  }
  return Math.floor(remainingMilliseconds / 60_000);
}

/** Format whole minutes as a zero-padded `HH:MM` (hours:minutes) figure. */
function formatHoursMinutes(totalMinutes: number): string {
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  const padded = (value: number) => String(value).padStart(2, "0");
  return `${padded(hours)}:${padded(minutes)}`;
}

export default function DemoSessionCountdown() {
  const [loadState, setLoadState] = useState<LoadState>({ kind: "loading" });
  // The local clock the countdown reads, advanced by the 1s timer. Starting at
  // `Date.now()` means the first paint already reflects real remaining time.
  const [now, setNow] = useState<number>(() => Date.now());

  // Fetch the session state once on mount. The isActive guard drops a late
  // resolve after unmount, the same pattern SelectTenantPage's loader uses.
  useEffect(() => {
    let isActive = true;
    getDemoSession()
      .then((session) => {
        if (isActive) {
          setLoadState({ kind: "loaded", session });
        }
      })
      .catch(() => {
        if (isActive) {
          setLoadState({ kind: "error" });
        }
      });
    return () => {
      isActive = false;
    };
  }, []);

  // Tick the local clock every second only while the session is active — no
  // timer runs for the plain-stamp states. The interval is cleared on unmount
  // (and when the active session changes) so nothing leaks.
  const isActiveSession =
    loadState.kind === "loaded" && loadState.session.status === "active";
  useEffect(() => {
    if (!isActiveSession) {
      return;
    }
    const timerId = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timerId);
  }, [isActiveSession]);

  // Every non-active state shows the plain overline stamp (no number), keeping
  // the stable id so existing anchors resolve.
  const plainStamp = (
    <StampTag id="app-masthead-session-stamp" variant="overline">
      Demo session
    </StampTag>
  );

  if (loadState.kind !== "loaded" || loadState.session.status !== "active") {
    return plainStamp;
  }

  const { expires_at: expiresAt } = loadState.session;
  if (expiresAt === undefined) {
    return plainStamp;
  }

  const totalMinutes = minutesRemaining(expiresAt, now);
  if (totalMinutes === null) {
    return plainStamp;
  }

  return (
    <span
      id="app-masthead-session-countdown"
      className="masthead-session-countdown"
    >
      <span
        id="app-masthead-session-countdown-label"
        className="masthead-session-countdown-label"
      >
        Demo session
      </span>
      <span
        id="app-masthead-session-countdown-separator"
        className="masthead-session-countdown-separator"
        aria-hidden="true"
      >
        ·
      </span>
      <span
        id="app-masthead-session-countdown-figure"
        className="masthead-session-countdown-figure"
      >
        {formatHoursMinutes(totalMinutes)}
      </span>
      <span
        id="app-masthead-session-countdown-remaining"
        className="masthead-session-countdown-remaining"
      >
        Remaining
      </span>
    </span>
  );
}
