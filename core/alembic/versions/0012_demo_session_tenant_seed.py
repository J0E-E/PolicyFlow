"""platform demo_session_tenant_seed ledger table

Creates ``platform.demo_session_tenant_seed`` — the per-(demo session, tenant)
idempotency ledger that `ensure_session_leads` writes after it instantiates a
visitor's private New queue from the canonical templates. A row's presence is the
**only** "already seeded" signal: the instantiation is a no-op when a row for
``(demo_session_id, tenant_slug)`` exists, and a second visit (a different
``demo_session_id``) seeds its own copy even though the dup-bait shares an email.
This is the hand-written twin of the ``DemoSessionTenantSeed`` ORM model in
``app.models``; the two must stay in lock-step, and the constraint name below
matches the naming convention pinned on ``Base.metadata`` so ``alembic check``
sees no phantom drift (the ``0002`` / ``0011`` precedent).

**Write grant.** `ensure_session_leads` runs inside the existing tenant-scoped
transaction (under ``SET LOCAL ROLE tenant_<x>`` via ``get_public_tenant_db``) so
the ledger write rides the same transaction as the session-tagged lead inserts.
That tenant role can already SELECT ``platform.demo_sessions`` (the ``0011`` read
grant) — here each tenant role additionally gets ``SELECT`` + ``INSERT`` on the
ledger so the guard read and the marker write both succeed under that role. The
downgrade revokes them symmetrically; the schema ``USAGE`` granted by ``0011``
for those same roles is left alone (``0011`` owns it).

Revision ID: 0012_demo_session_tenant_seed
Revises: 0011_demo_sessions
Create Date: 2026-06-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.tenancy.registry import TENANTS

# revision identifiers, used by Alembic.
revision: str = "0012_demo_session_tenant_seed"
down_revision: Union[str, None] = "0011_demo_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The per-tenant roles that write the ledger from inside the scoped instantiation
# transaction. Only the tenant roles run `ensure_session_leads`; the cross-tenant
# `platform_reader` never writes a lead, so it is not granted here.
SEED_LEDGER_WRITER_ROLES = [tenant.db_role for tenant in TENANTS]


def upgrade() -> None:
    op.create_table(
        "demo_session_tenant_seed",
        sa.Column("demo_session_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_slug", sa.Text(), nullable=False),
        sa.Column(
            "seeded_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "demo_session_id",
            "tenant_slug",
            name="pk_demo_session_tenant_seed",
        ),
        schema="platform",
    )

    # Let each scoped tenant request read the guard row and write the marker from
    # inside the same transaction that inserts the session-tagged leads. SELECT +
    # INSERT only (the ledger is append-once; nothing updates or deletes it here —
    # the purge engine's DELETE grant lands with the demo_purge role in Epic 9).
    for role in SEED_LEDGER_WRITER_ROLES:
        op.execute(
            f"GRANT SELECT, INSERT ON platform.demo_session_tenant_seed TO {role}"
        )


def downgrade() -> None:
    # Revoke the ledger SELECT + INSERT for every writer, symmetric with upgrade.
    # The schema USAGE these roles hold is owned by 0011, so it is left untouched.
    for role in SEED_LEDGER_WRITER_ROLES:
        op.execute(
            "REVOKE SELECT, INSERT ON platform.demo_session_tenant_seed "
            f"FROM {role}"
        )

    op.drop_table("demo_session_tenant_seed", schema="platform")
