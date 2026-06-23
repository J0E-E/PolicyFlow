"""The demo-lifecycle runtime — the FastAPI lifespan that self-cleans the demo.

Epic 9 built the purge engine (`app.demo.purge.purge_sessions`) as a single delete
parameterized by scope; nothing yet *ran* it on a schedule. This module is that
trigger: a background task, started by a FastAPI lifespan (mirroring
`app.events.runtime.event_bus_lifespan`), that

1. **sweeps expired sessions frequently** — every `DEMO_PURGE_INTERVAL_SECONDS` it
   runs `purge(Expired(), delete_session_row=True)`, so a visitor's 24h-old session
   self-cleans without anyone lifting a finger; and
2. **resets the demo to canonical state nightly** — once per crossing of
   `DEMO_NIGHTLY_RESET_HOUR_UTC` it runs `purge(All(), delete_session_row=True)`,
   wiping every overlay back to the shared `NULL` baseline (Phase 2).

**Sweep-first, log-and-continue (the relay idiom).** The loop runs the expiry purge
**immediately on boot** then sleeps the interval — so a freshly-booted demo doesn't
wait a full interval before its first clean. Each iteration's work is wrapped in a
`try/except` that logs (`logger.exception`) and continues, exactly like
`app.events.relay.run_relay_loop`: a single transient DB blip never kills the task.
Single-replica is assumed (the demo runs one core).

**No boot catch-up (the nightly reset's frozen contract).** The task seeds its
last-run date to **today's UTC date** at start, so a boot *after* the reset hour does
**not** fire `purge(All())` that day — the full wipe only ever fires at the
predictable quiet-hour crossing, never on a deploy/restart. The crossing decision is
a pure helper (`crossed_nightly_reset`) so it is testable without a clock or a DB.

**Startup/shutdown.** Startup creates the loop `asyncio.Task`; shutdown cancels it
and awaits it, swallowing the expected `asyncio.CancelledError` — the
`_tear_down_bus` idiom. `main.py` composes this lifespan alongside
`event_bus_lifespan` in one `AsyncExitStack`.
"""

import asyncio
import contextlib
import datetime
import logging

from app.config import settings
from app.demo.purge import All, Expired, purge_sessions

__all__ = [
    "crossed_nightly_reset",
    "demo_lifecycle_lifespan",
    "run_demo_lifecycle_loop",
]

logger = logging.getLogger(__name__)


def _utc_now() -> datetime.datetime:
    """Return the current UTC time. A seam tests patch with a controllable clock."""
    return datetime.datetime.now(datetime.timezone.utc)


def crossed_nightly_reset(
    now_utc: datetime.datetime,
    reset_hour_utc: int,
    last_run_date: datetime.date,
) -> tuple[bool, datetime.date]:
    """Decide whether the nightly canonical wipe should fire on this tick.

    A **pure** function (no clock, no DB) — given the current UTC time, the
    configured reset hour, and the date the wipe last ran, it returns
    ``(should_fire, new_last_run_date)``.

    The wipe fires **once per day**, on the first tick at or after `reset_hour_utc`
    on a date later than `last_run_date`. So:

    - a tick before the reset hour, or on a date already run, does **not** fire and
      leaves `last_run_date` unchanged;
    - the first tick at/after the reset hour on a fresh date fires and advances
      `last_run_date` to today, so the rest of the day's ticks do not re-fire.

    Seeding `last_run_date` to **today** at task start (the caller's job) means a boot
    after the reset hour reads "already run today" and does not fire — the no-catch-up
    contract.
    """
    today = now_utc.date()
    should_fire = today > last_run_date and now_utc.hour >= reset_hour_utc
    if should_fire:
        return True, today
    return False, last_run_date


async def run_demo_lifecycle_loop() -> None:
    """Run the demo-lifecycle scheduler forever — sweep, maybe wipe, sleep, repeat.

    The background task the lifespan runs. Each iteration:

    1. runs `purge(Expired(), delete_session_row=True)` (the frequent expiry sweep);
    2. consults `crossed_nightly_reset` and, on a crossing, runs
       `purge(All(), delete_session_row=True)` (the once-a-night canonical wipe);

    both wrapped in one `try/except` that logs and continues, so a transient failure
    never kills the loop. Then it sleeps `settings.demo_purge_interval_seconds` and
    repeats. The loop is **sweep-first** — the first expiry purge runs before the
    first sleep. It ends only when the task is cancelled (shutdown), which propagates
    cleanly out of the `asyncio.sleep`.

    `last_run_date` is seeded to **today's UTC date** so a boot after the reset hour
    does not fire the wipe that day (no catch-up); it then advances exactly once per
    crossing.
    """
    last_run_date = _utc_now().date()
    while True:
        try:
            await purge_sessions(Expired(), delete_session_row=True)
            should_wipe, last_run_date = crossed_nightly_reset(
                _utc_now(),
                settings.demo_nightly_reset_hour_utc,
                last_run_date,
            )
            if should_wipe:
                logger.info("demo nightly reset crossing; running purge(All)")
                await purge_sessions(All(), delete_session_row=True)
        except Exception:
            logger.exception(
                "demo lifecycle sweep failed; continuing to the next interval"
            )
        await asyncio.sleep(settings.demo_purge_interval_seconds)


@contextlib.asynccontextmanager
async def demo_lifecycle_lifespan(app):
    """Start the demo-lifecycle scheduler on app startup, stop it on shutdown.

    A FastAPI lifespan mirroring `event_bus_lifespan`. The `app` argument is the
    FastAPI application FastAPI passes in; this lifespan does not read it (the
    scheduler is global, not per-app), but the lifespan protocol requires the
    parameter.

    **Startup** creates the loop as a real `asyncio.Task`, keeping the reference so
    shutdown can cancel it. **Shutdown** cancels the task and awaits it, swallowing
    the expected `asyncio.CancelledError` — the `_tear_down_bus` idiom.
    """
    logger.info("demo lifecycle lifespan starting: launching the purge scheduler")
    lifecycle_task = asyncio.create_task(run_demo_lifecycle_loop())
    logger.info("demo lifecycle lifespan started: purge scheduler running")
    try:
        yield
    finally:
        logger.info("demo lifecycle lifespan stopping: cancelling the purge scheduler")
        lifecycle_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await lifecycle_task
        logger.info("demo lifecycle lifespan stopped")
