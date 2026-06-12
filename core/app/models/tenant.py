"""The `Tenant` ORM model — one row per customer organisation.

Tenants live in the shared `platform` schema: it is the program's reserved home
for cross-tenant identity and registry data. A tenant row is the membership
target every non-platform user points at via `users.tenant_id`, and the seam
P1.2 later uses to pick a per-tenant `search_path`.
"""

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class Tenant(Base):
    """A customer organisation in the shared `platform` schema."""

    __tablename__ = "tenants"
    __table_args__ = {"schema": "platform"}

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    slug: Mapped[str] = mapped_column(sa.Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
