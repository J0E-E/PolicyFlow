"""The `QuoteRequest` ORM model — the pollable carrier-quote round-trip (P2.3).

Like ``Opportunity`` / ``Lead``, this model is **deliberately schema-less**: it
names the table ``quote_requests`` but binds it to no schema, so it resolves
against the active ``search_path`` and the one class serves every tenant. The table
exists only inside each tenant schema (migration ``0016``) and is excluded from
``alembic check``, so the migration owns it and this model mirrors its columns.

The request endpoint creates one row ``status='pending'`` and enqueues
``quote.requested``; the ``carrier.quote`` consumer flips ``status`` to
``'completed'`` once it has written the option rows. The agent polls the row's
``status`` (the P1.9 idiom) until ``completed``. ``product_line`` is the key the
consumer reads its registry option templates by; ``correlation_id`` /
``demo_session_id`` are the trace columns carried through the round-trip.
"""

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class QuoteRequest(Base):
    """One carrier-quote round-trip, resolved via `search_path` into the tenant schema."""

    __tablename__ = "quote_requests"
    # No schema binding (like `Opportunity`): resolved against the active
    # `search_path`. Surrogate uuid PK generated app-side. `status` carries the
    # migration's `DEFAULT 'pending'` as a `server_default` so an insert may omit
    # it. `pk_quote_requests` from `app.db`.

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    status: Mapped[str] = mapped_column(
        sa.Text, nullable=False, server_default=sa.text("'pending'")
    )
    product_line: Mapped[str] = mapped_column(sa.Text, nullable=False)
    correlation_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    demo_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(sa.Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")
    )
