"""Acceptance suite for P2.4 (Renewals & cross-sell) — the composition proof (Epic 16).

The per-slice suites already pin each thread in isolation (`test_aep_sweep_endpoint`,
`test_anniversary_sweep_endpoint`, `test_task_queue_endpoint`, `test_household_cross_sell_accept`,
`test_seed_money_paths`). This module does **not** re-create those proofs — it adds only the
two things no per-slice test can: that all three threads **compose** in one demo session, and
that the baseline seed stays **byte-identical after the threads run**.

Two named tests, both against the real seeded substrate (the shared `seeded` + `db_client`
container):

- **compose** — in one demo session: assume Sunshine Agent → Platform Admin, run the AEP sweep
  (`{1,0}` then a `{0,1}` re-run) and the anniversary sweep (renews the back-dated
  `medicare_supplement`; no none/life line renews), re-assume the owning Agent, complete ONE of
  the two `renewal_review` tasks the sweeps mint, then accept the Ramirez open
  `dental_vision_hearing` cross-sell line — and read the container back to prove the results
  coexist rather than clobber each other.
- **baseline untouched** — fingerprint the baseline (`demo_session_id IS NULL`) money-path
  policy chains, run the threads, re-seed via `app.seed.seed`, and assert the fingerprint is
  unchanged and no new baseline chain was rooted. (Plain re-seed idempotency is already
  `test_seed_money_paths`'s job; the value here is *after the threads have committed*.)

Committing an `origin='renewal'` or `origin='cross_sell'` opportunity (both carry a NULL
`source_lead_id`) would break the 0020 migration round-trip, so both tests carry the shared
`cleanup_committed_renewals` + `cleanup_committed_cross_sell` teardowns (both now in
`conftest.py`, resolved by name).

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no decorator.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.demo.session import DEMO_SESSION_COOKIE_NAME
from app.models.user import Role
from app.seed import seed
from app.tenancy.registry import FLORIDA, SUNSHINE

from .test_demo_assume_persona import assume
from .test_endpoints_db import seeded  # noqa: F401 — fixture used by name
from .test_household_detail import _baseline_household_id


# --- Container read-back helpers (a fresh session; the endpoints already committed) ---


async def _opportunity_lines_by_origin(database_engine, tenant, origin: str) -> set[str]:
    """Return the product lines of every committed opportunity of one origin, one tenant."""
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    async with session_factory() as session:
        rows = (
            await session.execute(
                text(
                    f"SELECT product_line FROM {tenant.schema_name}.opportunities "
                    "WHERE origin = :origin"
                ),
                {"origin": origin},
            )
        ).scalars().all()
    return set(rows)


def _policy_fingerprint(rows) -> set:
    """Fingerprint baseline policies by (id, policy_number, issued_at) — the re-seed seam."""
    return {
        (str(policy_id), policy_number, issued_at)
        for policy_id, policy_number, issued_at in rows
    }


async def _baseline_policies(db_session, schema_name: str):
    """Read the baseline (`demo_session_id IS NULL`) policy rows for the fingerprint."""
    return (
        await db_session.execute(
            text(
                f"SELECT id, policy_number, issued_at "
                f"FROM {schema_name}.policies WHERE demo_session_id IS NULL"
            )
        )
    ).all()


async def _baseline_household_count(db_session, schema_name: str) -> int:
    """Count baseline (`demo_session_id IS NULL`) households — a new chain roots here."""
    return (
        await db_session.execute(
            text(
                f"SELECT COUNT(*) FROM {schema_name}.households "
                "WHERE demo_session_id IS NULL"
            )
        )
    ).scalar_one()


# --- The shared three-thread driver -------------------------------------------


async def _drive_three_threads(db_client, db_session) -> dict:
    """Run all three P2.4 threads in ONE demo session and assert each thread's outcome.

    Threads 1 & 2 (the AEP + anniversary sweeps) run as Platform Admin; thread 3 (task-queue
    completion + cross-sell accept) runs as the re-assumed owning Agent — all sharing the
    single demo session the first `assume` mints (the cookie persists across persona switch).
    Returns the ids the caller's composition / baseline assertions key on.
    """
    # Agent mints the demo session (last_tenant_slug = sunshine); Platform Admin reuses it.
    assert (
        await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT)
    ).status_code == 200
    assert (
        await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.PLATFORM_ADMIN)
    ).status_code == 200
    assert DEMO_SESSION_COOKIE_NAME in db_client.cookies

    # Thread 1 — AEP sweep renews the sole Sunshine MA policy; the re-run is a pure skip.
    first_aep = await db_client.post("/api/renewals/aep-sweep")
    assert first_aep.status_code == 200
    assert first_aep.json() == {"generated": 1, "skipped": 0}
    second_aep = await db_client.post("/api/renewals/aep-sweep")
    assert second_aep.json() == {"generated": 0, "skipped": 1}

    # Thread 2 — anniversary sweep renews the back-dated `medicare_supplement`; the none-line
    # (`final_expense`) and Florida-only life lines generate nothing (proven by the composition
    # read: only medicare_advantage + medicare_supplement carry an origin='renewal' opp).
    anniversary = await db_client.post("/api/renewals/anniversary-sweep")
    assert anniversary.status_code == 200
    assert anniversary.json() == {"generated": 1, "skipped": 0}

    # Thread 3 — back to the owning Agent (agent.one) in the same demo session.
    assert (
        await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT)
    ).status_code == 200

    # Both sweeps minted a `renewal_review` task for agent.one (AEP MA + anniversary
    # medsupp), so there are TWO — complete ONE and leave the other in the queue.
    queue = await db_client.get("/api/tasks")
    assert queue.status_code == 200
    renewal_tasks = [
        task
        for task in queue.json()["tasks"]
        if task["task_type"] == "renewal_review"
    ]
    assert len(renewal_tasks) == 2
    completed_task_id = renewal_tasks[0]["id"]
    remaining_task_id = renewal_tasks[1]["id"]
    completed = await db_client.post(f"/api/tasks/{completed_task_id}/complete")
    assert completed.status_code == 200
    assert completed.json()["task"]["status"] == "completed"

    # Cross-sell accept — open the Ramirez `dental_vision_hearing` line (agent.one owns it).
    household_id = await _baseline_household_id(
        db_session, SUNSHINE, "Ramirez Household"
    )
    accept = await db_client.post(
        f"/api/households/{household_id}/cross-sell",
        json={"product_line": "dental_vision_hearing"},
    )
    assert accept.status_code == 200
    assert accept.json()["opportunity"]["origin"] == "cross_sell"

    return {
        "completed_task_id": completed_task_id,
        "remaining_task_id": remaining_task_id,
        "household_id": household_id,
    }


# --- Phase 2: the three threads compose in one demo session -------------------


async def test_all_three_threads_compose_in_one_demo_session(
    seeded,  # noqa: F811 — fixture param, not a redefinition
    db_client,
    db_session,
    database_engine,
    container_keys_session_factory,
    cleanup_committed_renewals,
    cleanup_committed_cross_sell,
):
    """Both sweeps, a task completion, and a cross-sell accept coexist, not clobber.

    Drives all three P2.4 threads through one demo session, then reads the shared container
    back to prove the results compose.
    """
    result = await _drive_three_threads(db_client, db_session)

    # Both renewal threads' opportunities coexist — the AEP MA renewal and the anniversary
    # medsupp renewal — and no none-line / life-line renewed.
    assert await _opportunity_lines_by_origin(database_engine, SUNSHINE, "renewal") == {
        "medicare_advantage",
        "medicare_supplement",
    }
    # The cross-sell thread's opportunity coexists on the open line.
    assert await _opportunity_lines_by_origin(
        database_engine, SUNSHINE, "cross_sell"
    ) == {"dental_vision_hearing"}

    # The completed task dropped out of the queue; the second renewal task is still open.
    requeried = await db_client.get("/api/tasks")
    assert requeried.status_code == 200
    listed_ids = [task["id"] for task in requeried.json()["tasks"]]
    assert result["completed_task_id"] not in listed_ids
    assert result["remaining_task_id"] in listed_ids


# --- Phase 3: the baseline seed is untouched after the threads run ------------


async def test_baseline_seed_is_untouched_after_the_threads_run(
    seeded,  # noqa: F811 — fixture param, not a redefinition
    db_client,
    db_session,
    container_keys_session_factory,
    cleanup_committed_renewals,
    cleanup_committed_cross_sell,
):
    """Re-seeding after the threads run adds no baseline chain and rewrites nothing.

    The sweeps write `Renewal Due` only on session-owned policies and every thread write is
    session-tagged, so the baseline (`demo_session_id IS NULL`) money-path chains stay
    byte-identical across a re-seed that runs *after* all three threads have committed — the
    composition value on top of `test_seed_money_paths`' plain re-seed idempotency.
    """
    schemas = (SUNSHINE.schema_name, FLORIDA.schema_name)
    before_fingerprint = {
        schema: _policy_fingerprint(await _baseline_policies(db_session, schema))
        for schema in schemas
    }
    before_households = {
        schema: await _baseline_household_count(db_session, schema)
        for schema in schemas
    }

    await _drive_three_threads(db_client, db_session)

    # Re-seed after the threads have committed their session-scoped writes.
    await seed(db_session)

    for schema in schemas:
        after_fingerprint = _policy_fingerprint(
            await _baseline_policies(db_session, schema)
        )
        assert after_fingerprint == before_fingerprint[schema]
        assert after_fingerprint, "expected a non-empty baseline policy set"
        # No new baseline chain was rooted by the re-seed.
        assert (
            await _baseline_household_count(db_session, schema)
            == before_households[schema]
        )
