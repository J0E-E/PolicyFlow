"""tenant schemas, roles, grants, and tenant columns

Provisions the schema-per-tenant isolation backbone the registry describes. For
each tenant in ``app.tenancy.registry.TENANTS`` this creates a dedicated NOLOGIN
role, a schema owned by that role, and the USAGE + default-privilege grants that
make the schema boundary the enforcement layer. It also creates the cross-tenant
``platform_reader`` read-role, makes the connected login role ``NOINHERIT`` and a
member of every tenant role plus ``platform_reader`` (so a request can ``SET
ROLE`` into exactly one tenant), and adds the nullable ``schema_name`` /
``db_role`` columns to ``platform.tenants``.

The two new columns are added NULLABLE with no backfill — populating them is
Epic 3's job, which keeps the Epic-1 seed (it runs after ``upgrade head`` and
does not yet set these columns) green. Every identifier is interpolated only from
the registry, never from user input, so the migration and the seed can never
disagree about which schema/role serves which tenant.

Live apply against real Postgres is exercised in the Epic 2 substrate test
(``core/tests/test_tenant_schemas.py``).

Revision ID: 0003_tenant_schemas
Revises: 0002_platform_identity
Create Date: 2026-06-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.tenancy.registry import PLATFORM_ROLE, TENANTS

# revision identifiers, used by Alembic.
revision: str = "0003_tenant_schemas"
down_revision: Union[str, None] = "0002_platform_identity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def create_role_if_absent(role_name: str) -> None:
    """Create a NOLOGIN role idempotently.

    Roles are cluster-global, so a plain ``CREATE ROLE`` would fail on a second
    apply (or against a cluster where another database already created the role).
    The ``DO`` block guards on ``pg_roles`` so re-running is safe.
    """
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = '{role_name}'
            ) THEN
                CREATE ROLE {role_name} NOLOGIN;
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    # 1. The cross-tenant platform read-role.
    create_role_if_absent(PLATFORM_ROLE)

    # 2. Per tenant: a dedicated role, an owned schema, and the grants that make
    #    the schema boundary the isolation layer.
    for tenant in TENANTS:
        create_role_if_absent(tenant.db_role)

        op.execute(
            f"CREATE SCHEMA IF NOT EXISTS {tenant.schema_name} "
            f"AUTHORIZATION {tenant.db_role}"
        )
        op.execute(
            f"GRANT USAGE ON SCHEMA {tenant.schema_name} TO {tenant.db_role}"
        )
        op.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {tenant.schema_name} "
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {tenant.db_role}"
        )

        # Sanctioned cross-tenant operational reads for the platform read-role:
        # USAGE on the schema and a default SELECT on its future tables.
        op.execute(
            f"GRANT USAGE ON SCHEMA {tenant.schema_name} TO {PLATFORM_ROLE}"
        )
        op.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {tenant.schema_name} "
            f"GRANT SELECT ON TABLES TO {PLATFORM_ROLE}"
        )

    # 3. The platform read-role can read the shared `platform` schema.
    op.execute(f"GRANT USAGE ON SCHEMA platform TO {PLATFORM_ROLE}")
    op.execute(
        f"GRANT SELECT ON ALL TABLES IN SCHEMA platform TO {PLATFORM_ROLE}"
    )

    # 4. The connected login role holds none of these privileges ambiently
    #    (NOINHERIT) but is a member of every tenant role + the read-role, so a
    #    request can `SET ROLE` into exactly one of them.
    op.execute("ALTER ROLE CURRENT_USER NOINHERIT")
    for tenant in TENANTS:
        op.execute(f"GRANT {tenant.db_role} TO CURRENT_USER")
    op.execute(f"GRANT {PLATFORM_ROLE} TO CURRENT_USER")

    # 5. The two new tenant columns — nullable, no backfill (Epic 3 populates).
    op.add_column(
        "tenants",
        sa.Column("schema_name", sa.Text(), nullable=True),
        schema="platform",
    )
    op.add_column(
        "tenants",
        sa.Column("db_role", sa.Text(), nullable=True),
        schema="platform",
    )


def downgrade() -> None:
    # Reverse of upgrade, in dependency order.

    # 5. Drop the two tenant columns.
    op.drop_column("tenants", "db_role", schema="platform")
    op.drop_column("tenants", "schema_name", schema="platform")

    # 4. Restore the connected login role: revoke memberships, re-enable INHERIT.
    op.execute(f"REVOKE {PLATFORM_ROLE} FROM CURRENT_USER")
    for tenant in TENANTS:
        op.execute(f"REVOKE {tenant.db_role} FROM CURRENT_USER")
    op.execute("ALTER ROLE CURRENT_USER INHERIT")

    # 3. Revoke the platform read-role's grants on the shared schema.
    op.execute(
        f"REVOKE SELECT ON ALL TABLES IN SCHEMA platform FROM {PLATFORM_ROLE}"
    )
    op.execute(f"REVOKE USAGE ON SCHEMA platform FROM {PLATFORM_ROLE}")

    # 2. Per tenant: reverse the default privileges (both grantees) and drop the
    #    schema (CASCADE removes its objects before the owning role is dropped).
    for tenant in TENANTS:
        op.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {tenant.schema_name} "
            f"REVOKE SELECT ON TABLES FROM {PLATFORM_ROLE}"
        )
        op.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {tenant.schema_name} "
            f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES "
            f"FROM {tenant.db_role}"
        )
        op.execute(f"DROP SCHEMA IF EXISTS {tenant.schema_name} CASCADE")

    # 1. Drop the roles (cluster-global; guarded with IF EXISTS).
    for tenant in TENANTS:
        op.execute(f"DROP ROLE IF EXISTS {tenant.db_role}")
    op.execute(f"DROP ROLE IF EXISTS {PLATFORM_ROLE}")
