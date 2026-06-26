"""DB tests for the Expired / All purge scopes + the no-op run — P1.8 Epic 9 (Phase 3).

The companion to `test_demo_purge.py` (which proves the `Session` scope). These run
against the same real-Postgres substrate and prove the two whole-footprint scopes,
both called with `delete_session_row=True`:

- **`Expired`** deletes only the past-`expires_at` session's footprint across both
  schemas — leads, ledger, **and** the `demo_sessions` row — leaving the live
  session and the shared `NULL` baseline intact.
- **`All`** clears every session overlay (leads + ledger + rows) across both
  schemas, baseline intact.
- An **empty in-scope run** (no sessions match) deletes nothing and still returns
  zeroed counts (the INFO no-op line).

The engine's own-session `demo_purge` global is pointed at the container by the
per-file `container_purge_session_factory` fixture (mirrors `test_demo_purge.py`).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.demo import purge as purge_module
from app.demo.instantiation import ensure_session_leads
from app.demo.purge import All, Expired, purge_sessions
from app.seed import seed
from app.tenancy.registry import FLORIDA, SUNSHINE


@pytest.fixture
def container_purge_session_factory(database_engine, monkeypatch):
    """Point `app.demo.purge.session_factory` at the migrated container database.

    Mirrors the same-named fixture in `test_demo_purge.py`: the purge engine opens
    its own `demo_purge`-role session through this module-global, so the DB substrate
    must point it at the container, else it would hit the unreachable eager engine.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    monkeypatch.setattr(purge_module, "session_factory", session_factory)
    return session_factory


async def _reset_state(db_session) -> None:
    """Clear both tenants' `leads`, the ledger, and demo_sessions, then re-seed."""
    for schema_name in (SUNSHINE.schema_name, FLORIDA.schema_name):
        await db_session.execute(text(f"DELETE FROM {schema_name}.leads"))
    await db_session.execute(
        text("DELETE FROM platform.demo_session_tenant_seed")
    )
    await db_session.execute(text("DELETE FROM platform.demo_sessions"))
    await db_session.commit()
    await seed(db_session)


async def _mint_demo_session(db_session, *, expired: bool = False) -> uuid.UUID:
    """Insert a `platform.demo_sessions` row and return its id (live by default)."""
    session_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    expires_at = now - timedelta(hours=1) if expired else now + timedelta(days=1)
    await db_session.execute(
        text(
            "INSERT INTO platform.demo_sessions (id, expires_at) "
            "VALUES (:id, :expires_at)"
        ),
        {"id": session_id, "expires_at": expires_at},
    )
    await db_session.commit()
    return session_id


async def _count_leads_for_session(
    db_session, schema_name: str, demo_session_id: uuid.UUID
) -> int:
    """Count `<schema>.leads` rows tagged with `demo_session_id`."""
    return (
        await db_session.execute(
            text(
                f"SELECT COUNT(*) FROM {schema_name}.leads "
                "WHERE demo_session_id = :demo_session_id"
            ),
            {"demo_session_id": demo_session_id},
        )
    ).scalar_one()


async def _count_seed_baseline_leads(db_session, schema_name: str) -> int:
    """Count the shared read-only `demo_session_id IS NULL` baseline rows."""
    return (
        await db_session.execute(
            text(
                f"SELECT COUNT(*) FROM {schema_name}.leads "
                "WHERE demo_session_id IS NULL"
            )
        )
    ).scalar_one()


async def _demo_session_row_exists(db_session, demo_session_id: uuid.UUID) -> bool:
    """Return whether the `platform.demo_sessions` row still exists."""
    found = (
        await db_session.execute(
            text("SELECT 1 FROM platform.demo_sessions WHERE id = :id"),
            {"id": demo_session_id},
        )
    ).first()
    return found is not None


async def _seed_session_overlay(db_session, session_id: uuid.UUID) -> None:
    """Instantiate one session's queue in both tenants."""
    for tenant in (SUNSHINE, FLORIDA):
        await ensure_session_leads(db_session, tenant, session_id)


async def _baseline_counts(db_session) -> dict[str, int]:
    """Capture the shared `NULL` historical baseline per schema (asserted non-empty)."""
    baseline = {
        tenant.schema_name: await _count_seed_baseline_leads(
            db_session, tenant.schema_name
        )
        for tenant in (SUNSHINE, FLORIDA)
    }
    assert all(count > 0 for count in baseline.values())
    return baseline


