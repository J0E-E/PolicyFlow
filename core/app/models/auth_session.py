"""The `AuthSession` ORM model — one row per server-side login session.

A login issues an opaque token to the client but stores only its SHA-256 hash
here (`token_hash`), so the raw token never lives in the database. Resolving a
request looks the session up by hash; logout stamps `revoked_at`; expired or
revoked sessions stop being valid. Lives in the shared `platform` schema.
"""

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class AuthSession(Base):
    """A server-side session, keyed by the SHA-256 hash of its opaque token."""

    __tablename__ = "auth_sessions"
    __table_args__ = {"schema": "platform"}

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        sa.ForeignKey("platform.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(sa.Text, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        sa.TIMESTAMP(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
