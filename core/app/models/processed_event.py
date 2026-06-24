"""The `ProcessedEvent` ORM model — the per-tenant consumer idempotency row.

Migration ``0008_event_bus`` stood up a ``processed_events`` table inside **each**
tenant schema (the ``0007`` per-tenant pattern). Each row records that one named
consumer has processed one event: the unique ``(consumer_name, event_id)`` key is
the dedupe signal (a duplicate insert means "already processed"), and the row is
also the consumer's tenant-scoped, test-observable effect and the seed of the
future per-record event timeline (P1.9 reads it).

Like ``PiiDemoRecord`` / ``AuditRecord`` (and unlike the platform-bound
``Tenant`` / ``TenantDataKey``), this model is **deliberately schema-less**: it
names the table ``processed_events`` but binds no schema, so Postgres resolves it
against whatever ``search_path`` is active and the same one class serves every
tenant. The physical table exists only inside each tenant schema, so this
default-schema copy is **excluded** from ``alembic check`` by the filter in
``core/alembic/env.py`` ``include_object``.

Because the table is schema-less and drift-excluded, the migration **owns** the
``uq_processed_events_consumer_name_event_id`` unique constraint; this twin
declares columns + the primary key only (a declared constraint here would never
be reconciled against the live database, exactly as ``PiiDemoRecord``'s indexes
are owned by ``0006``).
"""

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class ProcessedEvent(Base):
    """A single consumer-idempotency row, resolved via `search_path` (schema-less)."""

    __tablename__ = "processed_events"
    # No schema binding (like `PiiDemoRecord` / `AuditRecord`): the table is
    # resolved against the active `search_path`, so one class serves every tenant
    # schema. The migration owns the unique `(consumer_name, event_id)` dedup
    # constraint; this twin declares columns + the primary key only. The PK name
    # `pk_processed_events` comes for free from the `pk` naming convention.

    # Surrogate uuid primary key generated app-side via `default=uuid.uuid4`
    # (matching `PiiDemoRecord`); the migration column carries no DB-side default.
    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    consumer_name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    event_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    correlation_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
    # Nullable one-line reaction result (e.g. the enrichment quality score), filled
    # by the Epic 3 summary on the fresh-insert path; older rows read NULL. The
    # schema-less twin declares the column; migration ``0014`` owns the DB object.
    result_summary: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
