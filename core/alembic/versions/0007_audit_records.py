"""audit stores + audit_writer role + append-only grants

Stands up the phase's audit storage and security backbone — no application code
yet. Two append-only stores are created with identical columns: a tenantless
``platform.audit_records`` table in the shared ``platform`` schema (for
platform/tenantless events), and a per-tenant ``audit_records`` table inside
**each** tenant schema named in ``app.tenancy.registry.TENANTS`` (physical tenant
isolation, the same schema-per-tenant trick the rest of the platform uses).

Append-only is made **physical** beneath the application by a dedicated
``audit_writer`` NOLOGIN role that holds only ``INSERT`` + ``SELECT`` on both
stores — never ``UPDATE`` or ``DELETE`` — so no role the app writes audit as can
ever change or remove a record. The connected login role is ``NOINHERIT`` (set in
``0003``), so it must ``SET ROLE audit_writer`` explicitly; this migration makes
it a member via ``GRANT audit_writer TO CURRENT_USER`` (the ``0003`` membership
precedent).

Grants are then tightened to the TDD §5 matrix: each tenant role keeps SELECT on
its own ``audit_records`` (for the viewer) but has its auto-granted INSERT/UPDATE/
DELETE **revoked**, and ``platform_reader`` has its auto-granted SELECT on each
tenant ``audit_records`` **revoked** — so tenant audit is readable only inside its
own tenant. ``platform.audit_records`` is left ungranted to ``platform_reader`` (a
write-then-quiet compliance store; new platform tables are private by default
because ``0003`` gave ``platform_reader`` only a one-time grant, not default
privileges).

A non-unique ``ix_audit_records_occurred_at`` index on ``occurred_at`` is created
on **both** stores — full structural symmetry so the Epic 3 ORM models stay
genuinely identical. Every identifier is interpolated only from the registry,
never from user input, so the migration and the registry can never disagree about
which schema/role serves which tenant.

Live apply against real Postgres is exercised in this epic's substrate test
(``core/tests/test_audit_migration.py``).

Revision ID: 0007_audit_records
Revises: 0006_pii_demo
Create Date: 2026-06-14

"""
from typing import Sequence, Union

from alembic import op

from app.tenancy.registry import AUDIT_WRITER_ROLE, PLATFORM_ROLE, TENANTS

# revision identifiers, used by Alembic.
revision: str = "0007_audit_records"
down_revision: Union[str, None] = "0006_pii_demo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def create_role_if_absent(role_name: str) -> None:
    """Create a NOLOGIN role idempotently.

    Roles are cluster-global, so a plain ``CREATE ROLE`` would fail on a second
    apply (or against a cluster where another database already created the role).
    The ``DO`` block guards on ``pg_roles`` so re-running is safe. Copied from
    ``0003_tenant_schemas.py`` to keep this migration self-contained.
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


def create_audit_records_table(qualified_table: str) -> None:
    """Create one ``audit_records`` table (identical columns in both stores).

    ``qualified_table`` is the schema-qualified name (e.g. ``platform.audit_records``
    or ``sunshine.audit_records``). The primary-key constraint is named
    ``pk_audit_records`` in every schema — constraint names are unique per schema,
    not cluster-global, so the same name in different schemas does not clash (the
    same fixed-name pattern ``0006`` uses for ``pk_pii_demo``). Columns follow
    TDD §5 verbatim.
    """
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {qualified_table} (
            id uuid NOT NULL,
            occurred_at timestamptz NOT NULL DEFAULT now(),
            tenant_id uuid,
            actor_user_id uuid,
            actor_role text,
            event_type text NOT NULL,
            entity_type text,
            entity_id uuid,
            field_names text[],
            outcome text NOT NULL,
            CONSTRAINT pk_audit_records PRIMARY KEY (id)
        )
        """
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_audit_records_occurred_at "
        f"ON {qualified_table} (occurred_at)"
    )


def upgrade() -> None:
    # 1. The dedicated audit-writer role, and login-role membership so the service
    #    can `SET ROLE audit_writer` (the login role is NOINHERIT from 0003).
    create_role_if_absent(AUDIT_WRITER_ROLE)
    op.execute(f"GRANT {AUDIT_WRITER_ROLE} TO CURRENT_USER")

    # 2. The platform store: tenantless audit records in the shared schema, plus
    #    the occurred_at index. audit_writer gets USAGE on the schema and
    #    INSERT + SELECT on the table — nothing else (no UPDATE/DELETE).
    create_audit_records_table("platform.audit_records")
    op.execute(f"GRANT USAGE ON SCHEMA platform TO {AUDIT_WRITER_ROLE}")
    op.execute(
        f"GRANT INSERT, SELECT "
        f"ON platform.audit_records TO {AUDIT_WRITER_ROLE}"
    )
    # platform.audit_records is deliberately NOT granted to platform_reader
    # (write-then-quiet compliance store; no in-app reader).

    # 3. Per tenant: the identical audit_records table + index in its own schema,
    #    audit_writer INSERT+SELECT, then the append-only REVOKEs that tighten the
    #    0003 default-privilege CRUD down to the TDD §5 grant matrix.
    for tenant in TENANTS:
        qualified_table = f"{tenant.schema_name}.audit_records"
        create_audit_records_table(qualified_table)

        # audit_writer can reach and append to this tenant's store.
        op.execute(
            f"GRANT USAGE ON SCHEMA {tenant.schema_name} TO {AUDIT_WRITER_ROLE}"
        )
        op.execute(
            f"GRANT INSERT, SELECT ON {qualified_table} TO {AUDIT_WRITER_ROLE}"
        )

        # The tenant role was auto-granted full CRUD by 0003's default
        # privileges. Revoke writes so it is SELECT-only on its own audit (for
        # the viewer); keep SELECT.
        op.execute(
            f"REVOKE INSERT, UPDATE, DELETE "
            f"ON {qualified_table} FROM {tenant.db_role}"
        )

        # platform_reader was auto-granted SELECT by 0003's default privileges.
        # Revoke it so tenant audit is readable only inside its own tenant.
        op.execute(
            f"REVOKE SELECT ON {qualified_table} FROM {PLATFORM_ROLE}"
        )


def downgrade() -> None:
    # Reverse of upgrade, in dependency order. Dropping the tables takes their
    # indexes and table-level grants with them, but the schema-level USAGE grants
    # to audit_writer survive a table drop and must be revoked explicitly before
    # DROP ROLE (Postgres refuses to drop a role any object still depends on).

    # 3. Drop the per-tenant audit stores and revoke audit_writer's schema USAGE.
    for tenant in TENANTS:
        op.execute(
            f"DROP TABLE IF EXISTS {tenant.schema_name}.audit_records"
        )
        op.execute(
            f"REVOKE USAGE ON SCHEMA {tenant.schema_name} FROM {AUDIT_WRITER_ROLE}"
        )

    # 2. Drop the platform audit store and revoke audit_writer's platform USAGE.
    op.execute("DROP TABLE IF EXISTS platform.audit_records")
    op.execute(f"REVOKE USAGE ON SCHEMA platform FROM {AUDIT_WRITER_ROLE}")

    # 1. Revoke the login-role membership, then drop the now-dependency-free role
    #    (cluster-global, guarded with IF EXISTS).
    op.execute(f"REVOKE {AUDIT_WRITER_ROLE} FROM CURRENT_USER")
    op.execute(f"DROP ROLE IF EXISTS {AUDIT_WRITER_ROLE}")
