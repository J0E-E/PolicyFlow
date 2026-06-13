"""tenant_settings table per tenant schema, with grants

Creates the first real tenant-scoped entity: a ``tenant_settings`` table inside
**each** tenant schema named in ``app.tenancy.registry.TENANTS``. The table holds
one tenant's presentation sliver — a brand colour, an optional logo URL, and a
welcome message — keyed by the ``platform.tenants`` id it configures (a singleton
row per tenant schema), with the primary key named ``pk_tenant_settings`` to
agree with the schema-less ORM model.

Grants are explicit here (not relying on 0003's default-privilege timing): each
tenant role gets full CRUD on its own copy and ``platform_reader`` gets SELECT,
so the schema boundary stays the isolation layer and Epic 8's tests have a stable
target. Every identifier is interpolated only from the registry, never from user
input, matching 0003.

Live apply against real Postgres is exercised in the Epic 4 substrate test
(``core/tests/test_tenant_settings.py``).

Revision ID: 0004_tenant_settings
Revises: 0003_tenant_schemas
Create Date: 2026-06-13

"""
from typing import Sequence, Union

from alembic import op

from app.tenancy.registry import PLATFORM_ROLE, TENANTS

# revision identifiers, used by Alembic.
revision: str = "0004_tenant_settings"
down_revision: Union[str, None] = "0003_tenant_schemas"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # For each tenant: create the settings table in its own schema, then the
    # explicit per-tenant CRUD grant and the platform read-role SELECT grant.
    for tenant in TENANTS:
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {tenant.schema_name}.tenant_settings (
                tenant_id uuid NOT NULL,
                brand_primary_color text NOT NULL,
                brand_logo_url text,
                welcome_message text NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now(),
                CONSTRAINT pk_tenant_settings PRIMARY KEY (tenant_id)
            )
            """
        )

        # Explicit grants on the now-existing table (robust regardless of the
        # default-privilege timing in 0003).
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE "
            f"ON {tenant.schema_name}.tenant_settings TO {tenant.db_role}"
        )
        op.execute(
            f"GRANT SELECT "
            f"ON {tenant.schema_name}.tenant_settings TO {PLATFORM_ROLE}"
        )


def downgrade() -> None:
    # Drop the table per schema; the grants fall with it. Ordered and reversible.
    for tenant in TENANTS:
        op.execute(
            f"DROP TABLE IF EXISTS {tenant.schema_name}.tenant_settings"
        )
