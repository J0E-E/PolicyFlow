"""Tests for the named PII reveal seam — `on_pii_revealed` (Epic 7, P1.4).

A focused DB test, mirroring `test_audit_service.py`'s structure. The seam is no
longer a no-op: as of P1.4 it writes exactly one tenant-store `pii.revealed`
audit record carrying the field **name** only (never the value), so the old
"returns `None` / does nothing" assertion is replaced by "writes exactly one
tenant record with `field_names=[field]`".

It runs against the real Postgres booted in Docker (the same `database_engine`
substrate as `test_audit_service.py`), with the migrations applied. The seam
opens its **own** session through the module-global `app.audit.service.session_factory`;
the `container_audit_session_factory` fixture points that global at the container
database. It also requests `container_keys_session_factory` because `seed()`
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


@pytest.mark.asyncio
async def test_on_pii_revealed_writes_one_tenant_record_with_the_field_name(
    container_audit_session_factory, container_keys_session_factory
):
    """A reveal lands exactly one `pii.revealed` row in the caller's tenant store.

    The row carries the actor, the entity (`pii_demo` + record id), and the field
    **name** only (`field_names=["email"]`) — never the revealed value. Nothing
    reaches the platform store for that actor: a reveal is tenant-scoped (the
    project's cross-cutting axis), landing only in that tenant's own schema.
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

    await on_pii_revealed(identity, "pii_demo", record_id, "email")

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

    # That same actor wrote nothing to the platform store — a reveal routes only to
    # the tenant's own schema (tenant isolation).
    platform_rows = await _read_rows_for_actor(
        session_factory, "platform.audit_records", actor_user_id
    )
    assert platform_rows == []


def test_on_pii_revealed_is_an_async_function():
    """The seam is a coroutine function, so Epic 12 can `await` it."""
    assert inspect.iscoroutinefunction(on_pii_revealed) is True
