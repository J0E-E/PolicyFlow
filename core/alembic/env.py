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


def include_name(name, type_, parent_names) -> bool:
    """Limit autogenerate/check to the schemas the models actually declare.

    With ``include_schemas=True`` Alembic reflects *every* schema in the live
    database — including the migration-owned tenant schemas (``sunshine`` /
    ``florida``) and Postgres's built-in ``public`` / ``information_schema`` —
    none of which any model owns, so Alembic would report them as phantom drift.

    For ``type_ == "schema"`` we keep only the schemas the models declare,
    derived from the metadata itself so the allow-list tracks any future model
    automatically: ``{table.schema for table in Base.metadata.tables.values()}``
    yields ``{None, "platform"}`` (``None`` is Alembic's default schema). For
    every other object type we return ``True`` and leave the comparison untouched.
    """
    if type_ == "schema":
        declared_schemas = {
            table.schema for table in Base.metadata.tables.values()
        }
        return name in declared_schemas
    return True


def include_object(object_, name, type_, reflected, compare_to) -> bool:
    """Exclude the deliberately schema-less tenant tables from comparison.

    ``TenantSettings``, ``PiiDemoRecord``, the schema-less ``AuditRecord``, the
    P1.5 ``OutboxEvent`` / ``ProcessedEvent``, and the P1.7 ``Lead`` all map to the
    default schema in the models but physically exist only inside each tenant
    schema, so without this filter Alembic would want to *create* ``tenant_settings``
    / ``pii_demo`` / ``audit_records`` / ``outbox`` / ``processed_events`` /
    ``leads`` in the default schema (the metadata side) and *drop* the real
    per-tenant copies. Dropping these tables from the comparison closes both halves
    of that phantom drift; the per-tenant copies are also already excluded by
    ``include_name`` (belt and suspenders).

    ``audit_records`` is special: it is the **one** table name shared by a
    schema-less model (``AuditRecord``) and a platform-bound model
    (``PlatformAuditRecord`` → ``platform.audit_records``). Name-only matching
    would wrongly drop the platform twin too, so its exclusion is **schema-
    guarded** on ``object_.schema is None`` — only the default-schema copy is
    dropped, while ``platform.audit_records`` stays in the comparison and is
    drift-checked against the migration. ``tenant_settings`` / ``pii_demo`` /
    ``outbox`` / ``processed_events`` / ``leads`` have no platform twin, so
    name-only matching is safe for them.
    """
    if type_ == "table" and name in {
        "tenant_settings",
        "pii_demo",
        "outbox",
        "processed_events",
        "leads",
    }:
        return False
    if (
        type_ == "table"
        and name == "audit_records"
        and object_.schema is None
    ):
        return False
    return True


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
        include_name=include_name,
        include_object=include_object,
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
            include_name=include_name,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
