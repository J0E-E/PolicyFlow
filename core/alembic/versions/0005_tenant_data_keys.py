"""tenant_data_keys table in the platform schema, login-role-only readable

Creates the wrapped-key store: a single ``platform.tenant_data_keys`` table
holding one master-key-wrapped root key per tenant (``tenant_id`` primary key,
``wrapped_root_key`` bytea, ``created_at``), with the primary key named
``pk_tenant_data_keys`` to agree with the platform-bound ORM model.

The security crux is *who may read it*. The table is owned by the default login
role (the user the app connects as before ``get_tenant_db`` does its
``SET LOCAL ROLE`` into a tenant), and ownership already implies ``SELECT``. The
explicit ``GRANT SELECT ... TO CURRENT_USER`` below documents that login-role-only
boundary; **no** grant is made to any tenant role or to ``platform_reader``, and
none is needed — ``0003`` gave ``platform_reader`` only a one-time grant on the
then-existing tables (not ``ALTER DEFAULT PRIVILEGES``), so a new ``platform``
table is private by default. So even a fully tenant-scoped request can never read
key material, and the tenant-isolation story holds.

There is deliberately **no** foreign key on ``tenant_id`` (matching the TDD §5
column list exactly); integrity is guarded by the Epic 6 seed inserting only
registry tenant ids.

Live apply against real Postgres is exercised in this epic's substrate test
(``core/tests/test_tenant_data_keys.py``).

Revision ID: 0005_tenant_data_keys
Revises: 0004_tenant_settings
Create Date: 2026-06-13

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_tenant_data_keys"
down_revision: Union[str, None] = "0004_tenant_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the wrapped-key store in the platform schema.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS platform.tenant_data_keys (
            tenant_id uuid NOT NULL,
            wrapped_root_key bytea NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_tenant_data_keys PRIMARY KEY (tenant_id)
        )
        """
    )

    # Ownership already implies SELECT for the login role; this explicit grant
    # documents the login-role-only boundary. No tenant role and no
    # platform_reader is granted, so key material is unreadable inside any
    # tenant-scoped request.
    op.execute(
        "GRANT SELECT ON platform.tenant_data_keys TO CURRENT_USER"
    )


def downgrade() -> None:
    # Drop the table; the grant falls with it. Reversible and replayable.
    op.execute("DROP TABLE IF EXISTS platform.tenant_data_keys")
