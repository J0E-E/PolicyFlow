"""outbox SELECT grant for the tenant role + processed_events.result_summary

Lands the storage + grant backbone for the P1.9 per-record event timeline
(Epic 1, the tracer slice). No application code lands here — only one additive
column and one re-grant, both per tenant, mirroring the ``0013`` per-tenant loop.

**The outbox SELECT re-grant.** ``0008`` tightened the tenant ``db_role`` to
**INSERT-only** on its own ``outbox`` (it ``REVOKE``d ``SELECT, UPDATE, DELETE`` —
see ``0008_event_bus.py`` line ~202) because, at the time, the request session only
ever *wrote* outbox rows; the relay owned the reads. The P1.9 timeline endpoint
runs under that same tenant ``db_role`` (``get_tenant_db``) and must now *read* the
lead's own outbox rows, so this migration ``GRANT``s ``SELECT`` back on each
tenant's ``outbox``. UPDATE/DELETE stay revoked — the timeline only reads. The
role still only ever sees its own schema, so tenant isolation is unchanged
(``0008`` kept ``processed_events`` SELECT "for the P1.9 timeline" by the same
reasoning; this completes the pair).

**The ``processed_events.result_summary`` column.** A nullable ``text`` column the
later result-summary epic (Epic 3) fills with the enrichment reaction's one-line
canned score; added here, as one additive migration alongside the grant, so Epic 3
needs no migration of its own. Older rows simply read ``NULL``. ``processed_events``
is a schema-less ORM twin (``ProcessedEvent``) resolved via ``search_path`` and
excluded from ``alembic check`` (the ``PiiDemoRecord`` / ``OutboxEvent`` precedent),
so this migration **owns** the column; the twin merely declares it.

Every identifier is interpolated only from the registry, never from user input, so
the migration and the registry can never disagree about which schema/role serves
which tenant. Live apply against real Postgres is exercised in this epic's substrate
test (``core/tests/test_timeline_migration.py``).

Revision ID: 0014_timeline_outbox_grant
Revises: 0013_demo_purge_role
Create Date: 2026-06-24

"""
from typing import Sequence, Union

from alembic import op

from app.tenancy.registry import TENANTS

# revision identifiers, used by Alembic.
revision: str = "0014_timeline_outbox_grant"
down_revision: Union[str, None] = "0013_demo_purge_role"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Per tenant: re-grant the tenant role SELECT on its own outbox (0008 revoked
    # it; the P1.9 timeline endpoint reads outbox under this role) and add the
    # nullable result_summary column the Epic 3 summary fills. UPDATE/DELETE stay
    # revoked — the timeline only ever reads its outbox.
    for tenant in TENANTS:
        outbox_table = f"{tenant.schema_name}.outbox"
        processed_events_table = f"{tenant.schema_name}.processed_events"
        op.execute(f"GRANT SELECT ON {outbox_table} TO {tenant.db_role}")
        op.execute(
            f"ALTER TABLE {processed_events_table} "
            f"ADD COLUMN IF NOT EXISTS result_summary text"
        )


def downgrade() -> None:
    # Reverse of upgrade: drop the column and revoke the SELECT, restoring the
    # 0008 INSERT-only-on-outbox grant shape.
    for tenant in TENANTS:
        outbox_table = f"{tenant.schema_name}.outbox"
        processed_events_table = f"{tenant.schema_name}.processed_events"
        op.execute(
            f"ALTER TABLE {processed_events_table} "
            f"DROP COLUMN IF EXISTS result_summary"
        )
        op.execute(f"REVOKE SELECT ON {outbox_table} FROM {tenant.db_role}")