async def test_expired_scope_purges_only_the_expired_session_footprint(
    container_keys_session_factory, container_purge_session_factory, db_session
):
    """`purge(Expired, delete_session_row=True)` clears only the expired session.

    The expired session's leads + ledger + `demo_sessions` row are gone across both
    schemas; the live session and the shared `NULL` baseline survive.
    """
    await _reset_state(db_session)
    expired_session = await _mint_demo_session(db_session, expired=True)
    live_session = await _mint_demo_session(db_session, expired=False)
    await _seed_session_overlay(db_session, expired_session)
    await _seed_session_overlay(db_session, live_session)
    baseline = await _baseline_counts(db_session)

    counts = await purge_sessions(Expired(), delete_session_row=True)

    assert counts.session_ids == (expired_session,)
    assert counts.total_leads_deleted == 10  # 5 per tenant, expired session only
    assert counts.ledger_deleted == 2
    assert counts.session_rows_deleted == 1  # the expired row itself

    # The expired session's whole footprint is gone.
    for tenant in (SUNSHINE, FLORIDA):
        assert (
            await _count_leads_for_session(
                db_session, tenant.schema_name, expired_session
            )
            == 0
        )
    assert await _demo_session_row_exists(db_session, expired_session) is False

    # The live session is wholly untouched (row + 5 leads per tenant).
    assert await _demo_session_row_exists(db_session, live_session) is True
    for tenant in (SUNSHINE, FLORIDA):
        assert (
            await _count_leads_for_session(
                db_session, tenant.schema_name, live_session
            )
            == 5
        )

    # Baseline intact in both schemas.
    for tenant in (SUNSHINE, FLORIDA):
        assert (
            await _count_seed_baseline_leads(db_session, tenant.schema_name)
            == baseline[tenant.schema_name]
        )


async def test_all_scope_clears_every_session_overlay_baseline_intact(
    container_keys_session_factory, container_purge_session_factory, db_session
):
    """`purge(All, delete_session_row=True)` wipes every session, keeps the baseline."""
    await _reset_state(db_session)
    session_one = await _mint_demo_session(db_session)
    session_two = await _mint_demo_session(db_session)
    await _seed_session_overlay(db_session, session_one)
    await _seed_session_overlay(db_session, session_two)
    baseline = await _baseline_counts(db_session)

    counts = await purge_sessions(All(), delete_session_row=True)

    assert set(counts.session_ids) == {session_one, session_two}
    assert counts.total_leads_deleted == 20  # 2 sessions x 2 tenants x 5 leads
    assert counts.ledger_deleted == 4
    assert counts.session_rows_deleted == 2

    # Every session overlay + row is gone in both schemas.
    for session_id in (session_one, session_two):
        assert await _demo_session_row_exists(db_session, session_id) is False
        for tenant in (SUNSHINE, FLORIDA):
            assert (
                await _count_leads_for_session(
                    db_session, tenant.schema_name, session_id
                )
                == 0
            )

    # Baseline intact.
    for tenant in (SUNSHINE, FLORIDA):
        assert (
            await _count_seed_baseline_leads(db_session, tenant.schema_name)
            == baseline[tenant.schema_name]
        )


async def test_empty_in_scope_run_deletes_nothing(
    container_keys_session_factory, container_purge_session_factory, db_session
):
    """An `Expired` run with no expired sessions is a clean no-op (zeroed counts).

    A single live session is present; nothing is expired, so the run matches zero
    sessions and deletes nothing — the no-op the INFO line still reports.
    """
    await _reset_state(db_session)
    live_session = await _mint_demo_session(db_session, expired=False)
    await _seed_session_overlay(db_session, live_session)
    baseline = await _baseline_counts(db_session)

    counts = await purge_sessions(Expired(), delete_session_row=True)

    assert counts.session_ids == ()
    assert counts.total_leads_deleted == 0
    assert counts.ledger_deleted == 0
    assert counts.session_rows_deleted == 0

    # Nothing was touched: the live session and the baseline are exactly as seeded.
    assert await _demo_session_row_exists(db_session, live_session) is True
    for tenant in (SUNSHINE, FLORIDA):
        assert (
            await _count_leads_for_session(
                db_session, tenant.schema_name, live_session
            )
            == 5
        )
        assert (
            await _count_seed_baseline_leads(db_session, tenant.schema_name)
            == baseline[tenant.schema_name]
        )
