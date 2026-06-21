"""platform demo_sessions table

Creates ``platform.demo_sessions`` — the server-side record of one demo *visit*,
the hand-written twin of the ``DemoSession`` ORM model in ``app.models``. The two
must stay in lock-step, and the constraint name below matches the naming
convention pinned on ``Base.metadata`` so ``alembic check`` sees no phantom drift
(the ``0002`` precedent).

This revision creates **only the table** plus the read grants the tracer needs.
The per-session seed ledger (``platform.demo_session_tenant_seed``), the
``demo_purge`` role + cross-schema DELETE grants, and the per-tenant
``leads.demo_session_id`` index described in TDD §5.8 land in their owning epics
(7 and 9), so the migration that carries them is theirs, not this one.

**Read grants.** A tenant-scoped request (under ``SET LOCAL ROLE tenant_<x>``)
must resolve the caller's demo session from the cookie to tag a created lead — so
each tenant role, and the cross-tenant ``platform_reader``, gets ``USAGE`` on the
``platform`` schema and ``SELECT`` on ``demo_sessions``. The visitor's own session
row is the only thing read; this is a narrow read grant, not the privileged
``demo_purge`` DELETE path (Epic 9). The roles already exist (``0003``); identifiers
come only from the registry, never user input, matching the ``0003`` precedent.

Revision ID: 0011_demo_sessions
Revises: 0010_lead_rejection_reason
Create Date: 2026-06-20

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.tenancy.registry import PLATFORM_ROLE, TENANTS

# revision identifiers, used by Alembic.
revision: str = "0011_demo_sessions"
down_revision: Union[str, None] = "0010_lead_rejection_reason"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The roles that may SELECT a demo session from inside a scoped request: every
# per-tenant role (the agent/public intake tag path) plus the cross-tenant reader.
DEMO_SESSION_READER_ROLES = [tenant.db_role for tenant in TENANTS] + [PLATFORM_ROLE]


def upgrade() -> None:
    op.create_table(
        "demo_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_tenant_slug", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_demo_sessions"),
        schema="platform",
    )

    # Let a scoped tenant request (and the cross-tenant reader) read the visitor's
    # own demo session to tag a created lead. USAGE on the schema + SELECT on this
    # one table — nothing wider.
    for role in DEMO_SESSION_READER_ROLES:
        op.execute(f"GRANT USAGE ON SCHEMA platform TO {role}")
        op.execute(
            f"GRANT SELECT ON platform.demo_sessions TO {role}"
        )


def downgrade() -> None:
    # Revoke the table SELECT for every reader. `platform_reader` keeps its schema
    # USAGE (granted by 0003, owned there); revoke the USAGE this revision added for
    # the per-tenant roles so the downgrade is symmetric and leaves no stray grant.
    for role in DEMO_SESSION_READER_ROLES:
        op.execute(
            f"REVOKE SELECT ON platform.demo_sessions FROM {role}"
        )
    for tenant in TENANTS:
        op.execute(f"REVOKE USAGE ON SCHEMA platform FROM {tenant.db_role}")

    op.drop_table("demo_sessions", schema="platform")
