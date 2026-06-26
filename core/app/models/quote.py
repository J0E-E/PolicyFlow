"""The `Quote` ORM model — one returned carrier option (P2.3).

Like ``Opportunity`` / ``QuoteRequest``, this model is **deliberately schema-less**:
it names the table ``quotes`` but binds it to no schema, so it resolves against the
active ``search_path`` and the one class serves every tenant. The table exists only
inside each tenant schema (migration ``0016``) and is excluded from ``alembic
check``, so the migration owns it and this model mirrors its columns.

The ``carrier.quote`` consumer writes one row per option it generates from the
registry catalog, tagging each with both its ``quote_request_id`` and the
``opportunity_id`` so a read can attach the options to either. ``premium_annual``
is written (not derived in the DB) — the consumer copies it from the registry
template, where it is twelve monthly premiums. Amounts are whole dollars.
"""

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class Quote(Base):
    """One returned carrier option, resolved via `search_path` into the tenant schema."""

    __tablename__ = "quotes"
    # No schema binding (like `Opportunity`): resolved against the active
    # `search_path`. Surrogate uuid PK generated app-side. `pk_quotes` from
    # `app.db`.

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    quote_request_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    carrier: Mapped[str] = mapped_column(sa.Text, nullable=False)
    product_label: Mapped[str] = mapped_column(sa.Text, nullable=False)
    coverage_amount: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    premium_monthly: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    premium_annual: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    correlation_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    demo_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(sa.Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
    )
