"""pii_demo demonstrator table per tenant schema, with grants and blind indexes

Creates the phase's demonstrator entity: a ``pii_demo`` table inside **each**
tenant schema named in ``app.tenancy.registry.TENANTS``. The table carries every
distinct PII field treatment in one place — a plaintext display name, the
encrypted (``bytea``) field blobs, the two blind-index (``bytea``) columns used
for exact-match lookup without decryption, the derived plaintext age band, and
the never-revealable mock Medicare id — so the rest of the phase has one concrete
target exercising encryption, blind indexing, masking, and age-band derivation.

Each blind-index column gets a **non-unique** index
(``ix_pii_demo_email_blind_index`` / ``ix_pii_demo_phone_blind_index``, following
the ``ix_`` naming convention in ``app.db``) so the Epic 11 lookup can match by
fingerprint cheaply.

Grants mirror ``0004_tenant_settings`` exactly: each tenant role gets full CRUD on
its own copy and ``platform_reader`` gets SELECT, so the schema boundary stays the
isolation layer. Every identifier is interpolated only from the registry, never
from user input, matching 0004.

Live apply against real Postgres is exercised in this epic's substrate test
(``core/tests/test_pii_demo.py``).

Revision ID: 0006_pii_demo
Revises: 0005_tenant_data_keys
Create Date: 2026-06-13

"""
from typing import Sequence, Union

from alembic import op

from app.tenancy.registry import PLATFORM_ROLE, TENANTS

# revision identifiers, used by Alembic.
revision: str = "0006_pii_demo"
down_revision: Union[str, None] = "0005_tenant_data_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # For each tenant: create the demonstrator table in its own schema, its two
    # blind-index indexes, then the explicit per-tenant CRUD grant and the
    # platform read-role SELECT grant.
    for tenant in TENANTS:
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {tenant.schema_name}.pii_demo (
                id uuid NOT NULL,
                display_name text NOT NULL,
                email_encrypted bytea NOT NULL,
                email_blind_index bytea NOT NULL,
                phone_encrypted bytea,
                phone_blind_index bytea,
                date_of_birth_encrypted bytea,
                age_band text NOT NULL,
                mock_medicare_id_encrypted bytea,
                created_at timestamptz NOT NULL DEFAULT now(),
                CONSTRAINT pk_pii_demo PRIMARY KEY (id)
            )
            """
        )

        # Non-unique indexes on the two blind-index columns for exact-match
        # lookup (Epic 11) without decryption.
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_pii_demo_email_blind_index "
            f"ON {tenant.schema_name}.pii_demo (email_blind_index)"
        )
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_pii_demo_phone_blind_index "
            f"ON {tenant.schema_name}.pii_demo (phone_blind_index)"
        )

        # Explicit grants on the now-existing table (same per-tenant CRUD +
        # platform read-role SELECT shape as 0004's tenant_settings).
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE "
            f"ON {tenant.schema_name}.pii_demo TO {tenant.db_role}"
        )
        op.execute(
            f"GRANT SELECT "
            f"ON {tenant.schema_name}.pii_demo TO {PLATFORM_ROLE}"
        )


def downgrade() -> None:
    # Drop the table per schema; the indexes and grants fall with it. Ordered and
    # reversible.
    for tenant in TENANTS:
        op.execute(
            f"DROP TABLE IF EXISTS {tenant.schema_name}.pii_demo"
        )
