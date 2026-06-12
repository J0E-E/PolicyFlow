"""Shared pytest fixtures for the core backend test suite.

Provides two foundations:

1. An async HTTP client wired directly to the FastAPI app in-process via
   `httpx.ASGITransport`, so tests exercise the real async request path without
   binding a network port or running a server.
2. A **real-database test substrate** (Epic 11): a session-scoped ephemeral
   Postgres booted in Docker via testcontainers, with our Alembic migrations
   applied, plus a DB-backed async session and a DB-backed HTTP client. Epics 12
   (session/provider lifecycle) and 13 (endpoint enforcement) build on these.

Docker absent → the substrate fixtures error and DB tests fail. This is a
deliberate "fail always" choice: there is no skip logic, so a missing Docker
daemon surfaces loudly rather than silently passing untested code.
"""

import os

# Importing the app (and, through it, `app.db` / `app.models`) builds the async
# engine eagerly at import time, which needs a well-formed DATABASE_URL. Default
# one here so a bare test run never fails on an unset URL. `setdefault` means a
# real CI or dev URL already in the environment still wins. The DB substrate
# fixtures below never use this eager engine — they override `get_db` to point at
# the throwaway container instead.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://user:secret@localhost:5432/policyflow"
)

from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from app.db import get_db
from app.main import app

# The container image is pinned to match production (docker-compose.yml).
POSTGRES_IMAGE = "postgres:16-alpine"

# `alembic.ini` and the `alembic/` script directory live in the core package root
# (one level above this tests/ directory).
CORE_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_CONFIG_PATH = CORE_ROOT / "alembic.ini"


@pytest_asyncio.fixture
async def client():
    """Yield an async HTTP client bound to the core FastAPI app.

    Requests go straight to the app through an in-process ASGI transport — no
    live server or open socket. This is the foundation later backend tests
    (e.g. the health ok/degraded tests) build on.
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        yield client


@pytest.fixture(scope="session")
def postgres_container():
    """Boot one throwaway Postgres in Docker for the whole test session.

    Started once per `pytest` run and torn down at the end. There is no exception
    handling: if the Docker daemon is unreachable the container fails to start and
    every database test errors — the deliberate "fail always when Docker is
    absent" choice for this substrate.
    """
    with PostgresContainer(POSTGRES_IMAGE) as container:
        yield container


def build_postgresql_url(container: PostgresContainer) -> str:
    """Build a plain ``postgresql://user:pass@host:port/db`` URL for the container.

    Driverless on purpose: `app.db` / `alembic/env.py` each rewrite this scheme to
    the driver they need (asyncpg for the async engine, psycopg for migrations).
    """
    host = container.get_container_host_ip()
    port = container.get_exposed_port(container.port)
    return (
        f"postgresql://{container.username}:{container.password}"
        f"@{host}:{port}/{container.dbname}"
    )


@pytest.fixture(scope="session")
def database_engine(postgres_container):
    """Apply the migrations to the container, then yield an async engine for it.

    Points `DATABASE_URL` at the container so Alembic's `env.py` reads it, runs
    `alembic upgrade head` (its `env.py` rewrites the scheme to the sync psycopg
    driver), and yields an asyncpg async engine bound to the same container so
    tests read and write through the real, migrated schema.
    """
    database_url = build_postgresql_url(postgres_container)

    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        alembic_config = Config(str(ALEMBIC_CONFIG_PATH))
        alembic_config.set_main_option("script_location", str(CORE_ROOT / "alembic"))
        command.upgrade(alembic_config, "head")
    finally:
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url

    async_database_url = "postgresql+asyncpg://" + database_url[len("postgresql://"):]
    # `NullPool` so no asyncpg connection is held across tests. Each function-scoped
    # test runs on its own event loop (pytest-asyncio's default), and a pooled
    # asyncpg connection bound to a finished loop fails on teardown on Windows
    # (proactor "NoneType has no attribute send"). Opening a fresh connection per
    # session sidesteps that without changing what the tests observe.
    engine = create_async_engine(async_database_url, poolclass=NullPool)
    yield engine


@pytest_asyncio.fixture
async def db_session(database_engine):
    """Yield a real `AsyncSession` bound to the migrated container database.

    Function-scoped so each test gets a fresh session. This is the seam Epic 12
    builds its session/provider lifecycle tests on. Mirrors `app.db`'s
    `async_sessionmaker(..., expire_on_commit=False)` configuration.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def db_client(database_engine):
    """Yield an async HTTP client whose `get_db` points at the container database.

    Overrides `app.dependency_overrides[get_db]` with a session bound to the
    migrated container engine — the same override idiom `test_tenant_router.py`
    uses with a fake session, but here the session is real. The override is
    cleaned up afterward so it never leaks into other tests. This is the seam
    Epic 13 builds its endpoint enforcement tests on.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)
