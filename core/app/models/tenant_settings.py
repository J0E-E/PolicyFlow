"""The `TenantSettings` ORM model — one settings row per tenant schema.

Unlike `Tenant` (which pins ``{"schema": "platform"}``), this model is
**deliberately schema-less**: it names the table ``tenant_settings`` but does not
bind it to a schema. Postgres therefore resolves it against whatever
``search_path`` is active, so the same one class serves every tenant — the
per-request scoping dependency just points ``search_path`` at the right schema.

The table holds a tenant's presentation sliver: a brand colour, an optional logo
URL, and a welcome message, keyed by the ``platform.tenants`` id it configures (a
singleton row per tenant schema). It is the first real tenant-scoped entity, the
concrete target the isolation tests use to prove that one tenant can never read
another's data.

Migration ``0004_tenant_settings`` creates the matching table in each tenant
schema; the seed fills one row per tenant from a small seed-local map.
"""

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class TenantSettings(Base):
    """A single tenant's presentation settings, resolved via `search_path`."""

    __tablename__ = "tenant_settings"
    # No schema binding (unlike `Tenant`): the table is resolved against the
    # active `search_path`. The primary key is named to agree with the
    # hand-written migration 0004 (`pk_tenant_settings`).
    __table_args__ = (
        sa.PrimaryKeyConstraint("tenant_id", name="pk_tenant_settings"),
    )

    # The platform.tenants id this row configures — a singleton row per tenant
    # schema, so the configured tenant_id doubles as the primary key.
    tenant_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid)
    brand_primary_color: Mapped[str] = mapped_column(sa.Text, nullable=False)
    brand_logo_url: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    welcome_message: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
