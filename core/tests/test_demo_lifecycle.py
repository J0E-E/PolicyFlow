"""Unit tests for the demo-lifecycle scheduler — P1.8 Epic 10.

The scheduler (`app.demo.runtime`) is the background task that self-cleans the demo:
a sweep-first loop running `purge(Expired())` every interval, plus a once-a-night
`purge(All())` on each crossing of the configured reset hour. These tests are **pure
units** — no Postgres, no broker. They drive the loop and the lifespan with:

- `purge_sessions` monkeypatched to a recording stub (no DB), so each call's scope is
  captured;
- `_utc_now` monkeypatched to a controllable clock, so the nightly-crossing decision
  is deterministic;
- `asyncio.sleep` monkeypatched to yield the event loop without real delay, so the
  loop iterates fast and cancellation surfaces cleanly.

They prove: sweep-first (the first expiry purge runs before the first sleep), the
interval cadence (a purge per iteration), log-and-continue on a raising purge, a clean
cancel on shutdown, the pure `crossed_nightly_reset` helper's no-catch-up + once-per-
day contract, the loop firing `purge(All)` once on a crossing alongside ongoing expiry
sweeps, and that the lifespan starts/stops the task cleanly. `pytest.ini` sets
`asyncio_mode = auto`; the async tests carry an explicit `@pytest.mark.asyncio` to
match the other loop-test modules.
"""

import asyncio
import contextlib
import datetime

import pytest

from app import main as main_module
from app.demo import runtime as runtime_module
from app.demo.purge import All, Expired
from app.demo.runtime import (
    crossed_nightly_reset,
    demo_lifecycle_lifespan,
    run_demo_lifecycle_loop,
)
from app.main import app_lifespan


def _utc(year, month, day, hour, minute=0):
    """Build a tz-aware UTC datetime, the clock the loop reads via `_utc_now`."""
    return datetime.datetime(
        year, month, day, hour, minute, tzinfo=datetime.timezone.utc
    )


def _patch_no_delay_sleep(monkeypatch):
    """Replace the loop's `asyncio.sleep` with a no-delay event-loop yield.

    Captures the *real* `asyncio.sleep` **before** patching, so the replacement yields
    control (`real_sleep(0)`) without re-entering itself — patching the shared
    `asyncio.sleep` to a body that calls `asyncio.sleep` would recurse forever.
    """
    real_sleep = asyncio.sleep

    async def no_delay_sleep(_seconds):
        await real_sleep(0)

    monkeypatch.setattr(runtime_module.asyncio, "sleep", no_delay_sleep)


# --- The pure crossing helper (no clock, no DB) ------------------------------


def test_crossed_nightly_reset_does_not_fire_before_the_reset_hour():
    """A tick before the reset hour on a fresh date does not fire, date unchanged."""
    last_run = datetime.date(2026, 6, 23)
    should_fire, new_last_run = crossed_nightly_reset(
        _utc(2026, 6, 24, 3),  # 03:00, before the 04:00 reset hour
        reset_hour_utc=4,
        last_run_date=last_run,
    )
    assert should_fire is False
    assert new_last_run == last_run


def test_crossed_nightly_reset_fires_at_the_hour_on_a_fresh_date():
    """The first tick at/after the reset hour on a new date fires and advances."""
    should_fire, new_last_run = crossed_nightly_reset(
        _utc(2026, 6, 24, 4),  # 04:00, the reset hour, on a date later than last run
        reset_hour_utc=4,
        last_run_date=datetime.date(2026, 6, 23),
    )
    assert should_fire is True
    assert new_last_run == datetime.date(2026, 6, 24)


