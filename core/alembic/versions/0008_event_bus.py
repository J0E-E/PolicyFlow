"""event-bus stores + outbox_relay/event_consumer roles + tight grants

Stands up the P1.5 event bus's storage and security backbone — no application
code yet. Two per-tenant tables are created inside **each** tenant schema named
in ``app.tenancy.registry.TENANTS`` (the ``0007`` per-tenant pattern; physical
tenant isolation, no tenantless ``platform`` twin — a ``platform`` write could
not sit in the tenant role's transaction, which would break the transactional
outbox's atomicity):

- ``<tenant>.outbox`` — the **transactional outbox**: one row per event, written
  in the *same* transaction as the state change that produced it, so an event is
  never lost relative to committed state. A partial index
  ``ix_outbox_unpublished`` on ``(occurred_at) WHERE published_at IS NULL`` keeps
  the relay's "unpublished rows, oldest first" scan cheap, and a defensive
  ``uq_outbox_event_id`` unique guards against a double-enqueue.
- ``<tenant>.processed_events`` — per-consumer idempotency + observable effect:
  the unique ``(consumer_name, event_id)`` constraint is the dedup signal (a
  duplicate insert means "already processed").

Two dedicated NOLOGIN roles enforce least privilege beneath the application, the
same tight-grant move ``0007`` makes for ``audit_writer``:

- ``outbox_relay`` holds only USAGE on each tenant schema + **SELECT + UPDATE** on
  each ``outbox`` (read unpublished rows, stamp ``published_at``) — never INSERT or
  DELETE.
- ``event_consumer`` holds only USAGE on each tenant schema + **INSERT + SELECT**
  on each ``processed_events`` (dedupe + record) — never UPDATE or DELETE.

The connected login role is ``NOINHERIT`` (set in ``0003``), so it must
``SET ROLE`` explicitly; this migration makes it a member of both new roles via
``GRANT … TO CURRENT_USER`` (the ``0003`` / ``0007`` membership precedent).

Grants are then tightened to the TDD §5.2 matrix. The tenant role was auto-granted
full CRUD by ``0003``'s default privileges; it is tightened to **INSERT-only** on
its own ``outbox`` (the request session's transactional write) and **SELECT-only**
on its own ``processed_events`` (the P1.9 timeline reads it). ``platform_reader``
has its auto-granted SELECT on **both** new tables **revoked** so operational
bookkeeping stays inside its own tenant, matching ``0007``'s tenant-audit
tightening.

Both tables are schema-less ORM twins (``OutboxEvent`` / ``ProcessedEvent``),
resolved via ``search_path`` and excluded from ``alembic check`` (the
``PiiDemoRecord`` precedent), so this migration **owns** every index and
constraint. Every identifier is interpolated only from the registry, never from
user input, so the migration and the registry can never disagree about which
schema/role serves which tenant.

Live apply against real Postgres is exercised in this epic's substrate test
(``core/tests/test_event_bus_migration.py``).

Revision ID: 0008_event_bus
Revises: 0007_audit_records
Create Date: 2026-06-15

"""
from typing import Sequence, Union

from alembic import op

from app.tenancy.registry import (
    EVENT_CONSUMER_ROLE,
    OUTBOX_RELAY_ROLE,
    PLATFORM_ROLE,
    TENANTS,
)

# revision identifiers, used by Alembic.
revision: str = "0008_event_bus"
down_revision: Union[str, None] = "0007_audit_records"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def create_role_if_absent(role_name: str) -> None:
    """Create a NOLOGIN role idempotently.

    Roles are cluster-global, so a plain ``CREATE ROLE`` would fail on a second
    apply (or against a cluster where another database already created the role).
    The ``DO`` block guards on ``pg_roles`` so re-running is safe. Copied from
    ``0007_audit_records.py`` to keep this migration self-contained.
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


def create_outbox_table(qualified_table: str) -> None:
    """Create one ``outbox`` table + its scan index and defensive unique.

    ``qualified_table`` is the schema-qualified name (e.g. ``sunshine.outbox``).
    Constraint/index names are fixed (``pk_outbox`` / ``uq_outbox_event_id`` /
    ``ix_outbox_unpublished``) in every schema — names are unique per schema, not
    cluster-global, so the same name in different schemas does not clash (the
    fixed-name pattern ``0006`` / ``0007`` use). Columns mirror ``EventEnvelope``
    (TDD §5.2) plus the relay's ``published_at`` marker.
    """
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {qualified_table} (
            id uuid NOT NULL,
            event_id uuid NOT NULL,
            event_type text NOT NULL,
            schema_version integer NOT NULL,
            tenant_id uuid NOT NULL,
            correlation_id uuid NOT NULL,
            causation_id uuid,
            actor_user_id uuid,
            actor_role text,
            demo_session_id uuid,
            payload jsonb NOT NULL,
            occurred_at timestamptz NOT NULL DEFAULT now(),
            published_at timestamptz,
            CONSTRAINT pk_outbox PRIMARY KEY (id),
            CONSTRAINT uq_outbox_event_id UNIQUE (event_id)
        )
        """
    )
    # Partial index for the relay scan: only unpublished rows, oldest first.
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_outbox_unpublished "
        f"ON {qualified_table} (occurred_at) WHERE published_at IS NULL"
    )


