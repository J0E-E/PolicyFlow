"""one-active-application partial unique index (P2.3 decline → supersession)

Backstops the "one active application per opportunity" rule (TDD C5) with a
**partial unique index** on each tenant's ``applications`` table:
``(opportunity_id) WHERE status IN ('Draft', 'Submitted')``. Only the *active*
statuses are constrained, so an opportunity may accumulate any number of
``Declined`` / ``Superseded`` history rows but never two live applications at once —
the DB guarantee behind the service-level check the select action makes.

Created in **every** tenant schema named in ``app.tenancy.registry.TENANTS``,
hand-written like the table's ``0017`` DDL. The applications table is already
excluded from ``alembic check``, so the index needs no model change to stay
drift-clean.

Revision ID: 0019_one_active_index
Revises: 0018_policies
Create Date: 2026-06-26

"""
from typing import Sequence, Union

from alembic import op

from app.tenancy.registry import TENANTS

# revision identifiers, used by Alembic. Kept ≤ 32 chars — Alembic's
# `alembic_version.version_num` column is `varchar(32)`.
revision: str = "0019_one_active_index"
down_revision: Union[str, None] = "0018_policies"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "ux_applications_one_active_per_opportunity"


def upgrade() -> None:
    # One partial unique index per tenant: at most one active (Draft / Submitted)
    # application per opportunity; history rows (Declined / Superseded) are unbound.
    for tenant in TENANTS:
        schema = tenant.schema_name
        op.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {INDEX_NAME} "
            f"ON {schema}.applications (opportunity_id) "
            "WHERE status IN ('Draft', 'Submitted')"
        )


def downgrade() -> None:
    for tenant in TENANTS:
        schema = tenant.schema_name
        op.execute(f"DROP INDEX IF EXISTS {schema}.{INDEX_NAME}")
