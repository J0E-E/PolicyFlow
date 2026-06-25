"""DB-backed proof of the lead convert action (P2.1 Epic 4).

`POST /api/leads/{id}/convert` turns a held `Qualified` lead into the converted-world
entities — a new Household, a Contact mirroring the lead, one Opportunity per supplied
product line, and a note-Task when the lead has notes — freezes the lead `Converted`,
and publishes the four conversion events, all on **one** request transaction (atomic,
no commit). These drive the real endpoint over the DB-backed client (the same
`seeded` / `db_client` / `database_engine` substrate the other endpoint tests use) and
read the created rows / outbox events back over the superuser `database_engine`.

The controllable `Qualified`, owner-held start state (the create endpoint can never make
one for an arbitrary owner) is inserted directly through the shared `insert_lead` seam;
the convert request carries the product lines (the lead's own `product_lines_of_interest`
is not what drives the opportunities — the confirmed request list is).

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no decorator. Seams
reused by name: `insert_lead` / `login_agent_for_slug` / `tenant_id_for_slug` /
`unique_contact` / `unique_marker` / `mint_live_demo_session` from `test_lead_reads.py`;
`read_outbox_rows_for_entity` from `test_lead_intake.py`; `login_as` / `seeded` from
`test_endpoints_db.py`.
"""

import uuid

from sqlalchemy import text

import app.leads.conversion as conversion_module
from app.demo.session import DEMO_SESSION_COOKIE_NAME
from app.events.catalog import EventType
from app.leads.state import LeadStatus
from app.models.user import Role
from app.tenancy.registry import SUNSHINE

from tests.test_endpoints_db import login_as, seeded  # noqa: F401
from tests.test_lead_intake import read_outbox_rows_for_entity
from tests.test_lead_reads import (
    insert_lead,
    login_agent_for_slug,
    mint_live_demo_session,
    tenant_id_for_slug,
    unique_contact,
    unique_marker,
)

# Two real Sunshine product-line keys (registry order), so a conversion opens two
# opportunities and the per-row event count is meaningfully > 1.
SUNSHINE_PRODUCT_LINES = ["medicare_advantage", "medicare_supplement"]


async def login_agent_and_insert_qualified_lead(
    db_client, database_engine, *, notes: str | None = None, demo_session_id=None
):
    """Log in a Sunshine agent and insert a `Qualified` lead they own; return the ids.

    Returns `(tenant_id, lead_id, agent_id)`. The lead is owned by the logged-in agent
    so it clears the convert holder guard. `notes` (absent from the `insert_lead` seam)
    is applied with a follow-up UPDATE when supplied, so the note-Task branch can be
    exercised.
    """
    login_response = await login_agent_for_slug(db_client, SUNSHINE.slug)
    assert login_response.status_code == 200
    agent_id = uuid.UUID(login_response.json()["user"]["id"])

    tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    email, phone = unique_contact()
    lead_id = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        tenant_id,
        first_name=unique_marker(),
        email=email,
        phone=phone,
        status=LeadStatus.QUALIFIED,
        owner_user_id=agent_id,
        owner_username="agent@sunshine.example",
        demo_session_id=demo_session_id,
    )

    if notes is not None:
        async with database_engine.begin() as connection:
            await connection.execute(
                text(
                    f"UPDATE {SUNSHINE.schema_name}.leads "
                    "SET notes = :notes WHERE id = :id"
                ),
                {"notes": notes, "id": lead_id},
            )

    return tenant_id, lead_id, agent_id


async def read_one(database_engine, query, params):
    """Run a SELECT and return the single row (or None) over the superuser engine."""
    async with database_engine.connect() as connection:
        return (await connection.execute(text(query), params)).first()


async def read_all(database_engine, query, params):
    """Run a SELECT and return every row over the superuser engine."""
    async with database_engine.connect() as connection:
        return (await connection.execute(text(query), params)).fetchall()


def convert_body(product_lines=None):
    """The new-household convert request body with the given product lines."""
    return {
        "household": {"mode": "new"},
        "product_lines": product_lines
        if product_lines is not None
        else SUNSHINE_PRODUCT_LINES,
    }


# --- Phase 1: happy path -----------------------------------------------------


