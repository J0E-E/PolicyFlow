"""The `Contact` ORM model — the per-tenant converted person (P2.1).

Like ``Lead`` / ``PiiDemoRecord``, this model is **deliberately schema-less**: it
names the table ``contacts`` but binds it to no schema, so it resolves against the
active ``search_path`` and the one class serves every tenant. The table exists only
inside each tenant schema (migration ``0015``) and is excluded from ``alembic
check``, so the migration owns it and this model mirrors its columns.

A Contact is the person a Lead converts into. Its PII **mirrors the Lead**: the
searchable, low-sensitivity columns stay plaintext (``first_name`` / ``last_name`` /
``zip_code`` / ``age_band``) and the sensitive fields are the same encrypted
(``bytea``) blobs re-encrypted under the tenant key (email, phone, date of birth,
optional street address). Unlike ``Lead`` there are **no blind-index columns** —
contact dedup is out of scope (TDD §5.2). It also records its ``household_id``, the
converting agent as owner, the originating ``source_lead_id``, and the
``correlation_id`` / ``demo_session_id`` trace columns.
"""

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class Contact(Base):
    """A single contact, resolved via `search_path` into the active tenant schema."""

    __tablename__ = "contacts"
    # No schema binding (like `Lead`): resolved against the active `search_path`.
    # Surrogate uuid PK generated app-side; no blind-index columns (dedup is out
    # of scope). `pk_contacts` comes from the `pk` naming convention in `app.db`.

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    first_name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    last_name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    zip_code: Mapped[str] = mapped_column(sa.Text, nullable=False)
    age_band: Mapped[str] = mapped_column(sa.Text, nullable=False)
    email_encrypted: Mapped[bytes] = mapped_column(
        sa.LargeBinary, nullable=False
    )
    phone_encrypted: Mapped[bytes] = mapped_column(
        sa.LargeBinary, nullable=False
    )
    date_of_birth_encrypted: Mapped[bytes] = mapped_column(
        sa.LargeBinary, nullable=False
    )
    street_address_encrypted: Mapped[Optional[bytes]] = mapped_column(
        sa.LargeBinary, nullable=True
    )
    lead_source: Mapped[str] = mapped_column(sa.Text, nullable=False)
    owner_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.Uuid, nullable=True
    )
    owner_username: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
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
