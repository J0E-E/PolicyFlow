"""The audit-record ORM models — one per audit store (Epic 2's `0007` tables).

Migration ``0007_audit_records`` stood up **two** append-only stores with
**identical** columns: a tenantless ``platform.audit_records`` table in the shared
``platform`` schema, and a per-tenant ``audit_records`` table inside **each**
tenant schema. This module maps both with two standalone classes (the codebase
idiom — every model is an explicit class; the column shape is held identical by
``tests/test_audit_record_models.py`` rather than by a shared mixin).

The split mirrors the established platform-bound / schema-less divide:

- ``PlatformAuditRecord`` is bound to the ``platform`` schema (like
  ``TenantDataKey`` / ``Tenant``), so Alembic reflects it and ``alembic check``
  drift-checks it against the migration.
- ``AuditRecord`` is **deliberately schema-less** (like ``TenantSettings`` /
  ``PiiDemoRecord``): it names the table ``audit_records`` but binds no schema, so
  Postgres resolves it against whatever ``search_path`` is active and the same one
  class serves every tenant. The physical table exists only inside each tenant
  schema, so this default-schema copy is **excluded** from ``alembic check`` by
  the schema-guarded filter in ``core/alembic/env.py`` ``include_object`` (the
  platform twin, which shares the table name, stays in the comparison).

Both carry the identical ten columns from ``0007_audit_records.py`` verbatim. The
primary-key name ``pk_audit_records`` comes for free from the ``pk`` naming
convention in ``app.db``. The ``ix_audit_records_occurred_at`` index on
``occurred_at`` is declared **only** on the drift-checked ``PlatformAuditRecord``
— with an **explicit** ``sa.Index("ix_audit_records_occurred_at", ...)`` name
because the ``ix`` naming convention's ``column_0_label`` would prepend the
schema-qualified table and produce ``ix_platform_audit_records_occurred_at``,
which ``alembic check`` flags as drift against the migration. The migration owns
the schema-less copy's index just as ``0006`` owns ``PiiDemoRecord``'s, because a
declared index on an excluded-from-drift table would never be reconciled against
the live database.
"""

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class PlatformAuditRecord(Base):
    """A single tenantless audit record in the `platform` schema (drift-checked)."""

    __tablename__ = "audit_records"
    # The `occurred_at` index is declared explicitly with the migration's exact
    # name. `index=True` would instead render as `ix_platform_audit_records_
    # occurred_at` (the `ix` naming convention's `column_0_label` includes the
    # schema-qualified table prefix), which `alembic check` reports as drift
    # against migration 0007's `ix_audit_records_occurred_at`. The explicit name
    # is the plan's documented fallback for that convention mismatch.
    __table_args__ = (
        sa.Index("ix_audit_records_occurred_at", "occurred_at"),
        {"schema": "platform"},
    )

    # Surrogate uuid primary key generated app-side via `default=uuid.uuid4`
    # (matching `PiiDemoRecord`); the migration column carries no DB-side default.
    # The PK name `pk_audit_records` comes from the `pk` naming convention.
    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    occurred_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(sa.Uuid, nullable=True)
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.Uuid, nullable=True
    )
    actor_role: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    event_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    entity_type: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    entity_id: Mapped[Optional[uuid.UUID]] = mapped_column(sa.Uuid, nullable=True)
    field_names: Mapped[Optional[list[str]]] = mapped_column(
        sa.ARRAY(sa.Text), nullable=True
    )
    outcome: Mapped[str] = mapped_column(sa.Text, nullable=False)


class AuditRecord(Base):
    """A single tenant audit record, resolved via `search_path` (schema-less)."""

    __tablename__ = "audit_records"
    # No schema binding (like `PiiDemoRecord` / `TenantSettings`, unlike
    # `PlatformAuditRecord`): the table is resolved against the active
    # `search_path`, so one class serves every tenant schema. This default-schema
    # copy is excluded from `alembic check` by the schema-guarded filter in
    # `core/alembic/env.py`; the `occurred_at` index is owned by migration 0007
    # (a declared index here would never be reconciled, like `PiiDemoRecord`'s).

    # Surrogate uuid primary key generated app-side, identical to the platform
    # twin. The PK name `pk_audit_records` comes from the `pk` naming convention;
    # constraint names are per-schema, not cluster-global, so the shared name in
    # the platform schema and each tenant schema does not clash.
    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    occurred_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(sa.Uuid, nullable=True)
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.Uuid, nullable=True
    )
    actor_role: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    event_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    entity_type: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    entity_id: Mapped[Optional[uuid.UUID]] = mapped_column(sa.Uuid, nullable=True)
    field_names: Mapped[Optional[list[str]]] = mapped_column(
        sa.ARRAY(sa.Text), nullable=True
    )
    outcome: Mapped[str] = mapped_column(sa.Text, nullable=False)
