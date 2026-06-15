"""DB substrate proof for `enqueue_event` (Epic 3) — the transactional outbox write.

These tests run against the real Postgres booted in Docker (the same
`database_engine` substrate as `test_isolation_acceptance.py` Phase 1 and
`test_event_bus_migration.py`). They prove the two guarantees the enqueue seam
exists for:

- **Transactional** — the inserted row is present after the request transaction
  commits and absent after it rolls back, because `enqueue_event` writes on the
  caller's request session and never commits itself (the request transaction owns
  commit/rollback).
- **Tenant-scoped** — an enqueue under tenant A's role + `search_path` lands only
  in `A.outbox`, never `B.outbox`; and tenant A's role is physically denied a
  read of `B.outbox` (mirroring `test_isolation_acceptance.py`).

The enqueue itself runs under the real INSERT-only tenant role (`SET LOCAL ROLE`
+ `SET LOCAL search_path`, the `get_tenant_db` pattern), which directly verifies
the pure-INSERT-no-RETURNING decision. Because that role lacks SELECT on its own
`outbox` (Epic 2's grant), every read-back uses the SELECT-capable superuser
engine connection, schema-qualified — never the tenant role.

`pytest.ini` sets `asyncio_mode = auto`; these substrate tests carry an explicit
`@pytest.mark.asyncio` to match the other `database_engine` substrate modules.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.events.catalog import SCHEMA_VERSION, EventType
from app.events.envelope import EventEnvelope, build_envelope
from app.events.outbox import enqueue_event
from app.tenancy.registry import FLORIDA, SUNSHINE, TenantConfig

# The two tenants used throughout: A enqueues, B is the schema that must stay
# untouched and unreadable. Pulled from the registry so they stay the single
# source of truth for schema name and DB role.
TENANT_A = SUNSHINE
TENANT_B = FLORIDA


def build_outbox_envelope(tenant: TenantConfig) -> EventEnvelope:
    """Build a fresh `record.created` envelope addressed to `tenant`.

    A minimal, recognisable, non-PII envelope for one tenant — enough to insert
    and read back field-for-field. `build_envelope` mints the identity/timestamp
    fields; the actor and payload are fixed test values.
    """
    return build_envelope(
        event_type=EventType.RECORD_CREATED.value,
        tenant_id=uuid.uuid4(),
        actor_user_id=uuid.uuid4(),
        actor_role="tenant_admin",
        payload={"entity_type": "pii_demo", "entity_id": str(uuid.uuid4())},
    )


async def enqueue_under_tenant_role(
    database_engine, tenant: TenantConfig, envelope: EventEnvelope, *, commit: bool
):
    """Enqueue `envelope` on a session scoped to `tenant`, then commit or roll back.

    Opens a session, switches into the tenant exactly as `get_tenant_db` does
    (`SET LOCAL ROLE` + `SET LOCAL search_path`), calls the real `enqueue_event`,
    and then either commits or rolls back the transaction — the two halves of the
    transactional guarantee under test.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    async with session_factory() as session:
        await session.begin()
        await session.execute(text(f"SET LOCAL ROLE {tenant.db_role}"))
        await session.execute(
            text(f"SET LOCAL search_path TO {tenant.schema_name}")
        )
        await enqueue_event(session, envelope)
        if commit:
            await session.commit()
        else:
            await session.rollback()


async def read_outbox_row(database_engine, schema_name: str, event_id: uuid.UUID):
    """Read back a single outbox row by `event_id` from `schema_name`.

    Uses the SELECT-capable superuser engine connection (the tenant role is
    INSERT-only on its own outbox), schema-qualified — the same faithful-reader
    substrate as `test_event_bus_migration.py`. Returns the row or `None`.
    """
    async with database_engine.connect() as connection:
        return (
            await connection.execute(
                text(
                    "SELECT event_id, event_type, schema_version, tenant_id, "
                    "occurred_at, correlation_id, causation_id, actor_user_id, "
                    "actor_role, demo_session_id, payload, published_at "
                    f"FROM {schema_name}.outbox WHERE event_id = :event_id"
                ),
                {"event_id": event_id},
            )
        ).one_or_none()


