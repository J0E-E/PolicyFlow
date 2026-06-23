"""DB tests for the purge engine — P1.8 Epic 9.

These run against the real Postgres booted in Docker (the same `database_engine` /
`db_session` substrate as `test_session_lead_instantiation.py`). They prove
`app.demo.purge.purge_sessions` removes exactly one session's overlay across **both**
tenant schemas while leaving every other session and the shared `NULL` baseline
untouched.

The engine opens its **own** session as the `demo_purge` role through the
module-global `app.demo.purge.session_factory`, so this file points that global at
the container database with a per-file monkeypatch fixture, mirroring
`container_relay_session_factory` in `test_relay.py`. The seeding path
(`ensure_session_leads`) encrypts via `app.pii.keys.session_factory`, so the tests
also take `container_keys_session_factory`.

The container database is **session-scoped and shared**, so each test first clears
both tenants' `leads`, the seed ledger, and `platform.demo_sessions` — owning its
precondition — then runs `seed(db_session)` so the tenants + keys (and the Epic 8
`NULL` historical baseline) exist. `pytest.ini` sets `asyncio_mode = auto`, so the
async tests carry no decorator.

This module covers the **Session** scope (Phase 2). The `Expired` / `All` scopes and
the no-op run are proven in `test_demo_purge_scopes.py` (Phase 3).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.demo import purge as purge_module
from app.demo.instantiation import ensure_session_leads
from app.demo.purge import Session, purge_sessions
from app.seed import seed
from app.tenancy.registry import FLORIDA, SUNSHINE


@pytest.fixture
def container_purge_session_factory(database_engine, monkeypatch):
    """Point `app.demo.purge.session_factory` at the migrated container database.

    The purge engine opens its **own** session through the module-global
    `app.demo.purge.session_factory` as the `demo_purge` role — separate from any
    request's `get_db`, the same own-session shape as `app.events.relay`. The DB
    substrate must point that global at the container database, otherwise the purge
    would hit the unreachable eager default engine. `monkeypatch` restores the real
    factory after each test. A mirror of `container_relay_session_factory` in
    `test_relay.py`.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    monkeypatch.setattr(purge_module, "session_factory", session_factory)
    return session_factory


async def _reset_state(db_session) -> None:
    """Clear both tenants' `leads`, the ledger, and demo_sessions, then seed tenants.

    Owns the precondition on the shared container so the count assertions are
    deterministic regardless of test order. `seed(db_session)` (idempotent)
    re-creates the tenant rows, per-tenant data keys, and the Epic 8 shared
    historical `NULL` baseline.
    """
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


async def _count_ledger_rows(db_session, demo_session_id: uuid.UUID) -> int:
    """Count `platform.demo_session_tenant_seed` markers for one session."""
    return (
        await db_session.execute(
            text(
                "SELECT COUNT(*) FROM platform.demo_session_tenant_seed "
                "WHERE demo_session_id = :id"
            ),
            {"id": demo_session_id},
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


async def _seed_two_sessions_across_both_schemas(db_session):
    """Instantiate two sessions' queues in both tenants; return their ids + baseline.

    Returns `(session_a, session_b, baseline)` where `baseline` maps each schema to
    its shared `NULL` historical row count, captured after seeding so the purge
    assertions can prove it is left intact.
    """
    session_a = await _mint_demo_session(db_session)
    session_b = await _mint_demo_session(db_session)

    for session_id in (session_a, session_b):
        for tenant in (SUNSHINE, FLORIDA):
            await ensure_session_leads(db_session, tenant, session_id)

    baseline = {
        tenant.schema_name: await _count_seed_baseline_leads(
            db_session, tenant.schema_name
        )
        for tenant in (SUNSHINE, FLORIDA)
    }
    # The Epic 8 baseline must be non-empty or the "intact" assertion is vacuous.
    assert all(count > 0 for count in baseline.values())
    return session_a, session_b, baseline


async def test_session_scope_purges_one_session_across_both_schemas(
    container_keys_session_factory, container_purge_session_factory, db_session
):
    """`purge(Session(a), delete_session_row=False)` removes a's overlay everywhere.

    Session a's leads (both schemas) and its ledger rows are gone; its
    `demo_sessions` row is **kept** (the visitor's session continues); session b's
    leads + ledger + row and the shared `NULL` baseline are all untouched.
    """
    await _reset_state(db_session)
    session_a, session_b, baseline = await _seed_two_sessions_across_both_schemas(
        db_session
    )

    counts = await purge_sessions(Session(session_a), delete_session_row=False)

    # The return object reports exactly what it deleted.
    assert counts.session_ids == (session_a,)
    assert counts.leads_deleted[SUNSHINE.schema_name] == 4
    assert counts.leads_deleted[FLORIDA.schema_name] == 4
    assert counts.total_leads_deleted == 8
    assert counts.ledger_deleted == 2  # one marker per tenant
    assert counts.session_rows_deleted == 0  # delete_session_row=False

    # Session a's overlay is gone in both schemas; its row + ledger cleared.
    for tenant in (SUNSHINE, FLORIDA):
        assert (
            await _count_leads_for_session(
                db_session, tenant.schema_name, session_a
            )
            == 0
        )
    assert await _count_ledger_rows(db_session, session_a) == 0
    # The session row itself survives — Session-scope reset keeps it (Epic 11).
    assert await _demo_session_row_exists(db_session, session_a) is True

    # Session b is wholly untouched.
    for tenant in (SUNSHINE, FLORIDA):
        assert (
            await _count_leads_for_session(
                db_session, tenant.schema_name, session_b
            )
            == 4
        )
    assert await _count_ledger_rows(db_session, session_b) == 2
    assert await _demo_session_row_exists(db_session, session_b) is True

    # The shared NULL baseline is intact in both schemas.
    for tenant in (SUNSHINE, FLORIDA):
        assert (
            await _count_seed_baseline_leads(db_session, tenant.schema_name)
            == baseline[tenant.schema_name]
        )