async def test_convert_returns_masked_frozen_lead(seeded, db_client, database_engine):
    """Converting a held `Qualified` lead → 200, frozen `Converted` with the refs set."""
    _, lead_id, _ = await login_agent_and_insert_qualified_lead(
        db_client, database_engine
    )

    response = await db_client.post(
        f"/api/leads/{lead_id}/convert", json=convert_body()
    )

    assert response.status_code == 200
    lead = response.json()["lead"]
    assert lead["status"] == "Converted"
    assert lead["converted_contact_id"] is not None
    # One opportunity per supplied product line, serialized as a list of uuid strings.
    assert len(lead["converted_opportunity_ids"]) == len(SUNSHINE_PRODUCT_LINES)
    assert all(isinstance(opp_id, str) for opp_id in lead["converted_opportunity_ids"])

    row = await read_one(
        database_engine,
        f"SELECT status, converted_contact_id FROM {SUNSHINE.schema_name}.leads "
        "WHERE id = :id",
        {"id": lead_id},
    )
    assert row.status == "Converted"
    assert row.converted_contact_id is not None


async def test_convert_creates_household_contact_and_opportunities(
    seeded, db_client, database_engine
):
    """A conversion writes the Household, the Contact, and one Opportunity per line."""
    tenant_id, lead_id, agent_id = await login_agent_and_insert_qualified_lead(
        db_client, database_engine
    )

    response = await db_client.post(
        f"/api/leads/{lead_id}/convert", json=convert_body()
    )
    assert response.status_code == 200
    contact_id = uuid.UUID(response.json()["lead"]["converted_contact_id"])

    contact = await read_one(
        database_engine,
        f"SELECT household_id, source_lead_id, owner_user_id, first_name "
        f"FROM {SUNSHINE.schema_name}.contacts WHERE id = :id",
        {"id": contact_id},
    )
    assert contact.source_lead_id == lead_id
    assert contact.owner_user_id == agent_id

    household = await read_one(
        database_engine,
        f"SELECT name FROM {SUNSHINE.schema_name}.households WHERE id = :id",
        {"id": contact.household_id},
    )
    # The household name is derived from the contact's (carried) last name — the
    # `insert_lead` seam fixes the lead's last name to "Reader".
    assert household.name == "Reader Household"

    opportunities = await read_all(
        database_engine,
        f"SELECT product_line, stage, origin, contact_id, household_id "
        f"FROM {SUNSHINE.schema_name}.opportunities WHERE contact_id = :id",
        {"id": contact_id},
    )
    assert {opp.product_line for opp in opportunities} == set(SUNSHINE_PRODUCT_LINES)
    assert all(opp.stage == "New" for opp in opportunities)
    assert all(opp.origin == "conversion" for opp in opportunities)
    assert all(opp.household_id == contact.household_id for opp in opportunities)


async def test_convert_creates_note_task_only_when_the_lead_has_notes(
    seeded, db_client, database_engine
):
    """A note-Task is written from `lead.notes`, and is absent when there are none."""
    # With notes -> one 'note' task hanging off the contact, body = the notes.
    _, lead_id, _ = await login_agent_and_insert_qualified_lead(
        db_client, database_engine, notes="Prefers a morning call."
    )
    response = await db_client.post(
        f"/api/leads/{lead_id}/convert", json=convert_body()
    )
    assert response.status_code == 200
    contact_id = uuid.UUID(response.json()["lead"]["converted_contact_id"])

    task = await read_one(
        database_engine,
        f"SELECT related_entity_type, related_entity_id, task_type, body "
        f"FROM {SUNSHINE.schema_name}.tasks WHERE related_entity_id = :id",
        {"id": contact_id},
    )
    assert task.related_entity_type == "contact"
    assert task.task_type == "note"
    assert task.body == "Prefers a morning call."

    # Without notes -> no task at all.
    _, lead_id_no_notes, _ = await login_agent_and_insert_qualified_lead(
        db_client, database_engine
    )
    response = await db_client.post(
        f"/api/leads/{lead_id_no_notes}/convert", json=convert_body()
    )
    assert response.status_code == 200
    contact_id_no_notes = uuid.UUID(response.json()["lead"]["converted_contact_id"])
    tasks = await read_all(
        database_engine,
        f"SELECT id FROM {SUNSHINE.schema_name}.tasks WHERE related_entity_id = :id",
        {"id": contact_id_no_notes},
    )
    assert tasks == []


