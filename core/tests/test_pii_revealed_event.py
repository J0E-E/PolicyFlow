"""DB-backed proof of the `pii.revealed` event trigger (Epic 9, P1.5).

Epic 8 fed the bus its first real trigger (`record.created` on create). Epic 9 is
the second: the guarded reveal route (`POST /api/pii-demo/{id}/reveal`) now **also**
enqueues one `pii.revealed` event onto the caller's `outbox`, on the *same request
session and transaction* as the reveal, carrying the field **name** only — never
the revealed value. The reveal response stays unchanged — it just *also* enqueues.

The reveal seam (`on_pii_revealed`) runs two effects, in order: the request-session
enqueue **first**, then the own-session audit write (the Epic 8 ordering). The audit
is its own immediately-committing session, so the two cannot share a transaction;
ordering the request-transaction enqueue before the own-session audit gives the
cleanest no-orphan behavior (a failing audit write rolls the request transaction
back, undoing the not-yet-committed outbox row).

This drives a create + reveal over the real DB-backed client (the same `seeded` +
`db_client` substrate the other endpoint tests use), logging in as the seeded
Sunshine Agent, and reads the outbox back to prove:

- **Happy path** — a reveal writes exactly one `pii.revealed` outbox row to **that
  tenant's** schema, with the envelope identity/correlation fields stamped,
  `published_at` still NULL (the relay sets it later), and a payload carrying the
  entity reference plus the field *name* only (`{entity_type, entity_id, field}`).
- **No PII** — the revealed plaintext value (the real email returned to the caller)
  appears in **no** column of that outbox row — only the field *name* (`email`) does
  (the no-PII-snapshot contract; the PII-protection / tenant-isolation axis here).
- **Atomicity** — when the audit write (which runs *after* the enqueue) raises, the
  reveal request is rolled back, so no `pii.revealed` outbox row is left behind — the
  enqueue rode the request transaction and rolled back with it.

This mirrors `test_record_created_event.py`'s shape: a DB-backed client create +
reveal, read back through the SELECT-capable superuser `database_engine` connection
(schema-qualified — the tenant role is INSERT-only on its own `outbox`), pinned by
the created record id via `payload->>'entity_id'` (the event id is minted inside the
seam, so it is not known to the test). `pytest.ini` sets `asyncio_mode = auto`, so
these async tests carry no `@pytest.mark.asyncio` decorator. The `seeded` /
`db_client` fixtures and the `login_as` helper are reused by name from
`test_endpoints_db.py`.
"""

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

import app.pii.reveal_seam as reveal_seam_module
from app.events.catalog import SCHEMA_VERSION, EventType
from app.models.user import Role
from app.tenancy.registry import SUNSHINE

from .test_endpoints_db import (  # noqa: F401 — `seeded` fixture is used by name
    login_as,
    seeded,
)

# The create body the reveal tests reuse. The `email` plaintext here is exactly
# what a successful `email` reveal returns to the caller — unmasked — so the no-PII
# assertion proves that revealed value never appears in the outbox row; only the
# field *name* (`email`) does.
REVEAL_RECORD_BODY = {
    "display_name": "Reveal Demo",
    "email": "reveal.demo@example.com",
    "date_of_birth": "1950-03-15",
    "phone": "+1 (415) 555-1234",
    "mock_medicare_id": "123-45-1234",
}
REVEALED_EMAIL_PLAINTEXT = REVEAL_RECORD_BODY["email"]


