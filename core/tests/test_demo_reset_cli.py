"""Tests for the operator reset CLI — `python -m app.demo.reset` — P1.8 Epic 9 (Phase 4).

Two layers:

- **Pure CLI contract** (no DB): the flag→scope mapping (`--all` → `All`, `--expired`
  → `Expired`) and the argparse guard that exactly one flag is required (zero flags
  or both exit non-zero).
- **End-to-end** (real Postgres): `main(["--all"])` and `main(["--expired"])` drive
  the actual `purge_sessions` engine against the container and print the counts —
  proving the CLI is wired to the engine, not just the mapping.

The engine's own-session `demo_purge` global is pointed at the container by the
per-file `container_purge_session_factory` fixture (mirrors `test_demo_purge.py`); the
seeding path encrypts, so the end-to-end tests also take
`container_keys_session_factory`.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.demo import purge as purge_module
from app.demo import reset as reset_module
from app.demo.instantiation import ensure_session_leads
from app.demo.purge import All, Expired, PurgeCounts
from app.demo.reset import build_parser, main, run, scope_for
from app.seed import seed
from app.tenancy.registry import FLORIDA, SUNSHINE


# --- Pure CLI-contract tests (no database) ----------------------------------


def test_all_flag_maps_to_all_scope():
    """`--all` parses to the `All` scope."""
    arguments = build_parser().parse_args(["--all"])
    assert isinstance(scope_for(arguments), All)


def test_expired_flag_maps_to_expired_scope():
    """`--expired` parses to the `Expired` scope."""
    arguments = build_parser().parse_args(["--expired"])
    assert isinstance(scope_for(arguments), Expired)


def test_no_flag_is_a_usage_error():
    """Zero flags exits non-zero — a scope is required."""
    with pytest.raises(SystemExit) as exit_info:
        build_parser().parse_args([])
    assert exit_info.value.code != 0


def test_both_flags_is_a_usage_error():
    """Both flags at once exits non-zero — the group is mutually exclusive."""
    with pytest.raises(SystemExit) as exit_info:
        build_parser().parse_args(["--all", "--expired"])
    assert exit_info.value.code != 0


def test_main_wires_parse_to_scope_to_engine_and_prints(monkeypatch, capsys):
    """`main(["--all"])` calls the engine with the All scope + delete_session_row=True.

    Proves the CLI's full wiring (argparse → `scope_for` → `purge_sessions` →
    `print`) without a database by capturing the engine call. The end-to-end DB
    tests below then drive the real engine, so both halves are covered.
    """
    captured: dict[str, object] = {}

    async def fake_purge(scope, *, delete_session_row):
        captured["scope"] = scope
        captured["delete_session_row"] = delete_session_row
        return PurgeCounts(session_ids=(uuid.uuid4(),), ledger_deleted=1)

    # `run` calls `purge_sessions` imported into the reset module's namespace.
    monkeypatch.setattr(reset_module, "purge_sessions", fake_purge)

    main(["--all"])

    assert isinstance(captured["scope"], All)
    assert captured["delete_session_row"] is True
    assert "demo purge (All)" in capsys.readouterr().out


# --- End-to-end tests (real Postgres) ---------------------------------------


@pytest.fixture
def container_purge_session_factory(database_engine, monkeypatch):
    """Point `app.demo.purge.session_factory` at the migrated container database.

    Mirrors the same-named fixture in `test_demo_purge.py`: `main` drives the real
    `purge_sessions`, whose own `demo_purge`-role session opens through this
    module-global, so it must point at the container.
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


async def _count_session_tagged_leads(db_session, schema_name: str) -> int:
    """Count every `demo_session_id IS NOT NULL` (overlay) lead in the schema."""
    return (
        await db_session.execute(
            text(
                f"SELECT COUNT(*) FROM {schema_name}.leads "
                "WHERE demo_session_id IS NOT NULL"
            )
        )
    ).scalar_one()


async def _count_demo_session_rows(db_session) -> int:
    """Count the `platform.demo_sessions` rows that remain."""
    return (
        await db_session.execute(
            text("SELECT COUNT(*) FROM platform.demo_sessions")
        )
    ).scalar_one()


async def _seed_session_overlay(db_session, session_id: uuid.UUID) -> None:
    """Instantiate one session's queue in both tenants."""
    for tenant in (SUNSHINE, FLORIDA):
        await ensure_session_leads(db_session, tenant, session_id)


async def test_run_all_drives_the_engine_and_clears_every_session(
    container_keys_session_factory, container_purge_session_factory, db_session
):
    """`run(All())` drives the real engine: every session overlay + row is gone.

    The CLI's `run` coroutine is awaited directly (rather than `main`, whose
    `asyncio.run` cannot nest inside the test's running loop); `test_main_wires_…`
    above already proves `main` reaches `run` with the right scope.
    """
    await _reset_state(db_session)
    await _seed_session_overlay(db_session, await _mint_demo_session(db_session))
    await _seed_session_overlay(db_session, await _mint_demo_session(db_session))

    counts = await run(All())

    # The operator scope always removes the session rows too (delete_session_row).
    assert counts.session_rows_deleted == 2
    assert await _count_demo_session_rows(db_session) == 0
    for tenant in (SUNSHINE, FLORIDA):
        assert (
            await _count_session_tagged_leads(db_session, tenant.schema_name) == 0
        )


async def test_run_expired_drives_the_engine_and_clears_only_expired(
    container_keys_session_factory, container_purge_session_factory, db_session
):
    """`run(Expired())` removes only the expired session; the live one survives."""
    await _reset_state(db_session)
    expired = await _mint_demo_session(db_session, expired=True)
    live = await _mint_demo_session(db_session, expired=False)
    await _seed_session_overlay(db_session, expired)
    await _seed_session_overlay(db_session, live)

    counts = await run(Expired())

    assert counts.session_ids == (expired,)
    assert counts.session_rows_deleted == 1
    # Only the live session's row remains; only its overlay (5 per tenant) stays.
    assert await _count_demo_session_rows(db_session) == 1
    for tenant in (SUNSHINE, FLORIDA):
        assert (
            await _count_session_tagged_leads(db_session, tenant.schema_name) == 5
        )
