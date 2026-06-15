"""DB-backed proof of the record-change audit wiring (Epic 9, P1.4).

Drives the one write surface that exists today — `POST /api/pii-demo/` — over the
real DB-backed client (the same `seeded` + `db_client` substrate the other
endpoint tests use), logging in as the seeded Sunshine Agent, and reads the audit
stores back directly to prove the create leaves the right trail in the right
store:

- **Happy path (names, not values):** a full create writes exactly one
  `record.created` / `success` row to **that tenant's** store naming the five
  supplied fields, and **none** of the supplied plaintext values appears in any
  column — only the field *names* do.
- **Optional-omission:** a create with only the three required fields records only
  those three names, proving the written-field-name list is dynamic.
- **Tenant isolation:** the actor wrote **nothing** to `platform.audit_records` —
  a `record.created` create is tenant-scoped (the project's cross-cutting axis).
- **Strict rollback:** when the audit write raises, the create is rolled back, so
  the request fails and no record with the attempted `display_name` is reachable.

This mirrors `test_auth_audit.py`: a per-actor read-back filtered by a per-test
`actor_user_id` (rather than a global `== 1` count), because the session-scoped
container DB is never reset between tests, so rows accumulate. `pytest.ini` sets
`asyncio_mode = auto`, so these async tests carry no `@pytest.mark.asyncio`
decorator. The `seeded` / `db_client` fixtures and the `login_as` helper are
reused by name from `test_endpoints_db.py`, the Epic 6/8 precedent.
"""

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

import app.pii_demo.router as pii_demo_router_module
from app.audit.records import EventType, Outcome
from app.models.user import Role
from app.tenancy.registry import SUNSHINE

from .test_endpoints_db import (  # noqa: F401 — `seeded` fixture is used by name
    login_as,
    seeded,
)

# The full create body the happy-path test reuses. Its plaintext values are the
# ones the no-PII assertion proves never appear in the audit row — only the field
# *names* (`display_name`, `email`, …) do.
FULL_RECORD_BODY = {
    "display_name": "Jane Demo",
    "email": "jane.demo@example.com",
    "date_of_birth": "1950-03-15",
    "phone": "+1 (415) 555-1234",
    "mock_medicare_id": "123-45-1234",
}


async def _read_record_created_rows_for_actor(
    session_factory, qualified_table, actor_user_id
):
    """Return one audit table's `record.created` rows for one actor, newest-first.

    Mirrors `test_auth_audit.py::_read_audit_rows_for_actor`, filtered to
    `event_type = 'record.created'`: a plain ``SELECT … WHERE actor_user_id = :id
    AND event_type = 'record.created' ORDER BY occurred_at DESC`` against a
    schema-qualified audit table. Filtering by a per-test `actor_user_id` (rather
    than counting the whole table) keeps each assertion attributable, because the
    session-scoped container DB is never reset between tests.
    """
    async with session_factory() as session:
        rows = await session.execute(
            text(
                "SELECT tenant_id, actor_user_id, actor_role, event_type, "
                "entity_type, entity_id, field_names, outcome "
                f"FROM {qualified_table} WHERE actor_user_id = :actor_user_id "
                "AND event_type = :event_type ORDER BY occurred_at DESC"
            ),
            {
                "actor_user_id": actor_user_id,
                "event_type": str(EventType.RECORD_CREATED),
            },
        )
        return rows.all()


async def _read_record_created_row_as_mapping(
    session_factory, qualified_table, entity_id
):
    """Return the full `record.created` row for one entity id as a dict.

    Used by the no-PII proof: the whole row is read as a mapping (``SELECT *``) so
    the test can scan **every** column's value for the supplied plaintext — the
    assertion is that none of it appears anywhere, only the field names do.
    """
    async with session_factory() as session:
        rows = await session.execute(
            text(
                f"SELECT * FROM {qualified_table} "
                "WHERE entity_id = :entity_id AND event_type = :event_type"
            ),
            {
                "entity_id": entity_id,
                "event_type": str(EventType.RECORD_CREATED),
            },
        )
        return [dict(row) for row in rows.mappings().all()]


# --- Happy path: names not values, tenant-isolated ---------------------------


