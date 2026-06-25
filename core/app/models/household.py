"""The `Household` ORM model — the per-tenant account-like grouping (P2.1).

Like ``Lead`` / ``PiiDemoRecord`` (and unlike the platform-bound ``Tenant``), this
model is **deliberately schema-less**: it names the table ``households`` but binds
it to no schema, so Postgres resolves it against the active ``search_path`` and the
one class serves every tenant. The table physically exists only inside each tenant
schema, created per-tenant by migration ``0015``; being schema-less, it is excluded
from ``alembic check`` (see ``core/alembic/env.py`` ``include_object``), so the
migration **owns** the table and this model only mirrors its columns.

A Household is the account-like grouping a Contact belongs to (one or more contacts
roll up to it). It carries no owner (it is shared across its contacts) and no PII —
just the display ``name`` (auto-built as ``"<LastName> Household"`` by the
conversion action) and the ``correlation_id`` / ``demo_session_id`` trace columns
every conversion entity carries.
"""

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class Household(Base):
    """A single household, resolved via `search_path` into the active tenant schema."""

    __tablename__ = "households"
    # No schema binding (like `Lead`): resolved against the active `search_path`.
    # The surrogate uuid PK is generated app-side via `default=uuid.uuid4`; the
    # migration column carries no DB-side default. `pk_households` comes from the
    # `pk` naming convention in `app.db`.

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    correlation_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    demo_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.Uuid, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
