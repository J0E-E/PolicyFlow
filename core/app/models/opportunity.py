"""The `Opportunity` ORM model — one per converted product line (P2.1).

Like ``Lead`` / ``PiiDemoRecord``, this model is **deliberately schema-less**: it
names the table ``opportunities`` but binds it to no schema, so it resolves against
the active ``search_path`` and the one class serves every tenant. The table exists
only inside each tenant schema (migration ``0015``) and is excluded from ``alembic
check``, so the migration owns it and this model mirrors its columns.

The conversion action creates one Opportunity per confirmed product line. It carries
both ``contact_id`` and ``household_id`` (the household rollup), the ``product_line``
key, and a ``stage`` that defaults to the literal ``'New'`` — **no** state machine is
pulled forward (P2.2 owns stage transitions). ``estimated_annual_premium`` (P2.3) and
``target_close_date`` (P2.2 / P2.4) are nullable placeholders later phases fill;
``origin`` records how it was created (``'conversion'`` here), alongside the
``source_lead_id`` and the ``correlation_id`` / ``demo_session_id`` trace columns.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class Opportunity(Base):
    """A single opportunity, resolved via `search_path` into the active tenant schema."""

    __tablename__ = "opportunities"
    # No schema binding (like `Lead`): resolved against the active `search_path`.
    # Surrogate uuid PK generated app-side. `stage` carries the migration's
    # `DEFAULT 'New'` as a `server_default` so an insert may omit it; no state
    # machine here (P2.2 owns transitions). `pk_opportunities` from `app.db`.

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    household_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    product_line: Mapped[str] = mapped_column(sa.Text, nullable=False)
    stage: Mapped[str] = mapped_column(
        sa.Text, nullable=False, server_default=sa.text("'New'")
    )
    owner_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.Uuid, nullable=True
    )
    owner_username: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    estimated_annual_premium: Mapped[Optional[Decimal]] = mapped_column(
        sa.Numeric, nullable=True
    )
    target_close_date: Mapped[Optional[date]] = mapped_column(
        sa.Date, nullable=True
    )
    origin: Mapped[str] = mapped_column(sa.Text, nullable=False)
    source_lead_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
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
