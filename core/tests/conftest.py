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
from sqlalchemy import text
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer
from testcontainers.rabbitmq import RabbitMqContainer

from app.audit import service as audit_service_module
from app.db import get_db
from app.main import app
from app.pii import keys as pii_keys_module
from app.tenancy.registry import FLORIDA, SUNSHINE

# The container images are pinned to match production (docker-compose.yml).
POSTGRES_IMAGE = "postgres:16-alpine"
RABBITMQ_IMAGE = "rabbitmq:3.13-management-alpine"

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
def rabbitmq_container():
    """Boot one throwaway RabbitMQ in Docker for the whole test session.

    Started lazily — only when a broker test first requests it — and torn down at
    the end. Mirrors `postgres_container`: there is no exception handling and no
    skip logic, so an unreachable Docker daemon fails the container start and every
    broker test errors. The same deliberate "fail always when Docker is absent"
    choice this substrate makes for the database fixtures. Epics 5/6/11 reuse this
    fixture rather than booting a second broker.
    """
    with RabbitMqContainer(RABBITMQ_IMAGE) as container:
        yield container


def build_amqp_url(container: RabbitMqContainer) -> str:
    """Build an ``amqp://user:pass@host:port/`` URL for the RabbitMQ container.

    Reads the container's published credentials and the host-mapped AMQP port,
    the broker-side mirror of `build_postgresql_url`. aio-pika's
    `connect_robust` takes this URL directly.
    """
    host = container.get_container_host_ip()
    port = container.get_exposed_port(container.port)
    return f"amqp://{container.username}:{container.password}@{host}:{port}/"


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


@pytest.fixture
def container_keys_session_factory(database_engine, monkeypatch):
    """Point `app.pii.keys.session_factory` at the migrated container database.

    Per-tenant key resolution (`get_tenant_keys`) reads the wrapped root key
    through the module-global `app.pii.keys.session_factory` — a session
    **separate** from the request's `get_db`. Since Epic 10 the seed itself
    encrypts demo PII rows (and so resolves keys) on this path, and any
    encrypt/decrypt-bearing endpoint does too, so the DB substrate must point that
    global at the container database — otherwise the key load would hit the
    unreachable eager default engine. `monkeypatch` restores the real factory
    after each test. Mirrors the per-file `container_session_factory` fixture the
    Epic 4/5/6 key tests use.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    monkeypatch.setattr(pii_keys_module, "session_factory", session_factory)
    return session_factory


@pytest.fixture
def container_audit_session_factory(database_engine, monkeypatch):
    """Point `app.audit.service.session_factory` at the migrated container database.

    The audit-emit service (`record_audit_event`) opens its **own** session through
    the module-global `app.audit.service.session_factory` — separate from the
    request's `get_db`, the same own-session shape as `app.pii.keys`. The DB
    substrate must point that global at the container database, otherwise the audit
    write would hit the unreachable eager default engine. `monkeypatch` restores
    the real factory after each test. A verbatim mirror of
    `container_keys_session_factory` above.

    Wired into `db_client` (Epic 6): the platform cross-tenant-read endpoint is the
    first emitting endpoint, so this wiring landed here exactly as the keys fixture
    was. `record_audit_event` opens its own session through this monkeypatched
    global, so any endpoint test driving an emitting route writes to the container.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    monkeypatch.setattr(audit_service_module, "session_factory", session_factory)
    return session_factory


@pytest_asyncio.fixture
async def db_session(database_engine, container_keys_session_factory):
    """Yield a real `AsyncSession` bound to the migrated container database.

    Function-scoped so each test gets a fresh session. This is the seam Epic 12
    builds its session/provider lifecycle tests on. Mirrors `app.db`'s
    `async_sessionmaker(..., expire_on_commit=False)` configuration. It also
    depends on `container_keys_session_factory` so any seed/encrypt path run on
    this session resolves per-tenant keys against the container key store.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def db_client(
    database_engine, container_keys_session_factory, container_audit_session_factory
):
    """Yield an async HTTP client whose `get_db` points at the container database.

    Overrides `app.dependency_overrides[get_db]` with a session bound to the
    migrated container engine — the same override idiom `test_tenant_router.py`
    uses with a fake session, but here the session is real. The override is
    cleaned up afterward so it never leaks into other tests. It also depends on
    `container_keys_session_factory` so the encrypt/decrypt endpoints' key
    resolution reads the container key store, not the unreachable eager engine,
    and on `container_audit_session_factory` (Epic 6) so any audit-emitting
    endpoint's own-session write lands in the container store, not the unreachable
    eager engine. This is the seam Epic 13 builds its endpoint enforcement tests on.
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


@pytest_asyncio.fixture
async def cleanup_committed_renewals(database_engine):
    """Delete every renewal a sweep-endpoint test committed to the shared container.

    Promoted here from the per-file copies once a third test file needed it (P2.4
    Epic 8's anniversary-sweep suite joins Epic 6's AEP-sweep + opportunity-policy-read
    suites). A sweep endpoint commits its `origin='renewal'` opportunities on block
    exit, and those carry a NULL `source_lead_id` (renewals leave it null). Left behind,
    they break the migration round-trip tests that downgrade past 0020 (which restores
    `source_lead_id NOT NULL`). Renewals are created only by these tests and pytest runs
    sequentially, so clearing every `origin='renewal'` opportunity, its renewal-review
    tasks, **and** the outbox event rows the sweep committed (`policy.renewal_due` plus
    the `opportunity.created` events tagged `origin='renewal'`) across both tenant
    schemas at teardown fully isolates the commit — mirroring the `_scoped_session`
    clear the pure service tests roll back.
    """
    yield
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    async with session_factory() as session:
        for tenant in (SUNSHINE, FLORIDA):
            await session.execute(
                text(
                    f"DELETE FROM {tenant.schema_name}.outbox "
                    "WHERE event_type = 'policy.renewal_due' "
                    "OR (event_type = 'opportunity.created' "
                    "AND payload->>'origin' = 'renewal')"
                )
            )
            await session.execute(
                text(
                    f"DELETE FROM {tenant.schema_name}.tasks "
                    "WHERE task_type = 'renewal_review'"
                )
            )
            await session.execute(
                text(
                    f"DELETE FROM {tenant.schema_name}.opportunities "
                    "WHERE origin = 'renewal'"
                )
            )
        await session.commit()
