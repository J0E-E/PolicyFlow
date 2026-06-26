"""The `Application` ORM model — one insurance application per selected quote (P2.3).

Like ``Opportunity`` / ``Quote``, this model is **deliberately schema-less**: it
names the table ``applications`` but binds it to no schema, so it resolves against
the active ``search_path`` and the one class serves every tenant. The table exists
only inside each tenant schema (migration ``0017``) and is excluded from ``alembic
check``, so the migration owns it and this model mirrors its columns.

Selecting an attached quote (Epic 5) creates one row `status='Draft'` with the
carrier / product / coverage / premium **copied from the quote** (a frozen snapshot
— the application carries its own terms even though the quote rows live on). The
remaining columns are filled by later epics on the same row: ``beneficiary`` /
``health_answers`` (the product step, Epic 6), ``medicare_id_encrypted`` (Tenant-1,
Epic 11), ``decision`` / ``decided_at`` (the inline carrier decision, Epic 7), and
``superseded_by_application_id`` (supersession, Epic 10). ``status`` moves through
the pure `app.applications.state` machine.
"""

import uuid
from datetime import datetime
from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class Application(Base):
    """One application, resolved via `search_path` into the active tenant schema."""

    __tablename__ = "applications"
    # No schema binding (like `Opportunity`): resolved against the active
    # `search_path`. Surrogate uuid PK generated app-side. `status` carries the
    # migration's `DEFAULT 'Draft'` as a `server_default`. `pk_applications` from
    # `app.db`.

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    contact_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    product_line: Mapped[str] = mapped_column(sa.Text, nullable=False)
    selected_quote_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    status: Mapped[str] = mapped_column(
        sa.Text, nullable=False, server_default=sa.text("'Draft'")
    )
    # Carrier / product / coverage / premium — a frozen snapshot copied from the
    # selected quote at selection time (whole dollars, like the quote).
    carrier: Mapped[str] = mapped_column(sa.Text, nullable=False)
    product_label: Mapped[str] = mapped_column(sa.Text, nullable=False)
    coverage_amount: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    premium_monthly: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    premium_annual: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    # The product-specific step content (Epic 6), nullable until captured.
    beneficiary: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    health_answers: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    # The Tenant-1 Medicare ID, encrypted at rest (Epic 11), nullable elsewhere.
    medicare_id_encrypted: Mapped[Optional[bytes]] = mapped_column(
        sa.LargeBinary, nullable=True
    )
    # The inline carrier decision (Epic 7), nullable until submitted.
    decision: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(
        sa.TIMESTAMP(timezone=True), nullable=True
    )
    # The superseding application (Epic 10), set when a fresh Draft replaces a
    # declined one.
    superseded_by_application_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.Uuid, nullable=True
    )
    correlation_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    demo_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(sa.Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
    )
