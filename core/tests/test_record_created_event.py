"""DB-backed proof of the `record.created` event trigger (Epic 8, P1.5).

Epics 1–7 stood up the whole event bus (envelope, outbox table, transactional
`enqueue_event`, relay, broker, stub consumers, lifespan) — but nothing fed it
yet. Epic 8 is the first trigger: the existing `POST /api/pii-demo/` create now
**also** enqueues a `record.created` event onto its outbox, on the *same request
session and transaction* as the row insert (the transactional outbox). The
response stays byte-for-byte unchanged — create just *also* enqueues.

This drives that create over the real DB-backed client (the same `seeded` +
`db_client` substrate the other endpoint tests use), logging in as the seeded
Sunshine Agent, and reads the outbox back to prove:

- **Happy path** — a full create writes exactly one `record.created` outbox row to
  **that tenant's** schema, with the envelope identity/correlation fields stamped,
  `published_at` still NULL (the relay sets it later), and a payload carrying the
  entity reference plus `age_band` plus the names-only `fields` list.
- **No PII** — none of the supplied plaintext values (`display_name`, `email`,
  exact date of birth, phone, mock Medicare id) appears in **any** column of that
  outbox row — only the field *names* do (the no-PII-snapshot contract).
- **Atomicity** — when the audit write (which runs *after* the enqueue) raises, the
  create is rolled back, so no `record.created` outbox row is left behind — the
  enqueue rode the request transaction and rolled back with the record.

This mirrors `test_record_change_audit.py`'s shape: a DB-backed client create,
read back through the SELECT-capable superuser `database_engine` connection
(schema-qualified — the tenant role is INSERT-only on its own `outbox`), pinned by
the created record id via `payload->>'entity_id'` (the event id is minted inside
the handler, so it is not known to the test). `pytest.ini` sets `asyncio_mode =
auto`, so these async tests carry no `@pytest.mark.asyncio` decorator. The
`seeded` / `db_client` fixtures and the `login_as` helper are reused by name from
`test_endpoints_db.py`.
"""

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

import app.pii_demo.router as pii_demo_router_module
from app.events.catalog import SCHEMA_VERSION, EventType
from app.models.user import Role
from app.tenancy.registry import SUNSHINE

from .test_endpoints_db import (  # noqa: F401 — `seeded` fixture is used by name
    login_as,
    seeded,
)

# The full create body the happy-path test reuses. Its plaintext values are the
# ones the no-PII assertion proves never appear in the outbox row — only the field
# *names* (`display_name`, `email`, …) do.
FULL_RECORD_BODY = {
    "display_name": "Jane Demo",
    "email": "jane.demo@example.com",
    "date_of_birth": "1950-03-15",
    "phone": "+1 (415) 555-1234",
    "mock_medicare_id": "123-45-1234",
}


async def read_outbox_rows_for_entity(database_engine, schema_name, entity_id):
    """Return all `record.created` outbox rows for one entity id, as a list of rows.

    Mirrors `test_outbox_enqueue.py::read_outbox_row` but keys on the payload's
    `entity_id` rather than the `event_id`: the event id is minted inside the
    create handler, so the test never sees it, whereas the created record's id is
    in the create response. Reads through the SELECT-capable superuser engine
    connection (the tenant role is INSERT-only on its own `outbox`),
    schema-qualified — the same faithful-reader substrate as the Epic 3 tests.
    """
    async with database_engine.connect() as connection:
        return (
            await connection.execute(
                text(
                    "SELECT event_id, event_type, schema_version, tenant_id, "
                    "occurred_at, correlation_id, causation_id, actor_user_id, "
                    "actor_role, demo_session_id, payload, published_at "
                    f"FROM {schema_name}.outbox "
                    "WHERE event_type = :event_type "
                    "AND payload->>'entity_id' = :entity_id"
                ),
                {
                    "event_type": str(EventType.RECORD_CREATED),
                    "entity_id": str(entity_id),
                },
            )
        ).all()


async def read_outbox_row_as_mapping(database_engine, schema_name, entity_id):
    """Return the full `record.created` outbox row for one entity id as a dict.

    Used by the no-PII proof: the whole row is read as a mapping (``SELECT *``) so
    the test can scan **every** column's value for the supplied plaintext — the
    assertion is that none of it appears anywhere, only the field names do.
    """
    async with database_engine.connect() as connection:
        rows = await connection.execute(
            text(
                f"SELECT * FROM {schema_name}.outbox "
                "WHERE event_type = :event_type "
                "AND payload->>'entity_id' = :entity_id"
            ),
            {
                "event_type": str(EventType.RECORD_CREATED),
                "entity_id": str(entity_id),
            },
        )
        return [dict(row) for row in rows.mappings().all()]


async def count_record_created_outbox_rows(database_engine, schema_name):
    """Return the total count of `record.created` outbox rows in `schema_name`.

    The before/after count the atomicity test uses: the session-scoped container
    DB is never reset between tests, so the proof is that the failed create leaves
    the count **unchanged**, not that the table is empty.
    """
    async with database_engine.connect() as connection:
        return (
            await connection.execute(
                text(
                    f"SELECT count(*) FROM {schema_name}.outbox "
                    "WHERE event_type = :event_type"
                ),
                {"event_type": str(EventType.RECORD_CREATED)},
            )
        ).scalar_one()


