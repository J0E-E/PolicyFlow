"""lead-conversion tables per tenant + converted-ref columns on leads

Stands up the per-tenant tables a lead conversion (P2.1) writes into —
``households``, ``contacts``, ``opportunities``, ``tasks`` — and adds the two
converted-ref columns on ``leads`` that point at what a lead became. No
application code lands here: this migration is the converted-world *schema* every
later epic stands on (TDD §5.2).

**The four tables (the ``0009`` per-tenant pattern).** Each table is created in
**every** tenant schema named in ``app.tenancy.registry.TENANTS``, hand-written
exactly like ``0009``'s ``leads``. They are schema-less ORM twins (the models land
in Epic 2, resolved via ``search_path``) excluded from ``alembic check`` like
``leads`` / ``pii_demo``, so this migration **owns** their DDL.

- ``households`` — the account-like grouping a contact belongs to. No owner.
- ``contacts`` — the converted person. Plaintext, searchable ``first_name`` /
  ``last_name`` / ``zip_code`` / ``age_band``; the encrypted (``bytea``) PII blobs
  mirrored from the lead (email / phone / date of birth / optional street). **No**
  blind-index columns — contact dedup is out of scope.
- ``opportunities`` — one per confirmed product line. ``stage`` defaults to the
  literal ``'New'`` (no P2.2 state machine pulled forward); premium / close-date
  are nullable (P2.3 / P2.4 fill them).
- ``tasks`` — a polymorphic shell (``related_entity_type`` / ``related_entity_id``)
  carrying the lead's notes as a ``'note'`` task body; ``due_date`` / ``status``
  nullable (P2.4 fills them).

Every entity carries the conversion's ``correlation_id`` (the M2 event-trace
invariant) and the nullable ``demo_session_id`` the purge sweep keys on.

**Grants (the ``0009`` + ``0013`` shape).** Per table: each tenant role gets full
CRUD on its own copy; ``platform_reader`` gets SELECT; ``demo_purge`` gets
SELECT + DELETE (it already holds schema ``USAGE`` from ``0013``), so the P2.1
purge extension can sweep these tables without riding a request transaction.

**The ``leads`` ALTER.** Two nullable converted-ref columns —
``converted_contact_id uuid`` and ``converted_opportunity_ids uuid[]`` (the
``product_lines_of_interest`` ``text[]`` precedent) — that a freeze sets and the
masked read surfaces. ``leads`` is already excluded from ``alembic check``, so the
ALTER needs no model change to stay drift-clean.

Every identifier is interpolated only from the registry, never from user input, so
the migration and the registry can never disagree about which schema/role serves
which tenant. Live apply against real Postgres is exercised in this epic's
substrate test (``core/tests/test_lead_conversion_migration.py``).

Revision ID: 0015_lead_conversion
Revises: 0014_timeline_outbox_grant
Create Date: 2026-06-25

"""
from typing import Sequence, Union

from alembic import op

from app.tenancy.registry import DEMO_PURGE_ROLE, PLATFORM_ROLE, TENANTS

# revision identifiers, used by Alembic.
revision: str = "0015_lead_conversion"
down_revision: Union[str, None] = "0014_timeline_outbox_grant"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The four new tables, in creation order. No cross-table foreign keys (the schema
# boundary is the isolation layer, like 0009's leads), so order is cosmetic.
NEW_TABLES: tuple[str, ...] = ("households", "contacts", "opportunities", "tasks")


def upgrade() -> None:
    # For each tenant: create the four tables in its own schema, then apply the
    # three-way grant shape (tenant CRUD, platform_reader SELECT, demo_purge
    # SELECT+DELETE) to each, then add the two converted-ref columns to leads.
    for tenant in TENANTS:
        schema = tenant.schema_name

        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.households (
                id uuid NOT NULL,
                name text NOT NULL,
                correlation_id uuid NOT NULL,
                demo_session_id uuid,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now(),
                CONSTRAINT pk_households PRIMARY KEY (id)
            )
            """
        )

        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.contacts (
                id uuid NOT NULL,
                household_id uuid NOT NULL,
                first_name text NOT NULL,
                last_name text NOT NULL,
                zip_code text NOT NULL,
                age_band text NOT NULL,
                email_encrypted bytea NOT NULL,
                phone_encrypted bytea NOT NULL,
                date_of_birth_encrypted bytea NOT NULL,
                street_address_encrypted bytea,
                lead_source text NOT NULL,
                owner_user_id uuid,
                owner_username text,
                source_lead_id uuid NOT NULL,
                correlation_id uuid NOT NULL,
                demo_session_id uuid,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now(),
                CONSTRAINT pk_contacts PRIMARY KEY (id)
            )
            """
        )

        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.opportunities (
                id uuid NOT NULL,
                contact_id uuid NOT NULL,
                household_id uuid NOT NULL,
                product_line text NOT NULL,
                stage text NOT NULL DEFAULT 'New',
                owner_user_id uuid,
                owner_username text,
                estimated_annual_premium numeric,
                target_close_date date,
                origin text NOT NULL,
                source_lead_id uuid NOT NULL,
                correlation_id uuid NOT NULL,
                demo_session_id uuid,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now(),
                CONSTRAINT pk_opportunities PRIMARY KEY (id)
            )
            """
        )

        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.tasks (
                id uuid NOT NULL,
                related_entity_type text NOT NULL,
                related_entity_id uuid NOT NULL,
                task_type text NOT NULL,
                body text NOT NULL,
                assignee_user_id uuid,
                assignee_username text,
                due_date timestamptz,
                status text,
                correlation_id uuid NOT NULL,
                demo_session_id uuid,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now(),
                CONSTRAINT pk_tasks PRIMARY KEY (id)
            )
            """
        )

        # The three-way grant shape per table (0009's tenant CRUD + platform_reader
        # SELECT, plus 0013's demo_purge SELECT+DELETE for the purge sweep).
        for table in NEW_TABLES:
            qualified_table = f"{schema}.{table}"
            op.execute(
                f"GRANT SELECT, INSERT, UPDATE, DELETE "
                f"ON {qualified_table} TO {tenant.db_role}"
            )
            op.execute(
                f"GRANT SELECT ON {qualified_table} TO {PLATFORM_ROLE}"
            )
            op.execute(
                f"GRANT SELECT, DELETE ON {qualified_table} TO {DEMO_PURGE_ROLE}"
            )

        # The two converted-ref columns a freeze sets on the held lead.
        op.execute(
            f"ALTER TABLE {schema}.leads "
            f"ADD COLUMN IF NOT EXISTS converted_contact_id uuid"
        )
        op.execute(
            f"ALTER TABLE {schema}.leads "
            f"ADD COLUMN IF NOT EXISTS converted_opportunity_ids uuid[]"
        )


def downgrade() -> None:
    # Reverse of upgrade, per schema: drop the leads columns, then drop the four
    # tables (their grants fall with them). Ordered and reversible.
    for tenant in TENANTS:
        schema = tenant.schema_name

        op.execute(
            f"ALTER TABLE {schema}.leads "
            f"DROP COLUMN IF EXISTS converted_opportunity_ids"
        )
        op.execute(
            f"ALTER TABLE {schema}.leads "
            f"DROP COLUMN IF EXISTS converted_contact_id"
        )

        for table in reversed(NEW_TABLES):
            op.execute(f"DROP TABLE IF EXISTS {schema}.{table}")
