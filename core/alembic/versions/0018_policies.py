"""policies table per tenant (P2.3 policy issuance)

Stands up the per-tenant ``policies`` table the approval path issues into (P2.3
Epic 8). No application code lands here: this migration **owns** the table's DDL,
exactly like ``0017``'s applications table.

**The table (the ``0017`` per-tenant pattern).** Created in **every** tenant schema
named in ``app.tenancy.registry.TENANTS``, hand-written like ``0017``. It is a
schema-less ORM twin (the model resolves via ``search_path``) excluded from
``alembic check`` like ``leads`` / the applications table, so this migration owns its
DDL and the model mirrors its columns.

An approved application auto-issues one policy in the same transaction (D8): a
human-readable ``policy_number`` plus the carrier / product / coverage / premium
**copied from the application** (itself copied from the selected quote) and a
``status`` that lands ``'Active'``. ``opportunity_id`` / ``application_id`` /
``contact_id`` link it back; ``correlation_id`` / ``demo_session_id`` are the trace
columns; ``issued_at`` defaults to ``now()``.

**Grants (the ``0017`` three-way shape).** The tenant role gets full CRUD on its own
copy (the approve action writes as the tenant role); ``platform_reader`` gets SELECT;
``demo_purge`` gets SELECT + DELETE for the purge sweep.

Every identifier is interpolated only from the registry, never from user input.

Revision ID: 0018_policies
Revises: 0017_applications
Create Date: 2026-06-26

"""
from typing import Sequence, Union

from alembic import op

from app.tenancy.registry import DEMO_PURGE_ROLE, PLATFORM_ROLE, TENANTS

# revision identifiers, used by Alembic.
revision: str = "0018_policies"
down_revision: Union[str, None] = "0017_applications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # For each tenant: create the policies table in its own schema, then apply the
    # three-way grant shape (tenant CRUD, platform_reader SELECT, demo_purge
    # SELECT+DELETE).
    for tenant in TENANTS:
        schema = tenant.schema_name

        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.policies (
                id uuid NOT NULL,
                opportunity_id uuid NOT NULL,
                application_id uuid NOT NULL,
                contact_id uuid NOT NULL,
                policy_number text NOT NULL,
                carrier text NOT NULL,
                product_label text NOT NULL,
                coverage_amount integer NOT NULL,
                premium_monthly integer NOT NULL,
                premium_annual integer NOT NULL,
                status text NOT NULL DEFAULT 'Active',
                correlation_id uuid NOT NULL,
                demo_session_id uuid,
                issued_at timestamptz NOT NULL DEFAULT now(),
                CONSTRAINT pk_policies PRIMARY KEY (id)
            )
            """
        )

        qualified_table = f"{schema}.policies"
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE "
            f"ON {qualified_table} TO {tenant.db_role}"
        )
        op.execute(f"GRANT SELECT ON {qualified_table} TO {PLATFORM_ROLE}")
        op.execute(f"GRANT SELECT, DELETE ON {qualified_table} TO {DEMO_PURGE_ROLE}")


def downgrade() -> None:
    # Reverse of upgrade, per schema: drop the table (its grants fall with it).
    for tenant in TENANTS:
        schema = tenant.schema_name
        op.execute(f"DROP TABLE IF EXISTS {schema}.policies")