# --- Phase 1: the enqueue lands one non-PII outbox row -----------------------


async def test_pii_demo_create_enqueues_record_created(
    seeded, db_client, container_audit_session_factory, database_engine
):
    """A full create enqueues exactly one tenant-scoped `record.created` outbox row.

    The Sunshine Agent holds `CREATE_EDIT_RECORDS`; a full-body create → 201 and
    enqueues exactly one `record.created` row into that tenant's own `outbox`, on
    the same request transaction as the insert. The envelope identity/correlation
    fields are stamped, the actor is the Agent, `causation_id` / `demo_session_id`
    are NULL, `published_at` is still NULL (the relay sets it later), and the
    payload carries the entity reference plus the coarse `age_band` plus the five
    supplied field *names* — never a PII value.
    """
    login_response = await login_as(db_client, Role.AGENT)
    assert login_response.status_code == 200
    actor_user_id = uuid.UUID(login_response.json()["user"]["id"])

    create_response = await db_client.post("/api/pii-demo/", json=FULL_RECORD_BODY)
    assert create_response.status_code == 201
    created_id = uuid.UUID(create_response.json()["record"]["id"])
    age_band = create_response.json()["record"]["age_band"]

    rows = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, created_id
    )
    assert len(rows) == 1
    enqueued = rows[0]
    assert enqueued.event_type == str(EventType.RECORD_CREATED)
    assert enqueued.schema_version == SCHEMA_VERSION
    assert enqueued.tenant_id is not None
    assert enqueued.actor_user_id == actor_user_id
    assert enqueued.actor_role == Role.AGENT
    assert enqueued.correlation_id is not None
    assert enqueued.causation_id is None
    assert enqueued.demo_session_id is None
    assert enqueued.published_at is None
    assert enqueued.payload == {
        "entity_type": "pii_demo",
        "entity_id": str(created_id),
        "age_band": age_band,
        "fields": [
            "display_name",
            "email",
            "date_of_birth",
            "phone",
            "mock_medicare_id",
        ],
    }


async def test_record_created_outbox_row_carries_no_pii(
    seeded, db_client, container_audit_session_factory, database_engine
):
    """No supplied plaintext value appears anywhere in the `record.created` row.

    The no-PII-snapshot contract: a full-body create enqueues a `record.created`
    row whose **every** column value is scanned for each supplied plaintext
    (`display_name`, `email`, the exact date of birth, the phone, the mock Medicare
    id) — none of it appears anywhere, only the field *names* do, so the event
    itself never leaks PII. (`age_band` is a coarse, already-unmasked bucket, not a
    PII value.)
    """
    login_response = await login_as(db_client, Role.AGENT)
    assert login_response.status_code == 200

    create_response = await db_client.post("/api/pii-demo/", json=FULL_RECORD_BODY)
    assert create_response.status_code == 201
    created_id = uuid.UUID(create_response.json()["record"]["id"])

    rows_as_mappings = await read_outbox_row_as_mapping(
        database_engine, SUNSHINE.schema_name, created_id
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


# --- Phase 2: atomicity — the enqueue rolls back with the record -------------


async def test_failed_create_enqueues_no_outbox_row(
    seeded, db_client, container_audit_session_factory, database_engine, monkeypatch
):
    """A failing audit write rolls the create back — no `record.created` row lands.

    The enqueue rides the request transaction and sits **before** the audit write
    (which is its own session that commits immediately). Monkeypatching the
    router's `record_audit_event` to raise makes the create error after the
    enqueue's flush; the exception propagates through `get_tenant_db`, which rolls
    back the request transaction — undoing **both** the `pii_demo` insert and the
    outbox row (atomic, no orphan). The proof is that the `record.created` outbox
    count for the tenant is unchanged across the failed request, and a follow-up
    list confirms no record with the unique `display_name` persisted.

    The test's `ASGITransport` re-raises an unhandled handler exception to the
    caller (it does not turn it into a 500 response body), so the failed request
    surfaces here as the propagating `RuntimeError` (the `test_record_change_audit`
    idiom; the name is imported into the router's namespace).
    """
    login_response = await login_as(db_client, Role.AGENT)
    assert login_response.status_code == 200

    count_before = await count_record_created_outbox_rows(
        database_engine, SUNSHINE.schema_name
    )

    monkeypatch.setattr(
        pii_demo_router_module,
        "record_audit_event",
        AsyncMock(side_effect=RuntimeError("audit write failed")),
    )

    # A unique display_name so the follow-up list assertion is unambiguous against
    # the accumulating, never-reset container DB.
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

    count_after = await count_record_created_outbox_rows(
        database_engine, SUNSHINE.schema_name
    )
    assert count_after == count_before

    # The create was rolled back: no record with the unique name is reachable.
    list_response = await db_client.get("/api/pii-demo/")
    assert list_response.status_code == 200
    display_names = {
        record["display_name"] for record in list_response.json()["records"]
    }
    assert unique_display_name not in display_names