# --- Phase 1: the enqueue helper + commit/rollback proof ---------------------


@pytest.mark.asyncio
async def test_enqueued_event_is_present_after_commit(database_engine):
    """After the request transaction commits, the enqueued row is in the outbox.

    Scope to tenant A, `enqueue_event`, commit; then read `A.outbox` back through
    the superuser connection and assert exactly one row whose columns equal the
    envelope's fields. `published_at` stays NULL (the relay sets it later).
    """
    envelope = build_outbox_envelope(TENANT_A)

    await enqueue_under_tenant_role(
        database_engine, TENANT_A, envelope, commit=True
    )

    row = await read_outbox_row(database_engine, TENANT_A.schema_name, envelope.event_id)

    assert row is not None
    assert row.event_id == envelope.event_id
    assert row.event_type == envelope.event_type
    assert row.schema_version == envelope.schema_version == SCHEMA_VERSION
    assert row.tenant_id == envelope.tenant_id
    assert row.occurred_at == envelope.occurred_at
    assert row.correlation_id == envelope.correlation_id
    assert row.causation_id == envelope.causation_id
    assert row.actor_user_id == envelope.actor_user_id
    assert row.actor_role == envelope.actor_role
    assert row.demo_session_id == envelope.demo_session_id
    assert row.payload == envelope.payload
    assert row.published_at is None


@pytest.mark.asyncio
async def test_enqueued_event_is_absent_after_rollback(database_engine):
    """After the request transaction rolls back, no enqueued row remains.

    The transactional guarantee: scope to tenant A, `enqueue_event`, then roll
    back without committing. Reading `A.outbox` back finds zero rows for that
    `event_id` — the event did not survive a transaction that did not commit.
    """
    envelope = build_outbox_envelope(TENANT_A)

    await enqueue_under_tenant_role(
        database_engine, TENANT_A, envelope, commit=False
    )

    row = await read_outbox_row(database_engine, TENANT_A.schema_name, envelope.event_id)

    assert row is None


# --- Phase 2: per-tenant isolation proof -------------------------------------


@pytest.mark.asyncio
async def test_enqueue_lands_only_in_the_callers_tenant_schema(database_engine):
    """A committed enqueue under tenant A lands in `A.outbox`, never `B.outbox`.

    Positive isolation: the schema-less insert resolved against tenant A's
    `search_path`, so the row exists in `A.outbox` and is absent from `B.outbox`
    — the write never crossed schemas.
    """
    envelope = build_outbox_envelope(TENANT_A)

    await enqueue_under_tenant_role(
        database_engine, TENANT_A, envelope, commit=True
    )

    row_in_a = await read_outbox_row(
        database_engine, TENANT_A.schema_name, envelope.event_id
    )
    row_in_b = await read_outbox_row(
        database_engine, TENANT_B.schema_name, envelope.event_id
    )

    assert row_in_a is not None
    assert row_in_b is None


@pytest.mark.asyncio
async def test_tenant_role_cannot_read_another_tenants_outbox(database_engine):
    """Under `SET LOCAL ROLE tenant_A`, reading `B.outbox` is permission-denied.

    Negative isolation (the scope's exact requirement): switch to tenant A's role
    and attempt a `SELECT FROM B.outbox`. Postgres raises an insufficient-privilege
    error (a SQLAlchemy `ProgrammingError` surfacing as "permission denied"),
    mirroring `test_isolation_acceptance.py`. The denial aborts its own
    transaction, so `SET LOCAL ROLE` resets as the block rolls back.
    """
    with pytest.raises(ProgrammingError) as denial:
        async with database_engine.begin() as connection:
            await connection.execute(text(f"SET LOCAL ROLE {TENANT_A.db_role}"))
            await connection.execute(
                text(f"SELECT * FROM {TENANT_B.schema_name}.outbox")
            )

    message = str(denial.value).lower()
    assert "permission denied" in message, (
        f"expected {TENANT_A.db_role} to be denied SELECT on "
        f"{TENANT_B.schema_name}.outbox, got: {message}"
    )
