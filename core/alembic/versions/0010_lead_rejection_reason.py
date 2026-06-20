"""rejection_reason column on the per-tenant leads table

Adds a nullable ``rejection_reason text`` column to the ``leads`` table inside
**each** tenant schema named in ``app.tenancy.registry.TENANTS`` (the per-tenant
pattern ``0009`` established). The column captures the optional free-text reason an
agent may supply when rejecting a `Working` lead (TDD §5.4, Epic 13). It is kept
**separate** from the intake ``notes`` column: ``notes`` is lead context captured at
intake, ``rejection_reason`` is the rejection rationale captured at the terminal
move. The masked read surfaces it as-is (like ``notes``); the ``lead.rejected``
event never carries it (its payload stays ``entity_id`` + ``reason_kind``).

Nullable so a reason-less reject is legal and so the column can be added to the
existing populated table without a backfill. The schema-less ``Lead`` ORM twin gets
the matching field; because that model is excluded from ``alembic check`` (the
``PiiDemoRecord`` precedent), this migration **owns** the column on the live table.

Every identifier is interpolated only from the registry, never from user input,
matching ``0009``. The downgrade drops the column per schema, so the migration
reverses cleanly (exercised by the round-trip test).

Revision ID: 0010_lead_rejection_reason
Revises: 0009_leads
Create Date: 2026-06-19

"""
from typing import Sequence, Union

from alembic import op

from app.tenancy.registry import TENANTS

# revision identifiers, used by Alembic.
revision: str = "0010_lead_rejection_reason"
down_revision: Union[str, None] = "0009_leads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add the nullable rejection_reason column to each tenant's leads table.
    for tenant in TENANTS:
        op.execute(
            f"ALTER TABLE {tenant.schema_name}.leads "
            f"ADD COLUMN rejection_reason text"
        )


def downgrade() -> None:
    # Drop the column per schema; reverses the upgrade exactly.
    for tenant in TENANTS:
        op.execute(
            f"ALTER TABLE {tenant.schema_name}.leads "
            f"DROP COLUMN rejection_reason"
        )
