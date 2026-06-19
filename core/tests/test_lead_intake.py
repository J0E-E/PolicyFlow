"""DB-backed proof of the agent lead-intake walking skeleton (Epic 7, P1.7).

Epics 1–6 stood up every lead building block (the event vocabulary, the state
machine, the per-tenant `leads` table + ORM, the product-line registry, the masked
read builder, the duplicate matcher) — but nothing created a lead yet. Epic 7 is
the first end-to-end intake slice: the authenticated `POST /api/leads` creates a
lead (born `Working`, owned by the entering agent, `agent_entered`), encrypts the
PII, runs the matcher, publishes `lead.created` (plus `lead.duplicate_detected` on
a match), and returns the masked lead.

This drives that create over the real DB-backed client (the same `seeded` +
`db_client` substrate the other endpoint tests use), logging in as the seeded
Sunshine Agent, and reads back over the SELECT-capable superuser `database_engine`
connection (schema-qualified — the tenant role is INSERT-only on its own `outbox`)
to prove:

- **Happy path** — an Agent create → 201 with the masked lead body; the stored row
  is born `Working` / owned by the Agent / `agent_entered`.
- **One non-PII `lead.created` event** — exactly one outbox row, with the right
  non-PII payload, `published_at` still NULL, the actor = the Agent, and no supplied
  plaintext anywhere in any column.
- **Duplicate path** — a second create matching the first sets the new lead's
  `duplicate_of_lead_id` and enqueues a `lead.duplicate_detected` event sharing the
  `lead.created` `correlation_id`.
- **Validation** — an unknown product-line key → 422; an empty product-line list →
  422.
- **RBAC** — Read-Only → 403; anonymous → 401.

This mirrors `test_record_created_event.py`'s shape (read back through the superuser
engine, pinned by the created lead id via `payload->>'entity_id'`). `pytest.ini`
sets `asyncio_mode = auto`, so these async tests carry no `@pytest.mark.asyncio`
decorator. The `seeded` / `db_client` fixtures and the `login_as` helper are reused
by name from `test_endpoints_db.py` and `conftest.py`.
"""

import uuid

from sqlalchemy import text

from app.events.catalog import SCHEMA_VERSION, EventType
from app.models.user import Role
from app.tenancy.registry import SUNSHINE

from tests.test_endpoints_db import login_as, seeded  # noqa: F401

# A full create body the happy-path tests reuse. Its plaintext values are the ones
# the no-PII assertion proves never appear in the outbox row. The product-line keys
# are real Sunshine keys (the seeded Agent's tenant), `phone` ends in `1234` so the
# last-4 masker has a known tail, and `date_of_birth` lands in the `65+` band.
FULL_LEAD_BODY = {
    "first_name": "Jane",
    "last_name": "Demo",
    "email": "jane.demo@example.com",
    "phone": "+1 (415) 555-1234",
    "date_of_birth": "1950-03-15",
    "zip_code": "33101",
    "product_lines_of_interest": ["medicare_advantage", "final_expense"],
    "street_address": "100 Demo Street",
    "preferred_contact_method": "email",
    "notes": "Prefers a morning callback.",
}

# The plaintext values that must never appear in any outbox-row column (the
# no-PII-snapshot contract). `age_band` is a coarse, already-unmasked bucket, not a
# PII value, so it is allowed in the payload and is not listed here.
SUPPLIED_PLAINTEXT_VALUES = [
    "Jane",
    "Demo",
    "jane.demo@example.com",
    "+1 (415) 555-1234",
    "1950-03-15",
    "100 Demo Street",
    "Prefers a morning callback.",
]


def lead_body_with(**overrides) -> dict:
    """Return a copy of `FULL_LEAD_BODY` with `overrides` applied.

    A fresh dict per call so a test never mutates the shared body. Tests that need a
    distinct lead (so the shared, never-reset container DB cannot cross-match) pass a
    unique `email` / `phone`.
    """
    body = dict(FULL_LEAD_BODY)
    body.update(overrides)
    return body


def unique_contact() -> tuple[str, str]:
    """Return a (email, phone) pair unique to one test, to avoid cross-test matches.

    The container database is shared across the session, so a test that must control
    whether a duplicate is found owns its match targets by suffixing both fields with
    a random token — no other test's (or the seed's) leads can fingerprint the same.
    """
    token = uuid.uuid4().hex[:12]
    return (f"intake-{token}@example.com", f"+1 (415) 555-{token[:4]}")