def test_crossed_nightly_reset_fires_exactly_once_per_day():
    """After firing, later same-day ticks do not re-fire (last_run advanced to today)."""
    # First crossing of the day fires.
    should_fire, last_run = crossed_nightly_reset(
        _utc(2026, 6, 24, 4),
        reset_hour_utc=4,
        last_run_date=datetime.date(2026, 6, 23),
    )
    assert should_fire is True

    # A later tick the same day, feeding the advanced date back in, does not re-fire.
    should_fire_again, last_run_again = crossed_nightly_reset(
        _utc(2026, 6, 24, 9),
        reset_hour_utc=4,
        last_run_date=last_run,
    )
    assert should_fire_again is False
    assert last_run_again == last_run


def test_crossed_nightly_reset_no_boot_catch_up():
    """Seeding last_run to *today* means a boot after the reset hour does not fire.

    The task start seeds `last_run_date = today`; a first tick later that same day —
    even well past the reset hour — reads "already run today" and does not fire. The
    wipe only fires once the clock crosses into the *next* day's reset hour.
    """
    today = datetime.date(2026, 6, 24)
    # Boot at 09:00, after the 04:00 reset hour, with last_run seeded to today.
    should_fire, _ = crossed_nightly_reset(
        _utc(2026, 6, 24, 9),
        reset_hour_utc=4,
        last_run_date=today,
    )
    assert should_fire is False


# --- The loop (purge + clock + sleep all faked) ------------------------------


class _PurgeRecorder:
    """A `purge_sessions` stand-in that records each call's scope, no DB."""

    def __init__(self):
        self.scopes = []

    async def __call__(self, scope, *, delete_session_row):
        self.scopes.append(scope)
        assert delete_session_row is True  # Epic 10 always deletes the session row.
        return None


async def _run_loop_for_a_few_iterations(monkeypatch, *, purge, clock_times):
    """Drive `run_demo_lifecycle_loop` through a handful of iterations then cancel.

    Patches `purge_sessions`, `_utc_now` (returning successive `clock_times`, holding
    the last value once exhausted), and `asyncio.sleep` (a no-delay yield). Returns
    after a clean cancellation.
    """
    monkeypatch.setattr(runtime_module, "purge_sessions", purge)

    clock = iter(clock_times)
    last_time = [clock_times[-1]]

    def fake_now():
        try:
            last_time[0] = next(clock)
        except StopIteration:
            pass
        return last_time[0]

    monkeypatch.setattr(runtime_module, "_utc_now", fake_now)
    _patch_no_delay_sleep(monkeypatch)

    task = asyncio.create_task(run_demo_lifecycle_loop())
    for _ in range(20):
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_loop_sweeps_expired_first_and_repeats(monkeypatch):
    """Sweep-first: an expiry purge runs before any sleep, then once per iteration.

    The clock stays before the reset hour, so no nightly wipe fires — every recorded
    scope is `Expired`, and at least one ran (the sweep-first proof).
    """
    purge = _PurgeRecorder()
    # All ticks at 03:00 (before the 04:00 default reset hour) — expiry-only.
    await _run_loop_for_a_few_iterations(
        monkeypatch,
        purge=purge,
        clock_times=[_utc(2026, 6, 24, 3)],
    )

    assert len(purge.scopes) >= 1
    assert all(isinstance(scope, Expired) for scope in purge.scopes)


@pytest.mark.asyncio
async def test_loop_survives_a_purge_that_raises(monkeypatch):
    """A purge that raises is swallowed; the loop survives to the next iteration."""
    call_count = 0

    async def flaky_purge(scope, *, delete_session_row):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("simulated purge DB blip")
        return None

    await _run_loop_for_a_few_iterations(
        monkeypatch,
        purge=flaky_purge,
        clock_times=[_utc(2026, 6, 24, 3)],
    )

    # More than one purge ran, so the loop survived the first call's raise.
    assert call_count >= 2