async def test_pii_demo_create_audits_record_created(
    seeded, db_client, container_audit_session_factory
):
    """A full create writes one tenant-store `record.created` naming the five fields.

    The Sunshine Agent holds `CREATE_EDIT_RECORDS`; a full-body create writes
    exactly one `record.created` / `success` row to that tenant's own store
    attributed to that actor, with the new record's id as `entity_id`, the five
    supplied field *names* in `field_names`, and a non-NULL `tenant_id`. None of
    the supplied plaintext values appears in any column, and nothing for that actor
    reaches the platform store — a create is tenant-scoped (the cross-cutting axis).
    """
    login_response = await login_as(db_client, Role.AGENT)
    assert login_response.status_code == 200
    actor_user_id = uuid.UUID(login_response.json()["user"]["id"])

    create_response = await db_client.post("/api/pii-demo/", json=FULL_RECORD_BODY)
    assert create_response.status_code == 201
    created_id = uuid.UUID(create_response.json()["record"]["id"])

    # Read this test's own row by `entity_id`: the seeded Agent persona is shared
    # with the other create tests, so a per-actor read accumulates their rows
    # across the never-reset container DB. The `entity_id` pins this create.
    tenant_rows = await _read_record_created_rows_for_actor(
        container_audit_session_factory,
        f"{SUNSHINE.schema_name}.audit_records",
        actor_user_id,
    )
    own_rows = [row for row in tenant_rows if row.entity_id == created_id]
    assert len(own_rows) == 1
    written = own_rows[0]
    assert written.actor_user_id == actor_user_id
    assert written.actor_role == Role.AGENT
    assert written.event_type == EventType.RECORD_CREATED
    assert written.outcome == Outcome.SUCCESS
    assert written.entity_type == "pii_demo"
    assert written.entity_id == created_id
    assert written.tenant_id is not None
    assert written.field_names == [
        "display_name",
        "email",
        "date_of_birth",
        "phone",
        "mock_medicare_id",
    ]

    # No supplied plaintext value appears in any column of the row — only the field
    # *names* do, so the audit trail itself never leaks PII.
    rows_as_mappings = await _read_record_created_row_as_mapping(
        container_audit_session_factory,
        f"{SUNSHINE.schema_name}.audit_records",
        created_id,
    )
    assert len(rows_as_mappings) == 1
    supplied_plaintext_values = [
        "Jane Demo",
        "jane.demo@example.com",
        "1950-03-15",
        "+1 (415) 555-1234",
        "123-45-1234",
    ]
    for value in rows_as_mappings[0].values():
        for plaintext in supplied_plaintext_values:
            assert plaintext not in str(value)

    # That same actor wrote nothing to the platform store — a create routes only to
    # the tenant's own schema (tenant isolation).
    platform_rows = await _read_record_created_rows_for_actor(
        container_audit_session_factory, "platform.audit_records", actor_user_id
    )
    assert platform_rows == []


async def test_create_without_optionals_records_only_supplied_names(
    seeded, db_client, container_audit_session_factory
):
    """A create with only the three required fields records only those three names.

    Omitting `phone` and `mock_medicare_id` makes the written-field-name list
    contain only `display_name`, `email`, `date_of_birth` — proving the list is
    dynamic and omits absent optionals.
    """
    login_response = await login_as(db_client, Role.AGENT)
    assert login_response.status_code == 200
    actor_user_id = uuid.UUID(login_response.json()["user"]["id"])

    create_response = await db_client.post(
        "/api/pii-demo/",
        json={
            "display_name": "Only Required",
            "email": "only.required@example.com",
            "date_of_birth": "2000-01-01",
        },
    )
    assert create_response.status_code == 201
    created_id = uuid.UUID(create_response.json()["record"]["id"])

    # Read this test's own row by `entity_id`: the seeded Agent persona is shared
    # with the happy-path test, so a per-actor read would also pick up that test's
    # row across the never-reset container DB. The `entity_id` pins this create.
    tenant_rows = await _read_record_created_rows_for_actor(
        container_audit_session_factory,
        f"{SUNSHINE.schema_name}.audit_records",
        actor_user_id,
    )
    own_rows = [row for row in tenant_rows if row.entity_id == created_id]
    assert len(own_rows) == 1
    written = own_rows[0]
    assert written.field_names == ["display_name", "email", "date_of_birth"]


# --- Strict rollback: a failing audit write undoes the create ----------------


async def test_failed_audit_rolls_back_the_create(
    seeded, db_client, container_audit_session_factory, monkeypatch
):
    """A failing audit write rolls the create back — no record persists.

    Monkeypatches the router's `record_audit_event` with an `AsyncMock` that raises
    (the name is imported into the router's namespace, so patching it there
    intercepts the call — the idiom `test_router.py` uses for `create_session`).
    The create then errors, and because the audit emit sits before the handler
    returns, the exception propagates through `get_tenant_db`, which rolls the
    `pii_demo` insert back. A follow-up list must not contain the unique record.

    The test's `ASGITransport` re-raises an unhandled handler exception to the
    caller (it does not turn it into a 500 response body), so the failed request
    surfaces here as the propagating `RuntimeError` — the request failing is what
    the rollback rides on. The proof the create was undone is the follow-up list.
    """
    login_response = await login_as(db_client, Role.AGENT)
    assert login_response.status_code == 200

    monkeypatch.setattr(
        pii_demo_router_module,
        "record_audit_event",
        AsyncMock(side_effect=RuntimeError("audit write failed")),
    )

    # A unique display_name so the follow-up list assertion is unambiguous against
    # the accumulating container DB.
    unique_display_name = f"rollback-{uuid.uuid4()}"
    with pytest.raises(RuntimeError, match="audit write failed"):
        await db_client.post(
            "/api/pii-demo/",
            json={
                "display_name": unique_display_name,
                "email": "rollback@example.com",
                "date_of_birth": "1999-12-31",
            },
        )

    # The create was rolled back: no record with the unique name is reachable.
    list_response = await db_client.get("/api/pii-demo/")
    assert list_response.status_code == 200
    display_names = {
        record["display_name"] for record in list_response.json()["records"]
    }
    assert unique_display_name not in display_names
