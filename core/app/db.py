"""Async SQLAlchemy engine, session factory, and declarative base for the core service.

This is the database spine the rest of the phase builds on: a single async engine
created from `DATABASE_URL`, a session factory that hands out request-scoped
sessions, the `get_db` FastAPI dependency, and the `Base` every ORM model will
extend. No tables exist yet — domain models arrive in Epic 2.

The stored `DATABASE_URL` is asyncpg-style (``postgres://`` / ``postgresql://``,
per docker-compose.yml). The async engine needs the scheme spelled out as
``postgresql+asyncpg://``, so `get_asynchronous_database_url` rewrites it — the
async twin of the synchronous ``postgresql+psycopg://`` rewrite in
`core/alembic/env.py`, with the same fail-fast spirit.
"""

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import settings


def get_asynchronous_database_url() -> str:
    """Return the DATABASE_URL rewritten for SQLAlchemy's async asyncpg driver.

    The stored URL is asyncpg-style (``postgres://`` or ``postgresql://``). The
    async engine requires the driver spelled out, so the scheme is rewritten to
    ``postgresql+asyncpg://`` while the credentials, host, and database name are
    left untouched. A missing or unsupported scheme raises a clear `RuntimeError`
    so boot fails fast rather than handing a broken URL to the engine.
    """
    database_url = settings.database_url
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url
    if database_url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + database_url[len("postgresql://"):]
    if database_url.startswith("postgres://"):
        return "postgresql+asyncpg://" + database_url[len("postgres://"):]
    raise RuntimeError(
        "DATABASE_URL is missing or has an unsupported scheme; expected one of "
        "postgres://, postgresql://, or postgresql+asyncpg://. The async engine "
        "cannot be built, so boot fails fast rather than serving a broken app."
    )


# Built at module import. `create_async_engine` is lazy — it opens no connection
# until the first query, so importing this module never touches Postgres.
engine = create_async_engine(get_asynchronous_database_url())

# Hands out async sessions bound to the engine above. `expire_on_commit=False`
# is the idiomatic async default: it keeps already-loaded attributes usable after
# a commit instead of forcing a fresh (awaitable) database round trip to read them.
session_factory = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """The declarative base every ORM model extends.

    Empty for now — the first domain models (tenants, users, auth_sessions)
    arrive in Epic 2 and will subclass this.
    """


async def get_db() -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped async database session, closing it when done.

    Used as a FastAPI dependency: the `async with` block opens a session for the
    request and the context manager closes it once the request ends, whether it
    succeeds or raises.
    """
    async with session_factory() as session:
        yield session
