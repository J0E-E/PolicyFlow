"""applications table per tenant (P2.3 quote selection → Application)

Stands up the per-tenant ``applications`` table the quote-selection action (P2.3
Epic 5) writes into and the later epics fill out. No application code lands here:
this migration **owns** the table's DDL, exactly like ``0016``'s quote tables.

**The table (the ``0016`` per-tenant pattern).** Created in **every** tenant schema
named in ``app.tenancy.registry.TENANTS``, hand-written like ``0016``. It is a
schema-less ORM twin (the model resolves via ``search_path``) excluded from
``alembic check`` like ``leads`` / the quote tables, so this migration owns its DDL
and the model mirrors its columns.

The **full** D5 column set is created here even though Epic 5 only writes a subset
(`status='Draft'`, the carrier/product/coverage/premium fields copied from the
selected quote, the opportunity/contact/quote references, and the trace columns) —
the product-step columns (`beneficiary` / `health_answers`), the decision columns
(`decision` / `decided_at`), the Tenant-1 `medicare_id_encrypted`, and the
`superseded_by_application_id` link are created now so Epics 6 / 7 / 10 / 11
**populate** them rather than each shipping its own ``ALTER``. The **partial unique
index** that backstops "one active application per opportunity" (C5) is **not** here
— it is Epic 10's deliverable, added when the supersession rule lands.

**Grants (the ``0016`` three-way shape).** The tenant role gets full CRUD on its own
copy (the select/submit actions write as the tenant role); ``platform_reader`` gets
SELECT; ``demo_purge`` gets SELECT + DELETE for the purge sweep.

Every identifier is interpolated only from the registry, never from user input.

Revision ID: 0017_applications
Revises: 0016_quotes
Create Date: 2026-06-26

"""
from typing import Sequence, Union

from alembic import op

from app.tenancy.registry import DEMO_PURGE_ROLE, PLATFORM_ROLE, TENANTS

# revision identifiers, used by Alembic.
revision: str = "0017_applications"
down_revision: Union[str, None] = "0016_quotes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # For each tenant: create the applications table in its own schema, then apply
    # the three-way grant shape (tenant CRUD, platform_reader SELECT, demo_purge
    # SELECT+DELETE).
    for tenant in TENANTS:
        schema = tenant.schema_name

        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.applications (
                id uuid NOT NULL,
                opportunity_id uuid NOT NULL,
                contact_id uuid NOT NULL,
                product_line text NOT NULL,
                selected_quote_id uuid NOT NULL,
                status text NOT NULL DEFAULT 'Draft',
                carrier text NOT NULL,
                product_label text NOT NULL,
                coverage_amount integer NOT NULL,
                premium_monthly integer NOT NULL,
                premium_annual integer NOT NULL,
                beneficiary jsonb,
                health_answers jsonb,
                medicare_id_encrypted bytea,
                decision text,
                decided_at timestamptz,
                superseded_by_application_id uuid,
                correlation_id uuid NOT NULL,
                demo_session_id uuid,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now(),
                CONSTRAINT pk_applications PRIMARY KEY (id)
            )
            """
        )

        qualified_table = f"{schema}.applications"
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
        op.execute(f"DROP TABLE IF EXISTS {schema}.applications")