async def read_lead_row(database_engine, schema_name, lead_id):
    """Return one lead row (selected columns) from `<schema_name>.leads` as a row.

    Reads through the SELECT-capable superuser engine connection (the tenant role's
    grants are scoped), schema-qualified — the same faithful-reader substrate the
    Epic 3/6 lead tests use. Keyed on the lead id from the create response.
    """
    async with database_engine.connect() as connection:
        return (
            await connection.execute(
                text(
                    "SELECT id, status, lead_source, owner_user_id, owner_username, "
                    "correlation_id, duplicate_of_lead_id, demo_session_id "
                    f"FROM {schema_name}.leads WHERE id = :id"
                ),
                {"id": lead_id},
            )
        ).one()


async def read_outbox_rows_for_entity(
    database_engine, schema_name, event_type, entity_id
):
    """Return all outbox rows of `event_type` for one entity id, as a list of rows.

    Mirrors `test_record_created_event.py::read_outbox_rows_for_entity` but is
    event-type-parameterized so the same helper reads `lead.created` and
    `lead.duplicate_detected`. Keyed on the payload's `entity_id` (the event id is
    minted inside the handler, so the test never sees it). Reads through the
    SELECT-capable superuser engine connection, schema-qualified.
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
                {"event_type": str(event_type), "entity_id": str(entity_id)},
            )
        ).all()


async def read_outbox_row_as_mapping(
    database_engine, schema_name, event_type, entity_id
):
    """Return the full outbox row(s) of `event_type` for one entity id as dicts.

    Used by the no-PII proof: the whole row is read as a mapping (``SELECT *``) so
    the test can scan **every** column's value for the supplied plaintext.
    """
    async with database_engine.connect() as connection:
        rows = await connection.execute(
            text(
                f"SELECT * FROM {schema_name}.outbox "
                "WHERE event_type = :event_type "
                "AND payload->>'entity_id' = :entity_id"
            ),
            {"event_type": str(event_type), "entity_id": str(entity_id)},
        )
        return [dict(row) for row in rows.mappings().all()]


# --- Phase 1: happy path — masked body + born state --------------------------


async def test_agent_create_returns_masked_lead(seeded, db_client):
    """An Agent creates a lead → 201 with the masked lead body (the read shape).

    The Sunshine Agent holds `CREATE_EDIT_RECORDS`; a full-body create → 201 and the
    response is the single masked read shape: plaintext names / `age_band` /
    `zip_code` / product-line keys / `lead_source` / `status`, a masked `email` and
    `phone`, the constant `****-**-**` date of birth, and `***` for the present
    street address. The lead is born `Working` / `agent_entered`, owned by the Agent.
    """
    login_response = await login_as(db_client, Role.AGENT)
    assert login_response.status_code == 200
    actor_user_id = login_response.json()["user"]["id"]

    # This masking-shape test submits the deterministic default body (not a
    # `unique_contact()` pair): the masked `email` / `phone` assertions below need
    # the known `jane.demo@example.com` / `…-1234` values. Masking is independent of
    # whether a duplicate is found, so a fixed body is safe here — only the tests
    # that assert duplicate behavior need per-test-unique contact details.
    response = await db_client.post("/api/leads", json=lead_body_with())

    assert response.status_code == 201
    lead = response.json()["lead"]
    assert lead["first_name"] == "Jane"
    assert lead["last_name"] == "Demo"
    assert lead["email"] == "j***@e***.com"
    assert lead["phone"] == "***-***-1234"
    assert lead["date_of_birth"] == "****-**-**"
    assert lead["age_band"] == "65+"
    assert lead["zip_code"] == "33101"
    assert lead["street_address"] == "***"
    assert lead["product_lines_of_interest"] == [
        "medicare_advantage",
        "final_expense",
    ]
    assert lead["lead_source"] == "agent_entered"
    assert lead["status"] == "Working"
    assert lead["owner_user_id"] == actor_user_id
    # The masked read never leaks the internal trace / matching columns.
    assert "correlation_id" not in lead
    assert "email_blind_index" not in lead
    assert "demo_session_id" not in lead


async def test_agent_create_row_is_born_working_owned_agent_entered(
    seeded, db_client, database_engine
):
    """The stored row is born `Working`, owned by the Agent, `agent_entered`.

    Reads the row back through the superuser engine and asserts the born framing the
    masked body only partly shows: `status = Working`, `lead_source = agent_entered`,
    `owner_user_id` / `owner_username` = the entering Agent, a non-null
    `correlation_id`, and a null `demo_session_id` (P1.8 owns its lifecycle).
    """
    login_response = await login_as(db_client, Role.AGENT)
    assert login_response.status_code == 200
    actor_user_id = uuid.UUID(login_response.json()["user"]["id"])
    actor_username = login_response.json()["user"]["username"]

    email, phone = unique_contact()
    response = await db_client.post(
        "/api/leads", json=lead_body_with(email=email, phone=phone)
    )
    assert response.status_code == 201
    created_id = uuid.UUID(response.json()["lead"]["id"])

    row = await read_lead_row(database_engine, SUNSHINE.schema_name, created_id)
    assert row.status == "Working"
    assert row.lead_source == "agent_entered"
    assert row.owner_user_id == actor_user_id
    assert row.owner_username == actor_username
    assert row.correlation_id is not None
    assert row.demo_session_id is None
    assert row.duplicate_of_lead_id is None


# --- Phase 2: the `lead.created` event ---------------------------------------


async def test_agent_create_enqueues_one_lead_created_event(
    seeded, db_client, database_engine
):
    """A create enqueues exactly one tenant-scoped `lead.created` outbox row.

    Exactly one `lead.created` row lands in the Agent's own tenant `outbox`, on the
    same request transaction as the insert. The envelope identity fields are stamped,
    the actor is the Agent, `causation_id` / `demo_session_id` are NULL,
    `published_at` is still NULL (the relay sets it later), and the payload carries
    the entity reference plus the non-PII descriptors (`lead_source`, `status`, the
    product-line keys, the coarse `age_band`) — never a PII value.
    """
    login_response = await login_as(db_client, Role.AGENT)
    assert login_response.status_code == 200
    actor_user_id = uuid.UUID(login_response.json()["user"]["id"])

    email, phone = unique_contact()
    response = await db_client.post(
        "/api/leads", json=lead_body_with(email=email, phone=phone)
    )
    assert response.status_code == 201
    created_id = uuid.UUID(response.json()["lead"]["id"])
    age_band = response.json()["lead"]["age_band"]

    rows = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.LEAD_CREATED, created_id
    )
    assert len(rows) == 1
    enqueued = rows[0]
    assert enqueued.event_type == str(EventType.LEAD_CREATED)
    assert enqueued.schema_version == SCHEMA_VERSION
    assert enqueued.tenant_id is not None
    assert enqueued.actor_user_id == actor_user_id
    assert enqueued.actor_role == Role.AGENT
    assert enqueued.correlation_id is not None
    assert enqueued.causation_id is None
    assert enqueued.demo_session_id is None
    assert enqueued.published_at is None
    assert enqueued.payload == {
        "entity_type": "lead",
        "entity_id": str(created_id),
        "lead_source": "agent_entered",
        "status": "Working",
        "product_lines_of_interest": ["medicare_advantage", "final_expense"],
        "age_band": age_band,
    }


async def test_lead_created_outbox_row_carries_no_pii(
    seeded, db_client, database_engine
):
    """No supplied plaintext value appears anywhere in the `lead.created` row.

    The no-PII-snapshot contract: a full-body create enqueues a `lead.created` row
    whose **every** column value is scanned for each supplied plaintext (names,
    email, phone, exact date of birth, street address, notes) — none appears
    anywhere, only the non-PII descriptors do, so the event itself never leaks PII.
    """
    login_response = await login_as(db_client, Role.AGENT)
    assert login_response.status_code == 200

    email, phone = unique_contact()
    response = await db_client.post(
        "/api/leads", json=lead_body_with(email=email, phone=phone)
    )
    assert response.status_code == 201
    created_id = uuid.UUID(response.json()["lead"]["id"])

    rows_as_mappings = await read_outbox_row_as_mapping(
        database_engine, SUNSHINE.schema_name, EventType.LEAD_CREATED, created_id
    )
    assert len(rows_as_mappings) == 1
    # The unique per-test email/phone are PII too — they must not leak either.
    plaintext_values = SUPPLIED_PLAINTEXT_VALUES + [email, phone]
    for value in rows_as_mappings[0].values():
        for plaintext in plaintext_values:
            assert plaintext not in str(value)


# --- Phase 3: the duplicate path ---------------------------------------------


async def test_second_matching_create_flags_duplicate_and_enqueues_event(
    seeded, db_client, database_engine
):
    """A second create matching the first flags it and enqueues `lead.duplicate_detected`.

    Two creates sharing the same email/phone: the first lands cleanly; the second is
    matched against it, so the second lead's `duplicate_of_lead_id` is set to the
    first lead's id and a single `lead.duplicate_detected` event is enqueued. That
    event's payload carries the new lead's `entity_id` and the matched
    `duplicate_of_lead_id`, and it shares the `correlation_id` of the second lead's
    own `lead.created` event (one lead's events share one trace id).
    """
    assert (await login_as(db_client, Role.AGENT)).status_code == 200

    email, phone = unique_contact()
    first_response = await db_client.post(
        "/api/leads", json=lead_body_with(email=email, phone=phone)
    )
    assert first_response.status_code == 201
    first_id = uuid.UUID(first_response.json()["lead"]["id"])

    second_response = await db_client.post(
        "/api/leads", json=lead_body_with(email=email, phone=phone)
    )
    assert second_response.status_code == 201
    second_id = uuid.UUID(second_response.json()["lead"]["id"])

    # The second lead's row records the linkage to the first.
    second_row = await read_lead_row(
        database_engine, SUNSHINE.schema_name, second_id
    )
    assert second_row.duplicate_of_lead_id == first_id

    # Exactly one `lead.duplicate_detected` event for the second lead, payload
    # naming the matched prior lead.
    duplicate_rows = await read_outbox_rows_for_entity(
        database_engine,
        SUNSHINE.schema_name,
        EventType.LEAD_DUPLICATE_DETECTED,
        second_id,
    )
    assert len(duplicate_rows) == 1
    duplicate_event = duplicate_rows[0]
    assert duplicate_event.payload == {
        "entity_id": str(second_id),
        "duplicate_of_lead_id": str(first_id),
    }

    # The duplicate event shares the second lead's `lead.created` correlation id.
    created_rows = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.LEAD_CREATED, second_id
    )
    assert len(created_rows) == 1
    assert duplicate_event.correlation_id == created_rows[0].correlation_id


async def test_first_create_does_not_flag_a_duplicate(
    seeded, db_client, database_engine
):
    """A first, non-matching create flags nothing and enqueues no duplicate event.

    The complement of the duplicate path: a lead with contact details no prior lead
    shares leaves `duplicate_of_lead_id` null and enqueues **no**
    `lead.duplicate_detected` event — only the `lead.created` event lands.
    """
    assert (await login_as(db_client, Role.AGENT)).status_code == 200

    email, phone = unique_contact()
    response = await db_client.post(
        "/api/leads", json=lead_body_with(email=email, phone=phone)
    )
    assert response.status_code == 201
    created_id = uuid.UUID(response.json()["lead"]["id"])

    row = await read_lead_row(database_engine, SUNSHINE.schema_name, created_id)
    assert row.duplicate_of_lead_id is None

    duplicate_rows = await read_outbox_rows_for_entity(
        database_engine,
        SUNSHINE.schema_name,
        EventType.LEAD_DUPLICATE_DETECTED,
        created_id,
    )
    assert duplicate_rows == []


# --- Phase 4: validation -----------------------------------------------------


async def test_unknown_product_line_key_is_422(seeded, db_client):
    """A product-line key the caller's tenant does not offer → 422.

    `not_a_real_line` is not one of Sunshine's registry keys, so the create is
    rejected with a 422 before any lead is written — the tenant-aware key-membership
    check the router owns.
    """
    assert (await login_as(db_client, Role.AGENT)).status_code == 200

    email, phone = unique_contact()
    response = await db_client.post(
        "/api/leads",
        json=lead_body_with(
            email=email,
            phone=phone,
            product_lines_of_interest=["medicare_advantage", "not_a_real_line"],
        ),
    )

    assert response.status_code == 422


async def test_other_tenant_product_line_key_is_422(seeded, db_client):
    """A real key from a *different* tenant is still rejected → 422.

    `term_life` is a real Florida key but not a Sunshine one, so a Sunshine Agent
    submitting it is rejected — the check is membership in the *caller's* tenant set,
    not global key validity.
    """
    assert (await login_as(db_client, Role.AGENT)).status_code == 200

    email, phone = unique_contact()
    response = await db_client.post(
        "/api/leads",
        json=lead_body_with(
            email=email, phone=phone, product_lines_of_interest=["term_life"]
        ),
    )

    assert response.status_code == 422


async def test_empty_product_line_list_is_422(seeded, db_client):
    """An empty `product_lines_of_interest` list → 422 (the ≥1 structural rule)."""
    assert (await login_as(db_client, Role.AGENT)).status_code == 200

    email, phone = unique_contact()
    response = await db_client.post(
        "/api/leads",
        json=lead_body_with(
            email=email, phone=phone, product_lines_of_interest=[]
        ),
    )

    assert response.status_code == 422


# --- Phase 5: RBAC -----------------------------------------------------------


async def test_create_forbidden_for_read_only(seeded, db_client):
    """A Read-Only user lacks `CREATE_EDIT_RECORDS` → 403."""
    assert (await login_as(db_client, Role.READ_ONLY)).status_code == 200

    email, phone = unique_contact()
    response = await db_client.post(
        "/api/leads", json=lead_body_with(email=email, phone=phone)
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "insufficient permissions"}


async def test_create_unauthenticated_is_401(seeded, db_client):
    """A fresh client with no session cookie → 401."""
    email, phone = unique_contact()
    response = await db_client.post(
        "/api/leads", json=lead_body_with(email=email, phone=phone)
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}
