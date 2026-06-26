"""The `Policy` ORM model — one issued insurance policy (P2.3).

Like ``Application`` / ``Opportunity``, this model is **deliberately schema-less**: it
names the table ``policies`` but binds it to no schema, so it resolves against the
active ``search_path`` and the one class serves every tenant. The table exists only
inside each tenant schema (migration ``0018``) and is excluded from ``alembic
check``, so the migration owns it and this model mirrors its columns.

An approved application auto-issues one policy in the approve transaction (Epic 8):
a human-readable ``policy_number`` plus the carrier / product / coverage / premium
**copied from the application** (a frozen snapshot — the issued terms), with
``status`` landing ``'Active'``. ``opportunity_id`` / ``application_id`` /
``contact_id`` link it back to its origins.
"""

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class Policy(Base):
    """One issued policy, resolved via `search_path` into the active tenant schema."""

    __tablename__ = "policies"
    # No schema binding (like `Application`): resolved against the active
    # `search_path`. Surrogate uuid PK generated app-side. `status` carries the
    # migration's `DEFAULT 'Active'` as a `server_default`. `pk_policies` from
    # `app.db`.

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    application_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    contact_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    policy_number: Mapped[str] = mapped_column(sa.Text, nullable=False)
    carrier: Mapped[str] = mapped_column(sa.Text, nullable=False)
    product_label: Mapped[str] = mapped_column(sa.Text, nullable=False)
    coverage_amount: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    premium_monthly: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    premium_annual: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        sa.Text, nullable=False, server_default=sa.text("'Active'")
    )
    correlation_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    demo_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(sa.Uuid, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
    )
