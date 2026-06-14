"""The `PiiDemoRecord` ORM model — the phase's PII demonstrator entity.

Like `TenantSettings` (and unlike the platform-bound `Tenant` /
`TenantDataKey`), this model is **deliberately schema-less**: it names the table
``pii_demo`` but does not bind it to a schema. Postgres therefore resolves it
against whatever ``search_path`` is active, so the same one class serves every
tenant — the per-request scoping dependency just points ``search_path`` at the
right schema, and the table physically exists only inside each tenant schema
(created per-tenant by migration ``0006``).

The record carries every distinct PII field treatment in one place: a plaintext
``display_name`` and ``age_band``, the encrypted (``bytea``) field blobs, the two
blind-index (``bytea``) columns used for exact-match lookup without decryption,
and the never-revealable ``mock_medicare_id_encrypted``. It is the concrete target
the rest of the phase exercises — encryption, blind indexing, masking, and
age-band derivation.

The two blind-index indexes (``ix_pii_demo_email_blind_index`` /
``ix_pii_demo_phone_blind_index``) are **owned by migration 0006**, not declared
on this model: because the table is schema-less it is excluded from
``alembic check`` (see ``core/alembic/env.py`` ``include_object``), so declaring
the indexes here would never be reconciled against the live database anyway.
"""

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class PiiDemoRecord(Base):
    """A single PII demonstrator record, resolved via `search_path`."""

    __tablename__ = "pii_demo"
    # No schema binding (like `TenantSettings`, unlike `Tenant`): the table is
    # resolved against the active `search_path`. The primary key is a surrogate
    # uuid generated app-side via `default=uuid.uuid4` (matching `Tenant`); the
    # migration column carries no DB-side default. The PK name `pk_pii_demo`
    # comes for free from the `pk` naming convention in `app.db`.

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    display_name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    email_encrypted: Mapped[bytes] = mapped_column(
        sa.LargeBinary, nullable=False
    )
    email_blind_index: Mapped[bytes] = mapped_column(
        sa.LargeBinary, nullable=False
    )
    phone_encrypted: Mapped[Optional[bytes]] = mapped_column(
        sa.LargeBinary, nullable=True
    )
    phone_blind_index: Mapped[Optional[bytes]] = mapped_column(
        sa.LargeBinary, nullable=True
    )
    date_of_birth_encrypted: Mapped[Optional[bytes]] = mapped_column(
        sa.LargeBinary, nullable=True
    )
    age_band: Mapped[str] = mapped_column(sa.Text, nullable=False)
    mock_medicare_id_encrypted: Mapped[Optional[bytes]] = mapped_column(
        sa.LargeBinary, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
