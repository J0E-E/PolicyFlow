"""demo_purge role + cross-schema DELETE grants + leads.demo_session_id index

Stands up the security backbone and performance index for the P1.8 purge engine
(``app.demo.purge``). No application code lands here — only the dedicated role,
its tight cross-schema grants, and the per-tenant index the purge sweep (and the
Epic 4 visibility filter) scan.

**The ``demo_purge`` role (the ``0008`` least-privilege pattern).** A single
NOLOGIN role holds exactly what the purge sweep needs and nothing more:

- ``USAGE`` on each tenant schema + **SELECT + DELETE** on that tenant's ``leads``
  — read the in-scope session ids and remove their session-tagged rows. Never
  INSERT or UPDATE: the purge only ever deletes.
- ``USAGE`` on ``platform`` + **SELECT + DELETE** on ``platform.demo_session_tenant_seed``
  (the Epic 7 ledger) and ``platform.demo_sessions`` — remove the ledger markers
  and, for the Expired/All scopes, the session rows themselves; SELECT resolves the
  in-scope ids (``Expired`` → ``expires_at < now()``, ``All`` → every id).

``demo_purge`` is the **only** role granted DELETE on ``leads`` — deliberately
separate from the tenant roles' ``SELECT, INSERT`` on the ``0012`` ledger, so the
destructive sweep never rides a request transaction. The connected login role is
``NOINHERIT`` (set in ``0003``), so it must ``SET ROLE`` explicitly; this migration
makes it a member via ``GRANT demo_purge TO CURRENT_USER`` (the ``0003`` / ``0008``
membership precedent), which is how the purge engine's own session becomes the role.

**The per-tenant ``leads.demo_session_id`` index.** ``0009`` added the nullable
``demo_session_id`` column with no index; the purge sweep's
``DELETE … WHERE demo_session_id = ANY(:ids)`` and the Epic 4 visibility filter's
``demo_session_id = :sid`` both scan it, so each tenant's ``leads`` gets a fixed-name
``ix_leads_demo_session_id`` index. Names are unique per schema, not cluster-global,
so the same name in different schemas does not clash (the ``0008`` fixed-name
pattern). ``leads`` is a schema-less ORM twin resolved via ``search_path`` and
excluded from ``alembic check`` (the ``PiiDemoRecord`` / ``OutboxEvent`` precedent),
so this migration **owns** the index, hand-written like its table in ``0009``.

Every identifier is interpolated only from the registry, never from user input, so
the migration and the registry can never disagree about which schema/role serves
which tenant. Live apply against real Postgres is exercised in this epic's substrate
test (``core/tests/test_demo_purge_migration.py``).

Revision ID: 0013_demo_purge_role
Revises: 0012_demo_session_tenant_seed
Create Date: 2026-06-23

"""
from typing import Sequence, Union

from alembic import op

from app.tenancy.registry import DEMO_PURGE_ROLE, TENANTS

# revision identifiers, used by Alembic.
revision: str = "0013_demo_purge_role"
down_revision: Union[str, None] = "0012_demo_session_tenant_seed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def create_role_if_absent(role_name: str) -> None:
    """Create a NOLOGIN role idempotently.

    Roles are cluster-global, so a plain ``CREATE ROLE`` would fail on a second
    apply (or against a cluster where another database already created the role).
    The ``DO`` block guards on ``pg_roles`` so re-running is safe. Copied from
    ``0008_event_bus.py`` to keep this migration self-contained.
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
    # 1. The dedicated NOLOGIN purge role, and login-role membership so the purge
    #    engine can `SET ROLE` into it (the login role is NOINHERIT from 0003).
    create_role_if_absent(DEMO_PURGE_ROLE)
    op.execute(f"GRANT {DEMO_PURGE_ROLE} TO CURRENT_USER")

    # 2. Per tenant: reach the schema, read/delete its leads, and index the
    #    demo_session_id column the sweep + the Epic 4 filter scan.
    for tenant in TENANTS:
        leads_table = f"{tenant.schema_name}.leads"
        op.execute(
            f"GRANT USAGE ON SCHEMA {tenant.schema_name} TO {DEMO_PURGE_ROLE}"
        )
        # SELECT (resolve in-scope ids / read for the sweep) + DELETE (remove the
        # session-tagged overlay). Never INSERT or UPDATE — the purge only deletes.
        op.execute(
            f"GRANT SELECT, DELETE ON {leads_table} TO {DEMO_PURGE_ROLE}"
        )
        # The purge sweep and the Epic 4 visibility filter both predicate on
        # demo_session_id; 0009 created the column without an index. Fixed name per
        # schema (names are per-schema, not cluster-global — the 0008 pattern).
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_leads_demo_session_id "
            f"ON {leads_table} (demo_session_id)"
        )

    # 3. Reach the platform schema and read/delete the two demo tables: the Epic 7
    #    ledger (markers) and demo_sessions (the session rows themselves, for the
    #    Expired/All scopes). SELECT resolves the in-scope ids; DELETE removes them.
    op.execute(f"GRANT USAGE ON SCHEMA platform TO {DEMO_PURGE_ROLE}")
    op.execute(
        f"GRANT SELECT, DELETE ON platform.demo_session_tenant_seed "
        f"TO {DEMO_PURGE_ROLE}"
    )
    op.execute(
        f"GRANT SELECT, DELETE ON platform.demo_sessions TO {DEMO_PURGE_ROLE}"
    )


def downgrade() -> None:
    # Reverse of upgrade, in dependency order. The role's grants must all be revoked
    # before DROP ROLE (Postgres refuses to drop a role any object still depends on).

    # 3. Revoke the platform-schema grants.
    op.execute(
        f"REVOKE SELECT, DELETE ON platform.demo_sessions FROM {DEMO_PURGE_ROLE}"
    )
    op.execute(
        f"REVOKE SELECT, DELETE ON platform.demo_session_tenant_seed "
        f"FROM {DEMO_PURGE_ROLE}"
    )
    op.execute(f"REVOKE USAGE ON SCHEMA platform FROM {DEMO_PURGE_ROLE}")

    # 2. Per tenant: drop the index, then revoke the leads + schema grants.
    for tenant in TENANTS:
        leads_table = f"{tenant.schema_name}.leads"
        op.execute(
            f"DROP INDEX IF EXISTS {tenant.schema_name}.ix_leads_demo_session_id"
        )
        op.execute(
            f"REVOKE SELECT, DELETE ON {leads_table} FROM {DEMO_PURGE_ROLE}"
        )
        op.execute(
            f"REVOKE USAGE ON SCHEMA {tenant.schema_name} FROM {DEMO_PURGE_ROLE}"
        )

    # 1. Revoke the login-role membership, then drop the now-dependency-free role
    #    (cluster-global, guarded with IF EXISTS).
    op.execute(f"REVOKE {DEMO_PURGE_ROLE} FROM CURRENT_USER")
    op.execute(f"DROP ROLE IF EXISTS {DEMO_PURGE_ROLE}")
