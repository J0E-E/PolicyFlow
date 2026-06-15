"""Tests for the named PII reveal seam — `on_pii_revealed` (Epic 7, P1.4 / P1.5).

A focused DB test, mirroring `test_audit_service.py`'s structure. The seam is no
longer a no-op: as of P1.4 it writes exactly one tenant-store `pii.revealed`
audit record carrying the field **name** only (never the value), and as of P1.5
it **also** enqueues one `pii.revealed` event into the caller's tenant `outbox`
on the request session **before** the audit write — so the assertion is "writes
exactly one tenant audit record with `field_names=[field]` **and** one
`pii.revealed` outbox row".

It runs against the real Postgres booted in Docker (the same `database_engine`
substrate as `test_audit_service.py`), with the migrations applied. The audit
effect opens its **own** session through the module-global
`app.audit.service.session_factory`; the `container_audit_session_factory`
fixture points that global at the container database. The P1.5 enqueue, by
contrast, runs on a **request** session the test supplies — opened against the
container DB under the tenant's INSERT-only `outbox` role + `search_path` (the
`test_outbox_enqueue.py` idiom) and committed after the call so the row lands.
The test also requests `container_keys_session_factory` because `seed()`
encrypts the demo PII rows and so resolves per-tenant keys through
`app.pii.keys.session_factory`, which must likewise point at the container — the
same pairing every `test_audit_service.py` test uses.

The remaining pure guard (`test_on_pii_revealed_is_an_async_function`) stays — the
reveal endpoint must be able to `await` the seam.
"""

import inspect
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth.provider import Identity
from app.models.user import Role
from app.pii.reveal_seam import on_pii_revealed
from app.seed import seed
from app.tenancy.registry import SUNSHINE


async def _seed_and_get_tenant_id(session_factory, slug: str) -> uuid.UUID:
    """Seed the demo data, then return the `platform.tenants` id for `slug`."""
    async with session_factory() as session:
        await seed(session)
    async with session_factory() as session:
        tenant_id_row = await session.execute(
            text("SELECT id FROM platform.tenants WHERE slug = :slug"),
            {"slug": slug},
        )
        return tenant_id_row.scalar_one()


async def _read_rows_for_actor(
    session_factory, qualified_table: str, actor_user_id: uuid.UUID
) -> list:
    """Return the rows of a schema-qualified audit table written by one actor.

    Mirrors `test_audit_service.py::_read_rows_for_actor` (mirrored rather than
    cross-imported between test files, the Epic 6 precedent). Every read filters
    by a per-test `actor_user_id` rather than counting the whole table: the
    `database_engine` substrate is session-scoped and never reset between tests,
    so rows accumulate; a per-actor filter is the `test_tenant_keys.py` idiom
    that keeps each assertion attributable.
    """
    async with session_factory() as session:
        rows = await session.execute(
            text(
                "SELECT tenant_id, actor_user_id, actor_role, event_type, "
                "entity_type, entity_id, field_names, outcome "
                f"FROM {qualified_table} WHERE actor_user_id = :actor_user_id "
                "ORDER BY occurred_at DESC"
            ),
            {"actor_user_id": actor_user_id},
        )
        return rows.all()


async def _open_tenant_outbox_session(database_engine):
    """Open a request-style session scoped to Sunshine's INSERT-only outbox role.

    The P1.5 enqueue runs on the **request** session, so the seam's first
    argument must be a session that can INSERT into the tenant's `outbox`. This
    mirrors `test_outbox_enqueue.py::enqueue_under_tenant_role`: open a session,
    begin a transaction, and `SET LOCAL ROLE` + `SET LOCAL search_path` to the
    tenant exactly as `get_tenant_db` does. The caller commits after the seam runs
    so the enqueued row lands.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    session = session_factory()
    await session.begin()
    await session.execute(text(f"SET LOCAL ROLE {SUNSHINE.db_role}"))
    await session.execute(
        text(f"SET LOCAL search_path TO {SUNSHINE.schema_name}")
    )
    return session


async def _count_pii_revealed_outbox_rows(database_engine, actor_user_id):
    """Count `pii.revealed` outbox rows in Sunshine's schema for one actor.

    Reads through the SELECT-capable superuser engine connection (the tenant role
    is INSERT-only on its own `outbox`), schema-qualified, filtered by
    `actor_user_id` so the assertion stays attributable against the accumulating,
    never-reset container DB — the `test_outbox_enqueue.py` reader idiom.
    """
    async with database_engine.connect() as connection:
        return (
            await connection.execute(
                text(
                    f"SELECT count(*) FROM {SUNSHINE.schema_name}.outbox "
                    "WHERE event_type = 'pii.revealed' "
                    "AND actor_user_id = :actor_user_id"
                ),
                {"actor_user_id": actor_user_id},
            )
        ).scalar_one()


@pytest.mark.asyncio
async def test_on_pii_revealed_writes_one_tenant_record_with_the_field_name(
    container_audit_session_factory, container_keys_session_factory, database_engine
):
    """A reveal lands one `pii.revealed` audit row and one `pii.revealed` outbox row.

    The audit row carries the actor, the entity (`pii_demo` + record id), and the
    field **name** only (`field_names=["email"]`) — never the revealed value.
    Nothing reaches the platform store for that actor: a reveal is tenant-scoped
    (the project's cross-cutting axis), landing only in that tenant's own schema.
    The P1.5 enqueue, on the request session the test supplies, writes exactly one
    `pii.revealed` outbox row in the same tenant schema.
    """
    session_factory = container_audit_session_factory
    tenant_id = await _seed_and_get_tenant_id(session_factory, SUNSHINE.slug)
    actor_user_id = uuid.uuid4()
    record_id = uuid.uuid4()
    identity = Identity(
        user_id=actor_user_id,
        tenant_id=tenant_id,
        role=Role.AGENT,
        username="agent.one@example",
    )

    request_session = await _open_tenant_outbox_session(database_engine)
    try:
        await on_pii_revealed(request_session, identity, "pii_demo", record_id, "email")
        await request_session.commit()
    finally:
        await request_session.close()

    tenant_rows = await _read_rows_for_actor(
        session_factory, f"{SUNSHINE.schema_name}.audit_records", actor_user_id
    )
    assert len(tenant_rows) == 1
    written = tenant_rows[0]
    assert written.tenant_id == identity.tenant_id
    assert written.actor_user_id == identity.user_id
    assert written.actor_role == "agent"
    assert written.event_type == "pii.revealed"
    assert written.entity_type == "pii_demo"
    assert written.entity_id == record_id
    assert written.field_names == ["email"]
    assert written.outcome == "success"

    # The P1.5 enqueue wrote exactly one `pii.revealed` outbox row for this actor.
    outbox_count = await _count_pii_revealed_outbox_rows(
        database_engine, actor_user_id
    )
    assert outbox_count == 1

    # That same actor wrote nothing to the platform store — a reveal routes only to
    # the tenant's own schema (tenant isolation).
    platform_rows = await _read_rows_for_actor(
        session_factory, "platform.audit_records", actor_user_id
    )
    assert platform_rows == []


def test_on_pii_revealed_is_an_async_function():
    """The seam is a coroutine function, so Epic 12 can `await` it."""
    assert inspect.iscoroutinefunction(on_pii_revealed) is True
