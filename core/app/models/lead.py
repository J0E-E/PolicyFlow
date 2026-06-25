"""The `Lead` ORM model — the per-tenant lead intake/queue/qualification entity.

Like ``PiiDemoRecord`` (and unlike the platform-bound ``Tenant`` /
``TenantDataKey``), this model is **deliberately schema-less**: it names the table
``leads`` but does not bind it to a schema. Postgres therefore resolves it against
whatever ``search_path`` is active, so the same one class serves every tenant —
the per-request scoping dependency just points ``search_path`` at the right
schema, and the table physically exists only inside each tenant schema (created
per-tenant by migration ``0009``).

The row carries the full lead shape (TDD §5.2): plaintext, searchable
``first_name`` / ``last_name`` and the low-sensitivity ``zip_code``; the encrypted
(``bytea``) PII blobs (email, phone, date of birth, optional street address); the
two blind-index (``bytea``) columns used for exact-match duplicate detection
without decryption; the derived plaintext ``age_band``; the ``product_lines_of_interest``
key array; the ``lead_source`` / ``status`` text columns (plain text, validated
app-side by ``StrEnum`` — **not** PG enums, the P1.1 lesson); the owner and
duplicate-linkage bookkeeping; the optional free-text ``rejection_reason`` captured
at reject (added by migration ``0010``, kept separate from intake ``notes``); the
``converted_contact_id`` / ``converted_opportunity_ids`` converted-ref columns a
P2.1 freeze sets (added by migration ``0015``, null until ``Converted``); and the
``correlation_id`` / ``demo_session_id`` event-trace columns.

The two blind-index indexes (``ix_leads_email_blind_index`` /
``ix_leads_phone_blind_index``) are **owned by migration 0009**, not declared on
this model: because the table is schema-less it is excluded from ``alembic check``
(see ``core/alembic/env.py`` ``include_object``), so declaring the indexes here
would never be reconciled against the live database anyway.
"""

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class Lead(Base):
    """A single lead, resolved via `search_path` into the active tenant schema."""

    __tablename__ = "leads"
    # No schema binding (like `PiiDemoRecord`, unlike `Tenant`): the table is
    # resolved against the active `search_path`. The primary key is a surrogate
    # uuid generated app-side via `default=uuid.uuid4` (matching `Tenant` /
    # `PiiDemoRecord`); the migration column carries no DB-side default. The PK
    # name `pk_leads` comes for free from the `pk` naming convention in `app.db`.

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    first_name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    last_name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    email_encrypted: Mapped[bytes] = mapped_column(
        sa.LargeBinary, nullable=False
    )
    email_blind_index: Mapped[bytes] = mapped_column(
        sa.LargeBinary, nullable=False
    )
    phone_encrypted: Mapped[bytes] = mapped_column(
        sa.LargeBinary, nullable=False
    )
    phone_blind_index: Mapped[bytes] = mapped_column(
        sa.LargeBinary, nullable=False
    )
    date_of_birth_encrypted: Mapped[bytes] = mapped_column(
        sa.LargeBinary, nullable=False
    )
    age_band: Mapped[str] = mapped_column(sa.Text, nullable=False)
    zip_code: Mapped[str] = mapped_column(sa.Text, nullable=False)
    street_address_encrypted: Mapped[Optional[bytes]] = mapped_column(
        sa.LargeBinary, nullable=True
    )
    product_lines_of_interest: Mapped[list[str]] = mapped_column(
        sa.ARRAY(sa.Text), nullable=False
    )
    preferred_contact_method: Mapped[Optional[str]] = mapped_column(
        sa.Text, nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    lead_source: Mapped[str] = mapped_column(sa.Text, nullable=False)
    status: Mapped[str] = mapped_column(sa.Text, nullable=False)
    owner_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.Uuid, nullable=True
    )
    owner_username: Mapped[Optional[str]] = mapped_column(
        sa.Text, nullable=True
    )
    duplicate_of_lead_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.Uuid, nullable=True
    )
    duplicate_resolution: Mapped[Optional[str]] = mapped_column(
        sa.Text, nullable=True
    )
    # The converted-ref columns a freeze sets (migration 0015): the new Contact and
    # the one-or-more new Opportunities the lead became. Null until the lead is
    # `Converted`. `converted_opportunity_ids` is a `uuid[]` (the
    # `product_lines_of_interest` `text[]` precedent).
    converted_contact_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.Uuid, nullable=True
    )
    converted_opportunity_ids: Mapped[Optional[list[uuid.UUID]]] = mapped_column(
        sa.ARRAY(sa.Uuid), nullable=True
    )
    correlation_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, nullable=False
    )
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