async def read_pii_revealed_rows_for_entity(database_engine, schema_name, entity_id):
    """Return all `pii.revealed` outbox rows for one entity id, as a list of rows.

    Mirrors `test_record_created_event.py::read_outbox_rows_for_entity` but keys on
    the `pii.revealed` event type: a full create also enqueues a `record.created`
    row for the same `entity_id`, so the event-type filter isolates the reveal's
    row. Reads through the SELECT-capable superuser engine connection (the tenant
    role is INSERT-only on its own `outbox`), schema-qualified.
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
                    "event_type": str(EventType.PII_REVEALED),
                    "entity_id": str(entity_id),
                },
            )
        ).all()


async def read_pii_revealed_row_as_mapping(database_engine, schema_name, entity_id):
    """Return the full `pii.revealed` outbox row for one entity id as a dict.

    Used by the no-PII proof: the whole row is read as a mapping (``SELECT *``) so
    the test can scan **every** column's value for the revealed plaintext — the
    assertion is that it appears nowhere, only the field name does.
    """
    async with database_engine.connect() as connection:
        rows = await connection.execute(
            text(
                f"SELECT * FROM {schema_name}.outbox "
                "WHERE event_type = :event_type "
                "AND payload->>'entity_id' = :entity_id"
            ),
            {
                "event_type": str(EventType.PII_REVEALED),
                "entity_id": str(entity_id),
            },
        )
        return [dict(row) for row in rows.mappings().all()]


async def count_pii_revealed_outbox_rows(database_engine, schema_name):
    """Return the total count of `pii.revealed` outbox rows in `schema_name`.

    The before/after count the atomicity test uses: the session-scoped container
    DB is never reset between tests, so the proof is that the failed reveal leaves
    the count **unchanged**, not that the table is empty.
    """
    async with database_engine.connect() as connection:
        return (
            await connection.execute(
                text(
                    f"SELECT count(*) FROM {schema_name}.outbox "
                    "WHERE event_type = :event_type"
                ),
                {"event_type": str(EventType.PII_REVEALED)},
            )
        ).scalar_one()


async def _create_record(db_client):
    """Create one full record as the logged-in caller; return its id."""
    create_response = await db_client.post("/api/pii-demo/", json=REVEAL_RECORD_BODY)
    assert create_response.status_code == 201
    return uuid.UUID(create_response.json()["record"]["id"])


# --- Phase 1: the enqueue lands one non-PII outbox row -----------------------


async def test_pii_demo_reveal_enqueues_pii_revealed(
    seeded, db_client, container_audit_session_factory, database_engine
):
    """A reveal enqueues exactly one tenant-scoped `pii.revealed` outbox row.

    The Sunshine Agent holds `REVEAL_PII`; a create then an `email` reveal → 200 and
    enqueues exactly one `pii.revealed` row into that tenant's own `outbox`, on the
    same request transaction as the reveal. The envelope identity/correlation fields
    are stamped, the actor is the Agent, `causation_id` / `demo_session_id` are NULL,
    `published_at` is still NULL (the relay sets it later), and the payload carries
    the entity reference plus the field *name* only — never the revealed value.
    """
    login_response = await login_as(db_client, Role.AGENT)
    assert login_response.status_code == 200
    actor_user_id = uuid.UUID(login_response.json()["user"]["id"])

    created_id = await _create_record(db_client)

    reveal_response = await db_client.post(
        f"/api/pii-demo/{created_id}/reveal", json={"field": "email"}
    )
    assert reveal_response.status_code == 200
    assert reveal_response.json() == {
        "field": "email",
        "value": REVEALED_EMAIL_PLAINTEXT,
    }

    rows = await read_pii_revealed_rows_for_entity(
        database_engine, SUNSHINE.schema_name, created_id
    )
    assert len(rows) == 1
    enqueued = rows[0]
    assert enqueued.event_type == str(EventType.PII_REVEALED)
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
        "field": "email",
    }


async def test_pii_revealed_outbox_row_carries_no_pii(
    seeded, db_client, container_audit_session_factory, database_engine
):
    """The revealed plaintext value appears nowhere in the `pii.revealed` row.

    The no-PII-snapshot contract (the PII-protection / tenant-isolation axis for
    this epic): a create then an `email` reveal enqueues a `pii.revealed` row whose
    **every** column value is scanned for the revealed plaintext (the real email
    returned to the caller) — it appears nowhere, only the field *name* (`email`)
    does, so the event itself never leaks the revealed PII.
    """
    login_response = await login_as(db_client, Role.AGENT)
    assert login_response.status_code == 200

    created_id = await _create_record(db_client)

    reveal_response = await db_client.post(
        f"/api/pii-demo/{created_id}/reveal", json={"field": "email"}
    )
    assert reveal_response.status_code == 200
    assert reveal_response.json()["value"] == REVEALED_EMAIL_PLAINTEXT

    rows_as_mappings = await read_pii_revealed_row_as_mapping(
        database_engine, SUNSHINE.schema_name, created_id
    )
    assert len(rows_as_mappings) == 1
    row = rows_as_mappings[0]
    for value in row.values():
        assert REVEALED_EMAIL_PLAINTEXT not in str(value)

    # The field *name* `email` is carried (it is not PII) — proving the row is the
    # reveal's, and that only the name, not the value, rides the event.
    assert row["payload"]["field"] == "email"


# --- Phase 2: atomicity — the enqueue rolls back with the reveal -------------


async def test_failed_reveal_enqueues_no_outbox_row(
    seeded, db_client, container_audit_session_factory, database_engine, monkeypatch
):
    """A failing audit write rolls the reveal back — no `pii.revealed` row lands.

    The enqueue rides the request transaction and sits **before** the audit write
    (its own session that commits immediately). Monkeypatching the seam's
    `record_audit_event` to raise makes the reveal error after the enqueue's flush;
    the exception propagates through `get_tenant_db`, which rolls back the request
    transaction — undoing the not-yet-committed outbox row (no orphan). The proof is
    that the `pii.revealed` outbox count for the tenant is unchanged across the
    failed request.

    The test's `ASGITransport` re-raises an unhandled handler exception to the
    caller (the Epic 8 idiom); `record_audit_event` is imported into the seam's
    namespace and runs **after** the enqueue, so patching it there is the failure
    injection point.
    """
    login_response = await login_as(db_client, Role.AGENT)
    assert login_response.status_code == 200

    created_id = await _create_record(db_client)

    count_before = await count_pii_revealed_outbox_rows(
        database_engine, SUNSHINE.schema_name
    )

    monkeypatch.setattr(
        reveal_seam_module,
        "record_audit_event",
        AsyncMock(side_effect=RuntimeError("audit write failed")),
    )

    with pytest.raises(RuntimeError, match="audit write failed"):
        await db_client.post(
            f"/api/pii-demo/{created_id}/reveal", json={"field": "email"}
        )

    count_after = await count_pii_revealed_outbox_rows(
        database_engine, SUNSHINE.schema_name
    )
    assert count_after == count_before
