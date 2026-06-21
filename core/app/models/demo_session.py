"""The `DemoSession` ORM model — one row per demo *visit*.

A visit to the demo mints a server-side demo session, carried to the browser in
its own `pf_demo_session` cookie (independent of the login `pf_session`). The row
is the authoritative record of when the visit's 24-hour window expires and is the
enumerable handle a later purge sweeps by. `last_tenant_slug` is informational —
it remembers which tenant the visitor last looked at so a fresh session can
preserve it. Lives in the shared `platform` schema, mirroring `auth_sessions`.

This is the table-only mapping for the tracer bullet (Epic 1). The per-session
seed ledger, the `demo_purge` role, and the per-tenant index land in later epics.
"""

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class DemoSession(Base):
    """A demo-visit session, keyed by its raw UUID and bounded by `expires_at`."""

    __tablename__ = "demo_sessions"
    __table_args__ = {"schema": "platform"}

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
    expires_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), nullable=False
    )
    last_tenant_slug: Mapped[Optional[str]] = mapped_column(
        sa.Text, nullable=True
    )
