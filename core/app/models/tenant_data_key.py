"""The `TenantDataKey` ORM model — one wrapped root key per tenant.

Like `Tenant` (and unlike the schema-less `TenantSettings`), this model is bound
to the shared ``platform`` schema: the wrapped-key store is platform-level data,
held in one place rather than copied per tenant schema. Each row holds one
tenant's master-key-wrapped root key, keyed by the ``platform.tenants`` id it
belongs to.

There is deliberately **no** foreign key on ``tenant_id`` (matching migration
``0005`` and the TDD §5 column list); the Epic 6 seed guards integrity by
inserting only registry tenant ids. The columns mirror the migration exactly so
``alembic check`` sees no drift, and the primary key name ``pk_tenant_data_keys``
comes for free from the ``pk`` naming convention in ``app.db``.

Reading this table is restricted to the default login role by migration ``0005``:
no tenant role and no ``platform_reader`` may ever read key material.
"""

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class TenantDataKey(Base):
    """A single tenant's master-key-wrapped root key in the `platform` schema."""

    __tablename__ = "tenant_data_keys"
    __table_args__ = {"schema": "platform"}

    # The platform.tenants id this key belongs to. No default (it is the supplied
    # tenant id, like `TenantSettings.tenant_id`); doubles as the primary key.
    tenant_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True)
    wrapped_root_key: Mapped[bytes] = mapped_column(
        sa.LargeBinary, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