@pytest.mark.asyncio
async def test_loop_fires_purge_all_once_on_a_crossing(monkeypatch):
    """On a nightly crossing the loop fires `purge(All)` exactly once, amid sweeps.

    The clock starts before the reset hour (loop seeds last_run to that date), then
    crosses into the next day at/after the reset hour on a later tick — so exactly one
    `All` purge fires, surrounded by ongoing `Expired` sweeps.
    """
    purge = _PurgeRecorder()
    # First _utc_now (task start seed) is 2026-06-24 03:00 → last_run = 06-24.
    # Subsequent ticks cross into 2026-06-25 04:00 (the reset hour, a new date).
    clock_times = [
        _utc(2026, 6, 24, 3),  # start seed: last_run = 06-24
        _utc(2026, 6, 24, 3, 30),  # iter 1 crossing-check: same day, no fire
        _utc(2026, 6, 25, 4),  # iter 2 crossing-check: new day at reset hour → fire
        _utc(2026, 6, 25, 5),  # iter 3+: same day, already fired, no re-fire
    ]
    await _run_loop_for_a_few_iterations(
        monkeypatch,
        purge=purge,
        clock_times=clock_times,
    )

    all_scopes = [scope for scope in purge.scopes if isinstance(scope, All)]
    expired_scopes = [scope for scope in purge.scopes if isinstance(scope, Expired)]
    assert len(all_scopes) == 1  # the wipe fired exactly once on the crossing
    assert len(expired_scopes) >= 2  # expiry sweeps kept running around it


# --- The lifespan (composition smoke) ----------------------------------------


@pytest.mark.asyncio
async def test_demo_lifecycle_lifespan_starts_and_stops_cleanly(monkeypatch):
    """The lifespan launches the loop task on entry and cancels it on exit.

    Drives the lifespan directly (the test client's ASGITransport fires no lifespan
    events). With `purge_sessions` and `asyncio.sleep` faked, entering the context
    starts the task and exiting cancels + awaits it, leaving no running task.
    """
    purge = _PurgeRecorder()
    monkeypatch.setattr(runtime_module, "purge_sessions", purge)
    monkeypatch.setattr(runtime_module, "_utc_now", lambda: _utc(2026, 6, 24, 3))
    _patch_no_delay_sleep(monkeypatch)

    async with demo_lifecycle_lifespan(app=None):
        # Give the loop a few turns so at least one sweep runs inside the context.
        for _ in range(5):
            await asyncio.sleep(0)
        assert len(purge.scopes) >= 1

    # After exit, no demo-lifecycle task should still be pending.
    pending = [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task() and not task.done()
    ]
    assert pending == []


# --- The composed app lifespan stack -----------------------------------------


@pytest.mark.asyncio
async def test_app_lifespan_enters_and_exits_both_lifespans(monkeypatch):
    """`app_lifespan` enters the event-bus + demo-lifecycle lifespans, exits in reverse.

    A pure composition smoke test (no broker, no DB): both inner lifespans are faked
    with recording async context managers, and the test asserts `app_lifespan` enters
    both on startup and unwinds both on shutdown in reverse order (the AsyncExitStack
    contract). Proves the stack wires every lifecycle task without replacing the
    `FastAPI(lifespan=...)` arg.
    """
    events = []

    def recording_lifespan(name):
        @contextlib.asynccontextmanager
        async def _lifespan(app):
            events.append(f"{name}:enter")
            try:
                yield
            finally:
                events.append(f"{name}:exit")

        return _lifespan

    monkeypatch.setattr(
        main_module, "event_bus_lifespan", recording_lifespan("event_bus")
    )
    monkeypatch.setattr(
        main_module, "demo_lifecycle_lifespan", recording_lifespan("demo_lifecycle")
    )

    async with app_lifespan(app=None):
        assert events == ["event_bus:enter", "demo_lifecycle:enter"]

    # Shutdown unwinds the stack in reverse (last entered, first exited).
    assert events == [
        "event_bus:enter",
        "demo_lifecycle:enter",
        "demo_lifecycle:exit",
        "event_bus:exit",
    ]
