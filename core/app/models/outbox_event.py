"""The `OutboxEvent` ORM model — the per-tenant transactional outbox row.

Migration ``0008_event_bus`` stood up an ``outbox`` table inside **each** tenant
schema (the ``0007`` per-tenant pattern). Each row is one event written in the
*same* database transaction as the state change that produced it, so an event is
never lost relative to the committed state — the transactional-outbox mechanism
frozen by the TDD (§5.2).

Like ``PiiDemoRecord`` / ``AuditRecord`` (and unlike the platform-bound
``Tenant`` / ``TenantDataKey``), this model is **deliberately schema-less**: it
names the table ``outbox`` but binds no schema, so Postgres resolves it against
whatever ``search_path`` is active and the same one class serves every tenant.
The physical table exists only inside each tenant schema, so this default-schema
copy is **excluded** from ``alembic check`` by the filter in
``core/alembic/env.py`` ``include_object``.

Because the table is schema-less and drift-excluded, the migration **owns** every
index and constraint (the partial ``ix_outbox_unpublished`` scan index and the
defensive ``uq_outbox_event_id`` unique). This twin declares columns + the primary
key only — a declared index here would never be reconciled against the live
database, exactly as ``PiiDemoRecord``'s blind-index indexes are owned by ``0006``.

The columns mirror the ``EventEnvelope`` fields 1:1 (``app/events/envelope.py``)
plus the relay's ``published_at`` marker, so wire == dataclass == outbox columns.
"""

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class OutboxEvent(Base):
    """A single transactional-outbox row, resolved via `search_path` (schema-less)."""

    __tablename__ = "outbox"
    # No schema binding (like `PiiDemoRecord` / `AuditRecord`): the table is
    # resolved against the active `search_path`, so one class serves every tenant
    # schema. The migration owns the indexes/constraints; this twin declares
    # columns + the primary key only. The PK name `pk_outbox` comes for free from
    # the `pk` naming convention in `app.db`.

    # Surrogate uuid primary key generated app-side via `default=uuid.uuid4`
    # (matching `PiiDemoRecord`); the migration column carries no DB-side default.
    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    event_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    event_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    schema_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    correlation_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    causation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.Uuid, nullable=True
    )
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.Uuid, nullable=True
    )
    actor_role: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    demo_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.Uuid, nullable=True
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(
        sa.TIMESTAMP(timezone=True), nullable=True
    )
