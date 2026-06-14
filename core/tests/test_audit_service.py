"""DB tests for the audit-emit service (Epic 4) — `record_audit_event`.

These run against the real Postgres booted in Docker (the same `database_engine`
substrate as `test_tenant_scoping.py` / `test_tenant_keys.py`), with the
migrations applied. They prove the one function the whole P1.4 phase writes
through:

Phase 1 — happy path + two-store routing:
- a `tenant_id` routes the row into **that tenant's** ``audit_records`` (not the
  platform store);
- `tenant_id=None` routes the row into ``platform.audit_records``;
- `field_names=["email", "phone"]` round-trips as a Postgres ``text[]`` of those
  exact names (names, never values);
- two sequential events come back newest-first when ordered ``occurred_at DESC``
  — proving the stored data supports the reader's ordering (Epic 10).

Phase 2 — strict-failure contract:
- a random unregistered `tenant_id` **raises** `UnknownAuditTenant` (propagates,
  strict) and writes **no** row to any store — a sensitive op cannot proceed
  unaudited, and the schema whitelist guard holds.

The service opens its **own** session through the module-global
`app.audit.service.session_factory`; the `container_audit_session_factory`
fixture (in `conftest.py`) points that global at the container database. Each
tenant id is read fresh from the seeded `platform.tenants` so the rows land in a
real, migrated tenant schema.

Every test also requests `container_keys_session_factory`: `seed()` encrypts the
demo PII rows (since Epic 10) and so resolves per-tenant keys through
`app.pii.keys.session_factory`, which must likewise point at the container — same
own-session shape as the audit factory. Without it `seed()` would hit the
unreachable eager default engine.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.audit.records import EventType, Outcome
from app.audit.service import UnknownAuditTenant, record_audit_event
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

    Every read filters by a per-test `actor_user_id` rather than counting the whole
    table. The `database_engine` substrate is session-scoped and never reset
    between tests, so rows accumulate across the file; a per-actor filter is the
    `test_tenant_keys.py` idiom (a fresh id per test, assert only on your own rows)
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


# --- Phase 1: happy path + two-store routing ---------------------------------


@pytest.mark.asyncio
async def test_tenant_event_writes_one_row_into_that_tenants_store(
    container_audit_session_factory, container_keys_session_factory
):
    """A `tenant_id` event lands in that tenant's `audit_records`, not platform."""
    session_factory = container_audit_session_factory
    tenant_id = await _seed_and_get_tenant_id(session_factory, SUNSHINE.slug)
    actor_user_id = uuid.uuid4()

    await record_audit_event(
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        actor_role="agent",
        event_type=EventType.RECORD_CREATED,
        outcome=Outcome.SUCCESS,
        entity_type="pii_demo",
        entity_id=uuid.uuid4(),
    )

    tenant_rows = await _read_rows_for_actor(
        session_factory, f"{SUNSHINE.schema_name}.audit_records", actor_user_id
    )
    assert len(tenant_rows) == 1
    written = tenant_rows[0]
    assert written.tenant_id == tenant_id
    assert written.actor_user_id == actor_user_id
    assert written.actor_role == "agent"
    assert written.event_type == EventType.RECORD_CREATED
    assert written.entity_type == "pii_demo"
    assert written.outcome == Outcome.SUCCESS

    # That same actor wrote nothing to the platform store — routing went only to
    # the tenant store.
    platform_rows = await _read_rows_for_actor(
        session_factory, "platform.audit_records", actor_user_id
    )
    assert platform_rows == []


@pytest.mark.asyncio
async def test_platform_event_writes_one_row_into_the_platform_store(
    container_audit_session_factory, container_keys_session_factory
):
    """A `tenant_id=None` event lands in `platform.audit_records`."""
    session_factory = container_audit_session_factory
    # Seed so the tenant store exists and can be checked too.
    await _seed_and_get_tenant_id(session_factory, SUNSHINE.slug)
    actor_user_id = uuid.uuid4()

    await record_audit_event(
        tenant_id=None,
        actor_user_id=actor_user_id,
        actor_role="platform_admin",
        event_type=EventType.PLATFORM_CROSS_TENANT_READ,
        outcome=Outcome.SUCCESS,
        entity_type="tenant_settings",
    )

    platform_rows = await _read_rows_for_actor(
        session_factory, "platform.audit_records", actor_user_id
    )
    assert len(platform_rows) == 1
    written = platform_rows[0]
    assert written.tenant_id is None
    assert written.actor_role == "platform_admin"
    assert written.event_type == EventType.PLATFORM_CROSS_TENANT_READ
    assert written.outcome == Outcome.SUCCESS

    # That same actor wrote nothing to the tenant store — the platform branch never
    # touched it.
    tenant_rows = await _read_rows_for_actor(
        session_factory, f"{SUNSHINE.schema_name}.audit_records", actor_user_id
    )
    assert tenant_rows == []


