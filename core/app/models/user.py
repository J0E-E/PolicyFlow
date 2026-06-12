"""The `Role` enum and the `User` ORM model.

`Role` is the single source of truth for who a user is in the system; later epics
(the RBAC matrix, the auth dependencies) import it from here. `User` lives in the
shared `platform` schema and carries the membership pointer (`tenant_id`) plus the
credential and authorization fields the auth flow leans on.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class Role(StrEnum):
    """Who a user is, and what the RBAC matrix authorizes them to do.

    The string values are the lowercase labels stored in the `platform.user_role`
    Postgres enum (see the `values_callable` on the `User.role` column). This is
    the single definition of the role set — later epics import `Role` from here
    rather than redeclaring it.
    """

    AGENT = "agent"
    TENANT_ADMIN = "tenant_admin"
    READ_ONLY = "read_only"
    PLATFORM_ADMIN = "platform_admin"


class User(Base):
    """A person who can sign in, in the shared `platform` schema.

    `tenant_id` is nullable because the platform administrator belongs to no
    single tenant; the `platform_admin_tenantless` check constraint enforces the
    matching rule that a platform admin (and only a platform admin) has no tenant.
    """

    __tablename__ = "users"
    __table_args__ = (
        sa.CheckConstraint(
            "(role = 'platform_admin') = (tenant_id IS NULL)",
            name="platform_admin_tenantless",
        ),
        {"schema": "platform"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.Uuid,
        sa.ForeignKey("platform.tenants.id"),
        nullable=True,
    )
    username: Mapped[str] = mapped_column(sa.Text, nullable=False, unique=True)
    email: Mapped[str] = mapped_column(sa.Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    role: Mapped[Role] = mapped_column(
        sa.Enum(
            Role,
            name="user_role",
            schema="platform",
            values_callable=lambda enum_class: [
                member.value for member in enum_class
            ],
        ),
        nullable=False,
    )
    # Future OIDC seam: the external identity provider's subject, when a user
    # signs in through an external identity rather than a local password.
    external_identity: Mapped[Optional[str]] = mapped_column(
        sa.Text, nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.true()
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
