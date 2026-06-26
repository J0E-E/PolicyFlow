"""quote-request + quote tables per tenant (P2.3 the carrier-quote round-trip)

Stands up the two per-tenant tables the carrier-quote round-trip (P2.3 Epic 3)
writes into — ``quote_requests`` (the pollable ``pending`` → ``completed``
lifecycle) and ``quotes`` (one row per returned option). No application code lands
here: this migration **owns** their DDL, exactly like ``0015``'s conversion tables.

**The two tables (the ``0015`` per-tenant pattern).** Each is created in **every**
tenant schema named in ``app.tenancy.registry.TENANTS``, hand-written like ``0015``.
They are schema-less ORM twins (the models resolve via ``search_path``) excluded
from ``alembic check`` like ``leads`` / the conversion tables, so this migration
owns their DDL and the models mirror their columns.

- ``quote_requests`` — the round-trip the agent polls: ``status`` defaults to the
  literal ``'pending'`` and the ``carrier.quote`` consumer flips it to
  ``'completed'`` when the options are written. Carries the ``opportunity_id`` it
  was raised for, the ``product_line`` the consumer reads its option templates by,
  and the ``correlation_id`` / ``demo_session_id`` trace columns.
- ``quotes`` — one row per returned option (carrier / product label / coverage /
  monthly + annual premium), tagged with both its ``quote_request_id`` and the
  ``opportunity_id`` so a read can attach the options to either.

**Grants (the ``0015`` three-way shape).** Per table: each tenant role gets full
CRUD on its own copy (the consumer writes as the tenant role, D2b);
``platform_reader`` gets SELECT; ``demo_purge`` gets SELECT + DELETE (it already
holds schema ``USAGE`` from ``0013``) so the P2.3 purge extension can sweep these
without riding a request transaction.

Every identifier is interpolated only from the registry, never from user input, so
the migration and the registry can never disagree about which schema/role serves
which tenant.

Revision ID: 0016_quotes
Revises: 0015_lead_conversion
Create Date: 2026-06-26

"""
from typing import Sequence, Union

from alembic import op

from app.tenancy.registry import DEMO_PURGE_ROLE, PLATFORM_ROLE, TENANTS

# revision identifiers, used by Alembic.
revision: str = "0016_quotes"
down_revision: Union[str, None] = "0015_lead_conversion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The two new tables, in creation order. No cross-table foreign keys (the schema
# boundary is the isolation layer, like 0015), so order is cosmetic.
NEW_TABLES: tuple[str, ...] = ("quote_requests", "quotes")


def upgrade() -> None:
    # For each tenant: create the two tables in its own schema, then apply the
    # three-way grant shape (tenant CRUD, platform_reader SELECT, demo_purge
    # SELECT+DELETE) to each.
    for tenant in TENANTS:
        schema = tenant.schema_name

        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.quote_requests (
                id uuid NOT NULL,
                opportunity_id uuid NOT NULL,
                status text NOT NULL DEFAULT 'pending',
                product_line text NOT NULL,
                correlation_id uuid NOT NULL,
                demo_session_id uuid,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now(),
                CONSTRAINT pk_quote_requests PRIMARY KEY (id)
            )
            """
        )

        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.quotes (
                id uuid NOT NULL,
                quote_request_id uuid NOT NULL,
                opportunity_id uuid NOT NULL,
                carrier text NOT NULL,
                product_label text NOT NULL,
                coverage_amount integer NOT NULL,
                premium_monthly integer NOT NULL,
                premium_annual integer NOT NULL,
                correlation_id uuid NOT NULL,
                demo_session_id uuid,
                created_at timestamptz NOT NULL DEFAULT now(),
                CONSTRAINT pk_quotes PRIMARY KEY (id)
            )
            """
        )

        # The three-way grant shape per table (0015's tenant CRUD + platform_reader
        # SELECT, plus 0013's demo_purge SELECT+DELETE for the purge sweep).
        for table in NEW_TABLES:
            qualified_table = f"{schema}.{table}"
            op.execute(
                f"GRANT SELECT, INSERT, UPDATE, DELETE "
                f"ON {qualified_table} TO {tenant.db_role}"
            )
            op.execute(f"GRANT SELECT ON {qualified_table} TO {PLATFORM_ROLE}")
            op.execute(
                f"GRANT SELECT, DELETE ON {qualified_table} TO {DEMO_PURGE_ROLE}"
            )


def downgrade() -> None:
    # Reverse of upgrade, per schema: drop the two tables (their grants fall with
    # them). Ordered and reversible.
    for tenant in TENANTS:
        schema = tenant.schema_name
        for table in reversed(NEW_TABLES):
            op.execute(f"DROP TABLE IF EXISTS {schema}.{table}")
