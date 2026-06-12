"""platform identity schema

Creates the shared ``platform`` schema and its first three tables — ``tenants``,
``users``, and ``auth_sessions`` — plus the ``platform.user_role`` enum. This is
the hand-written twin of the ORM models in ``app.models``: the two must stay in
lock-step, and the constraint names below match the naming convention pinned on
``Base.metadata`` so ``alembic check`` sees no phantom drift.

Live apply against real Postgres is exercised in Epic 11's testcontainers
substrate; this revision only defines the upgrade/downgrade.

Revision ID: 0002_platform_identity
Revises: 0001_empty_baseline
Create Date: 2026-06-12

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_platform_identity"
down_revision: Union[str, None] = "0001_empty_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The Postgres enum backing `users.role`. The labels are the lowercase `Role`
# values, matching the ORM model's `values_callable`. `create_type=False` keeps
# the column definitions from trying to create the type a second time — it is
# created once, explicitly, in `upgrade()`.
user_role_enum = sa.Enum(
    "agent",
    "tenant_admin",
    "read_only",
    "platform_admin",
    name="user_role",
    schema="platform",
    create_type=False,
)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS platform")

    user_role_enum.create(op.get_bind())

    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tenants"),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
        schema="platform",
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", user_role_enum, nullable=False),
        sa.Column("external_identity", sa.Text(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["platform.tenants.id"],
            name="fk_users_tenant_id_tenants",
        ),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.CheckConstraint(
            "(role = 'platform_admin') = (tenant_id IS NULL)",
            name="ck_users_platform_admin_tenantless",
        ),
        schema="platform",
    )

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_auth_sessions"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["platform.users.id"],
            name="fk_auth_sessions_user_id_users",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "token_hash", name="uq_auth_sessions_token_hash"
        ),
        schema="platform",
    )


def downgrade() -> None:
    op.drop_table("auth_sessions", schema="platform")
    op.drop_table("users", schema="platform")
    op.drop_table("tenants", schema="platform")

    user_role_enum.drop(op.get_bind())

    op.execute("DROP SCHEMA IF EXISTS platform")