async def test_convert_emits_the_four_event_types_sharing_the_correlation_id(
    seeded, db_client, database_engine
):
    """The convert enqueues household/contact/opportunity×N/lead.converted, one trace id."""
    _, lead_id, _ = await login_agent_and_insert_qualified_lead(
        db_client, database_engine
    )
    correlation_row = await read_one(
        database_engine,
        f"SELECT correlation_id FROM {SUNSHINE.schema_name}.leads WHERE id = :id",
        {"id": lead_id},
    )
    correlation_id = correlation_row.correlation_id

    response = await db_client.post(
        f"/api/leads/{lead_id}/convert", json=convert_body()
    )
    assert response.status_code == 200
    lead = response.json()["lead"]
    contact_id = uuid.UUID(lead["converted_contact_id"])
    opportunity_ids = [uuid.UUID(opp_id) for opp_id in lead["converted_opportunity_ids"]]
    household_row = await read_one(
        database_engine,
        f"SELECT household_id FROM {SUNSHINE.schema_name}.contacts WHERE id = :id",
        {"id": contact_id},
    )

    lead_converted = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.LEAD_CONVERTED, lead_id
    )
    contact_created = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.CONTACT_CREATED, contact_id
    )
    household_created = await read_outbox_rows_for_entity(
        database_engine,
        SUNSHINE.schema_name,
        EventType.HOUSEHOLD_CREATED,
        household_row.household_id,
    )
    opportunity_created = []
    for opportunity_id in opportunity_ids:
        opportunity_created += await read_outbox_rows_for_entity(
            database_engine,
            SUNSHINE.schema_name,
            EventType.OPPORTUNITY_CREATED,
            opportunity_id,
        )

    assert len(lead_converted) == 1
    assert len(contact_created) == 1
    assert len(household_created) == 1
    assert len(opportunity_created) == len(SUNSHINE_PRODUCT_LINES)

    every_event = (
        lead_converted + contact_created + household_created + opportunity_created
    )
    assert all(event.correlation_id == correlation_id for event in every_event)


# --- Phase 2: guards + edge cases --------------------------------------------


async def test_convert_by_a_non_holder_is_403(seeded, db_client, database_engine):
    """An agent who does not own the lead cannot convert it (403)."""
    tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    email, phone = unique_contact()
    # Owned by someone else entirely.
    lead_id = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        tenant_id,
        first_name=unique_marker(),
        email=email,
        phone=phone,
        status=LeadStatus.QUALIFIED,
        owner_user_id=uuid.uuid4(),
        owner_username="other@sunshine.example",
    )

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    response = await db_client.post(
        f"/api/leads/{lead_id}/convert", json=convert_body()
    )
    assert response.status_code == 403


async def test_convert_without_create_edit_capability_is_403(seeded, db_client):
    """A Read-Only user lacks `CREATE_EDIT_RECORDS`, so convert is a 403.

    The capability guard fires before any lead lookup, so no lead is needed — a
    Read-Only caller is refused outright (mirroring qualify/reject's RBAC test).
    """
    assert (await login_as(db_client, Role.READ_ONLY)).status_code == 200
    response = await db_client.post(
        f"/api/leads/{uuid.uuid4()}/convert", json=convert_body()
    )
    assert response.status_code == 403


async def test_convert_a_non_qualified_lead_is_409(seeded, db_client, database_engine):
    """A lead that is not `Qualified` cannot move to `Converted` (409)."""
    login_response = await login_agent_for_slug(db_client, SUNSHINE.slug)
    assert login_response.status_code == 200
    agent_id = uuid.UUID(login_response.json()["user"]["id"])
    tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    email, phone = unique_contact()
    lead_id = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        tenant_id,
        first_name=unique_marker(),
        email=email,
        phone=phone,
        status=LeadStatus.WORKING,
        owner_user_id=agent_id,
        owner_username="agent@sunshine.example",
    )

    response = await db_client.post(
        f"/api/leads/{lead_id}/convert", json=convert_body()
    )
    assert response.status_code == 409


