"""The public-intake rate limiter — a fixed-window per-IP throttle, no framework.

The unauthenticated public intake route is a soft target: anyone on the internet
can POST to it, so without a brake one client could flood a tenant with junk
leads. This module is that brake — an in-memory, per-IP, fixed-window counter that
answers a single yes/no question: *has this IP already used up its allowance in the
current time window?* It is pure logic — **no database, no I/O, no FastAPI** — in
the style of `state.py`, so it is fully unit-testable with a hand-advanced clock
and carries no web framework into the core. Epic 10's public route wires it in.

How the *fixed window* works (the simplest correct scheme): time is chopped into
back-to-back windows of `window_seconds`. The current window is just
`floor(now() / window_seconds)` — an integer that ticks up by one every window.
Each IP carries a `(window_index, count)`. When a request arrives and the IP's
stored window still matches the current one, its count goes up; when the window
has rolled over (a new index), the count resets to `1` for the fresh window. The
first `limit` hits in a window are allowed; the `(limit + 1)`th and beyond are
blocked until the window rolls. This trades a little burstiness at window edges
(up to `2 * limit` across a boundary) for being trivial to reason about and test —
the chosen trade-off for a demo-scale abuse control.

Locked design decisions (frozen at the gate — do not re-decide here):

- **Soft control flow, not a raise.** `is_allowed` returns a `bool` (`True` =
  proceed). The route — not the core — decides what a block *means* (429 vs a
  silent drop), so the limiter stays opinion-free.
- **Injected clock.** `now` defaults to `time.monotonic` (a steadily-rising
  seconds counter that never jumps backwards on a clock change), but tests pass a
  fake clock they advance by hand — so the suite never sleeps.
- **In-memory, no eviction.** State lives in a plain dict and resets on restart
  (acceptable per the TDD's D7). There is no active sweep of stale IPs; for a demo
  the unbounded-growth risk is negligible and a background reaper is out of scope.

IP keying is a separate pure helper, `client_ip_from_forwarded_for`, so the route
can pull the caller's IP out of the `X-Forwarded-For` header (the de-facto record
of the original client when a request passes through a proxy / load balancer)
without the limiter knowing anything about HTTP. Epic 10 owns the missing-header
fallback (what to do when there is no IP to key on at all).
"""

import math
import time
from collections.abc import Callable

from ..config import settings

__all__ = [
    "client_ip_from_forwarded_for",
    "RateLimiter",
    "public_intake_rate_limiter",
]


def client_ip_from_forwarded_for(header: str | None) -> str | None:
    """Return the first `X-Forwarded-For` hop, stripped, or `None` when absent.

    `X-Forwarded-For` is a comma-separated list of IPs a request picked up as it
    passed through proxies; the **first** hop is the original client, the one we
    rate-limit on. This pulls that first entry and trims surrounding whitespace.
    Returns `None` when the header is `None` or blank (nothing to key on) — Epic
    10 owns what the route does in that no-IP case.
    """
    if header is None:
        return None

    first_hop = header.split(",")[0].strip()
    return first_hop or None


class RateLimiter:
    """An in-memory fixed-window per-IP request counter (`is_allowed` = the gate).

    Holds one `(window_index, count)` per client IP in a plain dict. Each call to
    `is_allowed` computes the current window from the injected clock, resets the
    IP's count on a window rollover, increments it, and reports whether the IP is
    still within its allowance. Pure and framework-free — no database, no I/O.
    """

    def __init__(
        self,
        limit: int,
        window_seconds: float,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create a limiter allowing `limit` hits per `window_seconds`-long window.

        `now` is the clock the limiter reads the current time from; it defaults to
        `time.monotonic` (a steadily-rising seconds counter immune to wall-clock
        jumps). Tests pass a fake clock they advance by hand so the suite never
        sleeps. State starts empty; each IP is recorded on its first request.
        """
        self._limit = limit
        self._window_seconds = window_seconds
        self._now = now
        # Per-IP state: client_ip -> (window_index, count_in_that_window).
        self._hits: dict[str, tuple[int, int]] = {}

    def is_allowed(self, client_ip: str) -> bool:
        """Record a hit for `client_ip` and report whether it is within its allowance.

        Computes the current window as `floor(now() / window_seconds)`. If the IP's
        stored window differs (a rollover, or its first-ever request), its count
        resets to `1` for the new window; otherwise the count increments. Returns
        `True` while the count is `<= limit` — so the first `limit` hits in a window
        are allowed and the `(limit + 1)`th onward are blocked until the window
        rolls. The state mutation is the recording of the hit; the return value is
        the gate.
        """
        current_window_index = math.floor(self._now() / self._window_seconds)
        stored_window_index, count = self._hits.get(client_ip, (current_window_index, 0))

        if stored_window_index != current_window_index:
            count = 0

        count += 1
        self._hits[client_ip] = (current_window_index, count)

        return count <= self._limit


# The live limiter the public intake route uses, built from the settings knobs
# (PUBLIC_INTAKE_RATE_LIMIT / PUBLIC_INTAKE_RATE_LIMIT_WINDOW_SECONDS). Module-level
# so it is a single shared instance across requests, keeping per-IP counts in one
# place; uses the default `time.monotonic` clock. Epic 10 calls `is_allowed` on it.
public_intake_rate_limiter = RateLimiter(
    limit=settings.public_intake_rate_limit,
    window_seconds=settings.public_intake_rate_limit_window_seconds,
)
