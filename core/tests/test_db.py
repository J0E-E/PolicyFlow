"""No-Docker wiring tests for `app.db`.

`create_async_engine` is lazy — it opens no connection until the first query — so
these tests prove the module is wired together correctly (async dialect selected,
URL rewritten, session factory and `get_db` shaped right) without ever touching a
live Postgres. They run no SQL.

`settings` is snapshotted from the environment at import time, so each test sets a
well-formed `DATABASE_URL` and reloads `app.config` then `app.db` to pick it up.
"""

import importlib

import pytest
from sqlalchemy.ext.asyncio import AsyncSession


def reload_db_module_with_url(monkeypatch, database_url: str):
    """Set DATABASE_URL, then reload `app.config` and `app.db` to apply it.

    Returns the freshly reloaded `app.db` module. `settings` reads the environment
    only at import time, so `app.config` must be reloaded before `app.db` (which
    reads `settings.database_url` while building its engine).
    """
    monkeypatch.setenv("DATABASE_URL", database_url)

    import app.config

    importlib.reload(app.config)

    # Import `app.db` only after config is reloaded: building its engine reads
    # `settings.database_url`, which must already reflect the URL set above. If
    # `app.db` was imported by an earlier test, reload it so it rebuilds against
    # the refreshed settings.
    import app.db

    reloaded_db = importlib.reload(app.db)
    return reloaded_db


@pytest.fixture(autouse=True)
def restore_reloaded_modules_after_test():
    """Contain the `app.config` / `app.db` reloads so they cannot leak.

    `reload_db_module_with_url` calls `importlib.reload(app.db)`, which
    re-executes the module in place and rebinds `app.db.Base` to a fresh, **empty**
    `MetaData`. The ORM models stay registered on the *original* `Base`, so leaving
    the reloaded module in place silently empties `Base.metadata` for the rest of
    the session. Anything that reads `app.db.Base` at runtime then sees no tables —
    notably `alembic/env.py`, which would make `test_alembic_check_reports_no_drift`
    inspect an empty schema set and pass vacuously (a dead drift guard).

    Snapshot both module namespaces before the test and restore them afterwards so
    each reload is fully contained and the shared `Base` (with its models) survives.
    """
    import app.config
    import app.db

    saved_config = app.config.__dict__.copy()
    saved_db = app.db.__dict__.copy()
    try:
        yield
    finally:
        app.config.__dict__.clear()
        app.config.__dict__.update(saved_config)
        app.db.__dict__.clear()
        app.db.__dict__.update(saved_db)


def test_engine_uses_async_postgres_dialect(monkeypatch):
    """The engine is built with the asyncpg dialect from a bare postgres:// URL."""
    db = reload_db_module_with_url(
        monkeypatch, "postgres://user:secret@localhost:5432/policyflow"
    )

    assert db.engine.url.drivername == "postgresql+asyncpg"


def test_rewrites_bare_postgres_scheme(monkeypatch):
    """A ``postgres://`` URL is rewritten to ``postgresql+asyncpg://``."""
    db = reload_db_module_with_url(
        monkeypatch, "postgres://user:secret@localhost:5432/policyflow"
    )

    assert db.get_asynchronous_database_url() == (
        "postgresql+asyncpg://user:secret@localhost:5432/policyflow"
    )


def test_rewrites_postgresql_scheme(monkeypatch):
    """A ``postgresql://`` URL is rewritten to ``postgresql+asyncpg://``."""
    db = reload_db_module_with_url(
        monkeypatch, "postgresql://user:secret@localhost:5432/policyflow"
    )

    assert db.get_asynchronous_database_url() == (
        "postgresql+asyncpg://user:secret@localhost:5432/policyflow"
    )


def test_raises_on_empty_scheme(monkeypatch):
    """An empty DATABASE_URL fails fast with a clear RuntimeError."""
    db = reload_db_module_with_url(
        monkeypatch, "postgres://user:secret@localhost:5432/policyflow"
    )
    db.settings.database_url = ""

    with pytest.raises(RuntimeError):
        db.get_asynchronous_database_url()


def test_raises_on_garbage_scheme(monkeypatch):
    """An unsupported scheme fails fast with a clear RuntimeError."""
    db = reload_db_module_with_url(
        monkeypatch, "postgres://user:secret@localhost:5432/policyflow"
    )
    db.settings.database_url = "mysql://user:secret@localhost/policyflow"

    with pytest.raises(RuntimeError):
        db.get_asynchronous_database_url()


def test_session_factory_produces_async_session(monkeypatch):
    """Calling the session factory yields an AsyncSession instance."""
    db = reload_db_module_with_url(
        monkeypatch, "postgres://user:secret@localhost:5432/policyflow"
    )

    session = db.session_factory()

    assert isinstance(session, AsyncSession)


async def test_get_db_yields_then_closes_async_session(monkeypatch):
    """`get_db` yields an AsyncSession and closes it when the generator ends.

    The async generator is driven by hand: one step yields the session, the next
    runs the context manager's exit (which closes the session). No query is run.
    """
    db = reload_db_module_with_url(
        monkeypatch, "postgres://user:secret@localhost:5432/policyflow"
    )

    session_generator = db.get_db()
    session = await session_generator.__anext__()

    assert isinstance(session, AsyncSession)

    with pytest.raises(StopAsyncIteration):
        await session_generator.__anext__()