async def test_convert_a_seed_lead_in_a_demo_session_is_409(
    seeded, db_client, database_engine
):
    """A demo-session caller cannot convert a shared seed lead (`demo_session_id IS NULL`)."""
    login_response = await login_agent_for_slug(db_client, SUNSHINE.slug)
    assert login_response.status_code == 200
    agent_id = uuid.UUID(login_response.json()["user"]["id"])
    tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    email, phone = unique_contact()
    # A seed row (demo_session_id is NULL) owned by the agent.
    lead_id = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        tenant_id,
        first_name=unique_marker(),
        email=email,
        phone=phone,
        status=LeadStatus.QUALIFIED,
        owner_user_id=agent_id,
        owner_username="agent@sunshine.example",
        demo_session_id=None,
    )

    # Put the caller in a live demo session, so the seed-row guard engages.
    session_id = await mint_live_demo_session(database_engine)
    db_client.cookies.set(DEMO_SESSION_COOKIE_NAME, str(session_id))

    response = await db_client.post(
        f"/api/leads/{lead_id}/convert", json=convert_body()
    )
    assert response.status_code == 409


async def test_convert_a_missing_lead_is_404(seeded, db_client, database_engine):
    """An id that does not exist in the caller's tenant is a 404."""
    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    response = await db_client.post(
        f"/api/leads/{uuid.uuid4()}/convert", json=convert_body()
    )
    assert response.status_code == 404


async def test_convert_with_an_unknown_product_line_is_422(
    seeded, db_client, database_engine
):
    """A product-line key the tenant does not offer is a 422."""
    _, lead_id, _ = await login_agent_and_insert_qualified_lead(
        db_client, database_engine
    )
    response = await db_client.post(
        f"/api/leads/{lead_id}/convert",
        json=convert_body(product_lines=["not_a_real_line"]),
    )
    assert response.status_code == 422


async def test_convert_with_no_product_lines_is_422(
    seeded, db_client, database_engine
):
    """An empty `product_lines` list is rejected structurally (422)."""
    _, lead_id, _ = await login_agent_and_insert_qualified_lead(
        db_client, database_engine
    )
    response = await db_client.post(
        f"/api/leads/{lead_id}/convert", json=convert_body(product_lines=[])
    )
    assert response.status_code == 422


async def test_convert_rolls_back_every_write_on_a_mid_convert_failure(
    seeded, db_client, database_engine, monkeypatch
):
    """A failure during the convert rolls the whole transaction back — nothing persists.

    `enqueue_event` is patched to raise on the final `lead.converted` emit, **after** the
    household, contact, and opportunities have been flushed. Because the convert holds no
    commit of its own, the request transaction rolls back: the lead stays `Qualified` and
    not one converted-world row survives — the transactional-outbox atomicity guarantee.
    """
    _, lead_id, _ = await login_agent_and_insert_qualified_lead(
        db_client, database_engine
    )
    correlation_row = await read_one(
        database_engine,
        f"SELECT correlation_id FROM {SUNSHINE.schema_name}.leads WHERE id = :id",
        {"id": lead_id},
    )
    correlation_id = correlation_row.correlation_id

    real_enqueue_event = conversion_module.enqueue_event

    async def failing_enqueue_event(db, envelope):
        if envelope.event_type == EventType.LEAD_CONVERTED.value:
            raise RuntimeError("forced mid-convert failure")
        return await real_enqueue_event(db, envelope)

    monkeypatch.setattr(conversion_module, "enqueue_event", failing_enqueue_event)

    # The forced failure surfaces either as a propagated server exception or a 5xx,
    # depending on the test transport; either way the transaction must roll back. The
    # rollback assertions below are the real proof.
    try:
        response = await db_client.post(
            f"/api/leads/{lead_id}/convert", json=convert_body()
        )
        assert response.status_code >= 500
    except RuntimeError:
        pass

    # The lead is untouched, and no household/contact/opportunity for it survives.
    lead_row = await read_one(
        database_engine,
        f"SELECT status, converted_contact_id FROM {SUNSHINE.schema_name}.leads "
        "WHERE id = :id",
        {"id": lead_id},
    )
    assert lead_row.status == "Qualified"
    assert lead_row.converted_contact_id is None

    households = await read_all(
        database_engine,
        f"SELECT id FROM {SUNSHINE.schema_name}.households "
        "WHERE correlation_id = :correlation_id",
        {"correlation_id": correlation_id},
    )
    assert households == []
    contacts = await read_all(
        database_engine,
        f"SELECT id FROM {SUNSHINE.schema_name}.contacts WHERE source_lead_id = :id",
        {"id": lead_id},
    )
    assert contacts == []
