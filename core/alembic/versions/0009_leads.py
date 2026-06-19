"""leads table per tenant schema, with grants and blind indexes

Creates the P1.7 lead entity: a ``leads`` table inside **each** tenant schema
named in ``app.tenancy.registry.TENANTS`` (the ``0006`` per-tenant pattern). The
table carries the full lead shape (TDD §5.2) — plaintext, searchable names and
zip; the encrypted (``bytea``) PII blobs (email, phone, date of birth, optional
street address); the two blind-index (``bytea``) columns for exact-match duplicate
detection without decryption; the derived plaintext age band; the
``product_lines_of_interest`` key array; the ``lead_source`` / ``status`` **text**
columns (plain text validated app-side by ``StrEnum``, **not** PG ``ENUM`` — the
P1.1 lesson); the owner and duplicate-linkage bookkeeping; and the
``correlation_id`` / ``demo_session_id`` event-trace columns.

Each blind-index column gets a **non-unique** index
(``ix_leads_email_blind_index`` / ``ix_leads_phone_blind_index``, following the
``ix_`` naming convention in ``app.db``) so the Epic 6 duplicate matcher can match
by fingerprint cheaply.

Grants mirror ``0006_pii_demo`` exactly: each tenant role gets full CRUD on its
own copy and ``platform_reader`` gets SELECT, so the schema boundary stays the
isolation layer. (Unlike ``0008``'s event-bus stores, the lead table needs no
tightening REVOKEs — the request session does every read and write.) Every
identifier is interpolated only from the registry, never from user input, matching
0006.

The model is a schema-less ORM twin (``Lead``), resolved via ``search_path`` and
excluded from ``alembic check`` (the ``PiiDemoRecord`` precedent), so this
migration **owns** both blind-index indexes.

Live apply against real Postgres is exercised in this epic's substrate test
(``core/tests/test_leads_migration.py``).

Revision ID: 0009_leads
Revises: 0008_event_bus
Create Date: 2026-06-19

"""
from typing import Sequence, Union

from alembic import op

from app.tenancy.registry import PLATFORM_ROLE, TENANTS

# revision identifiers, used by Alembic.
revision: str = "0009_leads"
down_revision: Union[str, None] = "0008_event_bus"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # For each tenant: create the leads table in its own schema, its two
    # blind-index indexes, then the explicit per-tenant CRUD grant and the
    # platform read-role SELECT grant (the 0006 grant shape).
    for tenant in TENANTS:
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {tenant.schema_name}.leads (
                id uuid NOT NULL,
                first_name text NOT NULL,
                last_name text NOT NULL,
                email_encrypted bytea NOT NULL,
                email_blind_index bytea NOT NULL,
                phone_encrypted bytea NOT NULL,
                phone_blind_index bytea NOT NULL,
                date_of_birth_encrypted bytea NOT NULL,
                age_band text NOT NULL,
                zip_code text NOT NULL,
                street_address_encrypted bytea,
                product_lines_of_interest text[] NOT NULL,
                preferred_contact_method text,
                notes text,
                lead_source text NOT NULL,
                status text NOT NULL,
                owner_user_id uuid,
                owner_username text,
                duplicate_of_lead_id uuid,
                duplicate_resolution text,
                correlation_id uuid NOT NULL,
                demo_session_id uuid,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now(),
                CONSTRAINT pk_leads PRIMARY KEY (id)
            )
            """
        )

        # Non-unique indexes on the two blind-index columns for exact-match
        # duplicate detection (Epic 6) without decryption.
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_leads_email_blind_index "
            f"ON {tenant.schema_name}.leads (email_blind_index)"
        )
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_leads_phone_blind_index "
            f"ON {tenant.schema_name}.leads (phone_blind_index)"
        )

        # Explicit grants on the now-existing table (same per-tenant CRUD +
        # platform read-role SELECT shape as 0006's pii_demo).
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE "
            f"ON {tenant.schema_name}.leads TO {tenant.db_role}"
        )
        op.execute(
            f"GRANT SELECT "
            f"ON {tenant.schema_name}.leads TO {PLATFORM_ROLE}"
        )


def downgrade() -> None:
    # Drop the table per schema; the indexes and grants fall with it. Ordered and
    # reversible.
    for tenant in TENANTS:
        op.execute(
            f"DROP TABLE IF EXISTS {tenant.schema_name}.leads"
        )
