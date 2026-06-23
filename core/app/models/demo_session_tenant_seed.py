"""The `DemoSessionTenantSeed` ORM model — the per-session seed-instantiation ledger.

One row marks that a given demo *visit* (`demo_session_id`) has had its private
New queue instantiated in a given tenant (`tenant_slug`). `ensure_session_leads`
writes the row after it inserts that visit's session-tagged lead templates, and
reads it first as the **only** idempotency guard: a re-call for an already-seeded
`(demo_session_id, tenant_slug)` is a no-op (the row is present), while a second,
distinct visit seeds its own copy (a fresh `demo_session_id`, so no row yet) even
though the dup-bait deliberately shares an email across visits.

Keyed by the composite `(demo_session_id, tenant_slug)` so the guard is exact per
visit-and-tenant. Lives in the shared `platform` schema beside `demo_sessions`,
the hand-written twin of which it mirrors; the `0012` migration is its DDL twin
and the two must stay in lock-step.
"""

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class DemoSessionTenantSeed(Base):
    """A ledger row: this visit's New queue was instantiated in this tenant."""

    __tablename__ = "demo_session_tenant_seed"
    __table_args__ = {"schema": "platform"}

    demo_session_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True
    )
    tenant_slug: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    seeded_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
