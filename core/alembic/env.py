"""Alembic migration environment for the core service.

The database URL is read from the DATABASE_URL environment variable (the same
variable config.py reads). The stored URL is asyncpg-style (``postgres://`` /
``postgresql://``); Alembic runs migrations synchronously, so the scheme is
rewritten to ``postgresql+psycopg://`` here. target_metadata points at the domain
models' metadata so autogenerate and ``alembic check`` can catch drift between the
models and the migrations.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Importing the models package registers every table on `Base.metadata`, which
# is what `target_metadata` below points at.
import app.models  # noqa: F401
from app.db import Base

# Alembic Config object, providing access to values in alembic.ini.
config = context.config

# Configure Python logging from the alembic.ini settings.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Point autogenerate at the domain models' metadata so it can compare the models
# against the live database and report drift.
target_metadata = Base.metadata


def get_synchronous_database_url() -> str:
    """Return the DATABASE_URL rewritten for SQLAlchemy's sync psycopg driver.

    The stored URL is asyncpg-style (``postgres://`` or ``postgresql://``).
    Alembic uses a synchronous engine, so the scheme is rewritten to
    ``postgresql+psycopg://`` while the credentials, host, and database name
    are left untouched.
    """
    database_url = os.environ.get("DATABASE_URL", "")
    if database_url.startswith("postgresql+psycopg://"):
        return database_url
    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + database_url[len("postgresql://"):]
    if database_url.startswith("postgres://"):
        return "postgresql+psycopg://" + database_url[len("postgres://"):]
    raise RuntimeError(
        "DATABASE_URL is missing or has an unsupported scheme; expected one of "
        "postgres://, postgresql://, or postgresql+psycopg://. Migrations cannot "
        "run, so boot fails fast rather than serving a half-migrated app."
    )


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode, emitting SQL without a DB connection."""
    context.configure(
        url=get_synchronous_database_url(),
        target_metadata=target_metadata,
        include_schemas=True,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against a live database connection."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_synchronous_database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
