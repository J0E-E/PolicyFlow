"""Unit tests for the public-intake rate limiter (`app.leads.rate_limit`).

Pure unit tests — no DB, no Docker, **no sleeping**. The limiter's only outside
dependency is its clock, so every timing test injects a `FakeClock` it advances by
hand: a window rollover is simulated by jumping the clock past the window length,
never by waiting. This proves the fixed-window behaviour deterministically and
instantly.

Two units under test:

- `client_ip_from_forwarded_for` — the pure first-hop extractor (multi-hop,
  single-hop, surrounding whitespace, `None`, and empty/blank inputs).
- `RateLimiter` — under-limit allowed, the `(limit + 1)`th blocked, the count
  resetting on a window rollover, and distinct IPs counted independently.

`pytest.ini` sets `asyncio_mode = auto`, but everything here is synchronous, so the
tests are plain functions.
"""

from app.leads.rate_limit import RateLimiter, client_ip_from_forwarded_for


class FakeClock:
    """A hand-advanced stand-in for `time.monotonic` — never sleeps.

    Holds the current time in seconds and returns it when called (so it slots in
    where the limiter expects a `now()` callable). A test moves time forward with
    `advance`, letting it cross a window boundary without any real waiting.
    """

    def __init__(self, start: float = 0.0) -> None:
        self.current_time = start

    def __call__(self) -> float:
        return self.current_time

    def advance(self, seconds: float) -> None:
        self.current_time += seconds


# --- client_ip_from_forwarded_for -------------------------------------------


def test_forwarded_for_multi_hop_returns_first_hop():
    """With several comma-separated hops, the first (the original client) wins."""
    header = "203.0.113.7, 70.41.3.18, 150.172.238.178"

    assert client_ip_from_forwarded_for(header) == "203.0.113.7"


def test_forwarded_for_single_hop_returns_that_hop():
    """A single-IP header returns that IP unchanged."""
    assert client_ip_from_forwarded_for("203.0.113.7") == "203.0.113.7"


def test_forwarded_for_strips_surrounding_whitespace():
    """Whitespace around the first hop is trimmed off."""
    assert client_ip_from_forwarded_for("  203.0.113.7  , 70.41.3.18") == "203.0.113.7"


def test_forwarded_for_none_returns_none():
    """A missing header (`None`) yields `None` — nothing to key on."""
    assert client_ip_from_forwarded_for(None) is None


def test_forwarded_for_empty_or_blank_returns_none():
    """An empty or whitespace-only header yields `None`, not an empty string."""
    assert client_ip_from_forwarded_for("") is None
    assert client_ip_from_forwarded_for("   ") is None


# --- RateLimiter ------------------------------------------------------------

CLIENT_IP = "203.0.113.7"
OTHER_CLIENT_IP = "198.51.100.42"


def test_first_limit_hits_in_a_window_are_allowed():
    """The first `limit` requests in a window all return `True`."""
    clock = FakeClock()
    limiter = RateLimiter(limit=5, window_seconds=60.0, now=clock)

    results = [limiter.is_allowed(CLIENT_IP) for _ in range(5)]

    assert results == [True, True, True, True, True]


def test_limit_plus_one_hit_in_a_window_is_blocked():
    """The `(limit + 1)`th request in the same window returns `False`."""
    clock = FakeClock()
    limiter = RateLimiter(limit=5, window_seconds=60.0, now=clock)

    for _ in range(5):
        assert limiter.is_allowed(CLIENT_IP) is True

    # The sixth hit, still inside the same window, is over the allowance.
    assert limiter.is_allowed(CLIENT_IP) is False


def test_window_rollover_resets_the_count():
    """Crossing into a new window resets the IP's count so it is allowed again."""
    clock = FakeClock()
    limiter = RateLimiter(limit=5, window_seconds=60.0, now=clock)

    # Exhaust the allowance in the first window, then confirm it is blocked.
    for _ in range(5):
        limiter.is_allowed(CLIENT_IP)
    assert limiter.is_allowed(CLIENT_IP) is False

    # Jump past the window boundary into a fresh window; the count resets.
    clock.advance(60.0)

    assert limiter.is_allowed(CLIENT_IP) is True


def test_distinct_ips_are_counted_independently():
    """One IP exhausting its allowance does not block a different IP."""
    clock = FakeClock()
    limiter = RateLimiter(limit=5, window_seconds=60.0, now=clock)

    # Exhaust and then block the first IP.
    for _ in range(5):
        limiter.is_allowed(CLIENT_IP)
    assert limiter.is_allowed(CLIENT_IP) is False

    # A different IP still has its full allowance in the same window.
    results = [limiter.is_allowed(OTHER_CLIENT_IP) for _ in range(5)]
    assert results == [True, True, True, True, True]
    assert limiter.is_allowed(OTHER_CLIENT_IP) is False