@pytest.mark.asyncio
async def test_field_names_round_trip_as_a_text_array_of_names(
    container_audit_session_factory, container_keys_session_factory
):
    """`field_names` round-trips as a `text[]` of the exact names (never values)."""
    session_factory = container_audit_session_factory
    tenant_id = await _seed_and_get_tenant_id(session_factory, SUNSHINE.slug)
    actor_user_id = uuid.uuid4()

    await record_audit_event(
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        actor_role="agent",
        event_type=EventType.PII_REVEALED,
        outcome=Outcome.SUCCESS,
        entity_type="pii_demo",
        entity_id=uuid.uuid4(),
        field_names=["email", "phone"],
    )

    tenant_rows = await _read_rows_for_actor(
        session_factory, f"{SUNSHINE.schema_name}.audit_records", actor_user_id
    )
    assert len(tenant_rows) == 1
    assert tenant_rows[0].field_names == ["email", "phone"]


@pytest.mark.asyncio
async def test_two_events_order_newest_first_by_occurred_at(
    container_audit_session_factory, container_keys_session_factory
):
    """Two sequential events come back newest-first when ordered occurred_at DESC.

    The service writes `occurred_at` via the column's `now()` server default and
    leaves ordering to the reader (Epic 10). This proves the stored data *supports*
    a newest-first read: the second event recorded sorts ahead of the first. Both
    events share one `actor_user_id` so the read picks up exactly this test's pair.
    """
    session_factory = container_audit_session_factory
    tenant_id = await _seed_and_get_tenant_id(session_factory, SUNSHINE.slug)
    actor_user_id = uuid.uuid4()
    first_entity_id = uuid.uuid4()
    second_entity_id = uuid.uuid4()

    await record_audit_event(
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        actor_role="agent",
        event_type=EventType.RECORD_CREATED,
        outcome=Outcome.SUCCESS,
        entity_type="pii_demo",
        entity_id=first_entity_id,
    )
    await record_audit_event(
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        actor_role="agent",
        event_type=EventType.RECORD_CREATED,
        outcome=Outcome.SUCCESS,
        entity_type="pii_demo",
        entity_id=second_entity_id,
    )

    tenant_rows = await _read_rows_for_actor(
        session_factory, f"{SUNSHINE.schema_name}.audit_records", actor_user_id
    )
    ordered_entity_ids = [row.entity_id for row in tenant_rows]
    assert ordered_entity_ids == [second_entity_id, first_entity_id]


# --- Phase 2: strict-failure contract (the unknown-tenant edge) --------------


@pytest.mark.asyncio
async def test_unknown_tenant_raises_and_writes_no_row(
    container_audit_session_factory, container_keys_session_factory
):
    """An unregistered `tenant_id` raises `UnknownAuditTenant` and writes nothing.

    Strict failure (TDD Decision 7): a sensitive op cannot proceed unaudited, and
    the schema whitelist guard refuses to route a tenant with no row in
    `platform.tenants`. No row attributable to this actor reaches any store.
    """
    session_factory = container_audit_session_factory
    # Seed so both stores exist (and so this is a true unknown-tenant miss, not an
    # empty-database artifact); the random id below is never seeded.
    await _seed_and_get_tenant_id(session_factory, SUNSHINE.slug)
    unregistered_tenant_id = uuid.uuid4()
    actor_user_id = uuid.uuid4()

    with pytest.raises(UnknownAuditTenant) as raised:
        await record_audit_event(
            tenant_id=unregistered_tenant_id,
            actor_user_id=actor_user_id,
            actor_role="agent",
            event_type=EventType.RECORD_CREATED,
            outcome=Outcome.SUCCESS,
        )

    assert raised.value.tenant_id == unregistered_tenant_id
    assert str(unregistered_tenant_id) in str(raised.value)

    # No row reached either store — strict, and the guard held before any write.
    assert (
        await _read_rows_for_actor(
            session_factory, "platform.audit_records", actor_user_id
        )
        == []
    )
    assert (
        await _read_rows_for_actor(
            session_factory, f"{SUNSHINE.schema_name}.audit_records", actor_user_id
        )
        == []
    )
