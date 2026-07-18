"""renewal / cross-sell columns + one-renewal-per-policy-cycle index (P2.4)

Additive, forward-only schema for the renewals & cross-sell feature. Two nullable
columns land on each tenant's ``opportunities`` table and ``source_lead_id`` is
relaxed to nullable, so a renewal or cross-sell opportunity — which is born from a
policy, not a lead — can be created without a source lead (TDD §5.2, D3/D4):

- ``source_policy_id uuid`` — the policy a renewal / cross-sell opportunity springs
  from (null for the conversion-born opportunities that already exist).
- ``renewal_cycle text`` — the renewal cycle key (e.g. the AEP year), null unless
  the opportunity is a renewal.
- ``source_lead_id`` — ``DROP NOT NULL``: conversion opportunities still set it,
  renewal / cross-sell ones leave it null.

Plus a **partial unique index** guarding the idempotency rule — at most one renewal
opportunity per policy, per cycle, per demo session (ADR 0001/0004):
``(source_policy_id, renewal_cycle, demo_session_id) WHERE origin = 'renewal'``.
Only renewal rows are constrained; conversion / cross-sell rows are unbound.

**Per-tenant, like ``0019`` / ``0015``.** Every statement runs once per tenant
schema named in ``app.tenancy.registry.TENANTS``, interpolating only
``tenant.schema_name`` (never user input), with raw idempotent ``op.execute`` DDL
so the migration and the registry can never disagree about which schema serves
which tenant.

**No enum / CHECK DDL.** ``origin`` gains ``'renewal'`` / ``'cross_sell'`` and
``policies.status`` gains ``'Renewal Due'``, but both are plain ``text`` with no
enum or CHECK constraint, so the new values are simply now-valid — nothing to alter
(TDD D3/D5). Adding nullable columns inherits the table's existing grants (``0015``
already granted tenant CRUD / reader SELECT / purge SELECT+DELETE), so no new GRANT
is needed. ``opportunities`` is excluded from ``alembic check``, so the migration
owns its DDL and needs no model change to stay drift-clean (the model mirrors it in
this same epic for parity).

Revision ID: 0020_renewal_cross_sell_schema
Revises: 0019_one_active_index
Create Date: 2026-07-18

"""
from typing import Sequence, Union

from alembic import op

from app.tenancy.registry import TENANTS

# revision identifiers, used by Alembic. Kept ≤ 32 chars — Alembic's
# `alembic_version.version_num` column is `varchar(32)`.
revision: str = "0020_renewal_cross_sell_schema"
down_revision: Union[str, None] = "0019_one_active_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "ux_opportunities_one_renewal_per_policy_cycle"


def upgrade() -> None:
    # Per tenant: add the two nullable renewal / cross-sell columns, relax
    # source_lead_id to nullable, then guard one renewal per policy / cycle /
    # session with a partial unique index over origin = 'renewal' rows only.
    for tenant in TENANTS:
        schema = tenant.schema_name
        op.execute(
            f"ALTER TABLE {schema}.opportunities "
            f"ADD COLUMN IF NOT EXISTS source_policy_id uuid"
        )
        op.execute(
            f"ALTER TABLE {schema}.opportunities "
            f"ADD COLUMN IF NOT EXISTS renewal_cycle text"
        )
        op.execute(
            f"ALTER TABLE {schema}.opportunities "
            f"ALTER COLUMN source_lead_id DROP NOT NULL"
        )
        op.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {INDEX_NAME} "
            f"ON {schema}.opportunities "
            "(source_policy_id, renewal_cycle, demo_session_id) "
            "WHERE origin = 'renewal'"
        )


def downgrade() -> None:
    # Reverse of upgrade, per schema: drop the index, restore the NOT NULL on
    # source_lead_id, then drop the two columns. Reversed order, all reversible.
    for tenant in TENANTS:
        schema = tenant.schema_name
        op.execute(f"DROP INDEX IF EXISTS {schema}.{INDEX_NAME}")
        op.execute(
            f"ALTER TABLE {schema}.opportunities "
            f"ALTER COLUMN source_lead_id SET NOT NULL"
        )
        op.execute(
            f"ALTER TABLE {schema}.opportunities "
            f"DROP COLUMN IF EXISTS renewal_cycle"
        )
        op.execute(
            f"ALTER TABLE {schema}.opportunities "
            f"DROP COLUMN IF EXISTS source_policy_id"
        )