def create_processed_events_table(qualified_table: str) -> None:
    """Create one ``processed_events`` table + its dedup unique.

    ``qualified_table`` is the schema-qualified name (e.g.
    ``sunshine.processed_events``). The unique ``(consumer_name, event_id)`` is the
    idempotency key — a duplicate insert is the "already processed" signal. Columns
    follow TDD §5.2 verbatim.
    """
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {qualified_table} (
            id uuid NOT NULL,
            consumer_name text NOT NULL,
            event_id uuid NOT NULL,
            tenant_id uuid NOT NULL,
            event_type text NOT NULL,
            correlation_id uuid NOT NULL,
            processed_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_processed_events PRIMARY KEY (id),
            CONSTRAINT uq_processed_events_consumer_name_event_id
                UNIQUE (consumer_name, event_id)
        )
        """
    )


def upgrade() -> None:
    # 1. The two dedicated NOLOGIN roles, and login-role membership so the relay
    #    and consumers can `SET ROLE` into them (the login role is NOINHERIT from
    #    0003).
    create_role_if_absent(OUTBOX_RELAY_ROLE)
    create_role_if_absent(EVENT_CONSUMER_ROLE)
    op.execute(f"GRANT {OUTBOX_RELAY_ROLE} TO CURRENT_USER")
    op.execute(f"GRANT {EVENT_CONSUMER_ROLE} TO CURRENT_USER")

    # 2. Per tenant: the outbox + processed_events tables in its own schema, the
    #    tight role grants, then the REVOKEs that tighten the 0003 default-privilege
    #    CRUD down to the TDD §5.2 grant matrix.
    for tenant in TENANTS:
        outbox_table = f"{tenant.schema_name}.outbox"
        processed_events_table = f"{tenant.schema_name}.processed_events"
        create_outbox_table(outbox_table)
        create_processed_events_table(processed_events_table)

        # outbox_relay reaches each schema and reads/marks its outbox (no
        # INSERT/DELETE — the request session writes, the relay only publishes).
        op.execute(
            f"GRANT USAGE ON SCHEMA {tenant.schema_name} TO {OUTBOX_RELAY_ROLE}"
        )
        op.execute(
            f"GRANT SELECT, UPDATE ON {outbox_table} TO {OUTBOX_RELAY_ROLE}"
        )

        # event_consumer reaches each schema and dedupes/records into
        # processed_events (no UPDATE/DELETE — a processed event is immutable).
        op.execute(
            f"GRANT USAGE ON SCHEMA {tenant.schema_name} TO {EVENT_CONSUMER_ROLE}"
        )
        op.execute(
            f"GRANT INSERT, SELECT "
            f"ON {processed_events_table} TO {EVENT_CONSUMER_ROLE}"
        )

        # The tenant role was auto-granted full CRUD by 0003's default privileges.
        # Tighten its outbox to INSERT-only (the transactional write); it never
        # reads, updates, or deletes its own outbox (the relay owns those).
        op.execute(
            f"REVOKE SELECT, UPDATE, DELETE ON {outbox_table} FROM {tenant.db_role}"
        )
        # Tighten its processed_events to SELECT-only (the P1.9 timeline reads it);
        # the consumer, not the tenant role, writes processed events.
        op.execute(
            f"REVOKE INSERT, UPDATE, DELETE "
            f"ON {processed_events_table} FROM {tenant.db_role}"
        )

        # platform_reader was auto-granted SELECT by 0003's default privileges.
        # Revoke it on both tables so operational bookkeeping stays inside its own
        # tenant (matching 0007's tenant-audit tightening).
        op.execute(
            f"REVOKE SELECT ON {outbox_table} FROM {PLATFORM_ROLE}"
        )
        op.execute(
            f"REVOKE SELECT ON {processed_events_table} FROM {PLATFORM_ROLE}"
        )


def downgrade() -> None:
    # Reverse of upgrade, in dependency order. Dropping the tables takes their
    # indexes, constraints, and table-level grants with them, but the schema-level
    # USAGE grants to the two roles survive a table drop and must be revoked
    # explicitly before DROP ROLE (Postgres refuses to drop a role any object still
    # depends on).

    # 2. Drop the per-tenant event-bus stores and revoke the roles' schema USAGE.
    for tenant in TENANTS:
        op.execute(
            f"DROP TABLE IF EXISTS {tenant.schema_name}.processed_events"
        )
        op.execute(
            f"DROP TABLE IF EXISTS {tenant.schema_name}.outbox"
        )
        op.execute(
            f"REVOKE USAGE ON SCHEMA {tenant.schema_name} FROM {OUTBOX_RELAY_ROLE}"
        )
        op.execute(
            f"REVOKE USAGE ON SCHEMA {tenant.schema_name} FROM {EVENT_CONSUMER_ROLE}"
        )

    # 1. Revoke the login-role memberships, then drop the now-dependency-free roles
    #    (cluster-global, guarded with IF EXISTS).
    op.execute(f"REVOKE {OUTBOX_RELAY_ROLE} FROM CURRENT_USER")
    op.execute(f"REVOKE {EVENT_CONSUMER_ROLE} FROM CURRENT_USER")
    op.execute(f"DROP ROLE IF EXISTS {OUTBOX_RELAY_ROLE}")
    op.execute(f"DROP ROLE IF EXISTS {EVENT_CONSUMER_ROLE}")
