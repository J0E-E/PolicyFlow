"""Lead-conversion acceptance suite for P2.1 (Epic 11).

The phase's named acceptance proof: the whole conversion slice works end-to-end on the
real substrate. It is **add-only** — it asserts the end-to-end *narrative* and the
cross-cutting invariants, and deliberately does not re-run the focused per-epic
matrices (the convert guards live in `test_lead_convert.py`, the summary read in
`test_lead_conversion_read.py`, the prefill in `test_lead_conversion_prefill.py`, the
household search in `test_household_search.py`, the purge in `test_conversion_purge.py`).

The phases (each independently reviewable):

- **Phase 1 — happy-path conversion (HTTP):** a held `Qualified` lead with notes and two
  product lines converts → a Household + Contact + two Opportunities + a note-Task exist,
  the lead is frozen `Converted`, the four event types (incl `opportunity.created` ×2)
  all share the lead's `correlation_id`, the "Converted to" summary reads back, and the
  frozen lead refuses a resolve-duplicate (409).
- **Phase 2 — duplicate pre-select + new Contact (HTTP):** a lead flagged a duplicate of a
  converted prior pre-selects the prior's household; linking there opens a **new** Contact
  in the **same** household with no second `household.created`.
- **Phase 3 — forced-failure rollback (HTTP + monkeypatch):** a failure injected into a
  mid-convert step rolls the whole transaction back — the lead stays `Qualified` and not
  one converted-world row survives.
- **Phase 4 — cross-session isolation + purge (HTTP + purge engine):** a conversion done
  inside one demo session is invisible to another session's read (404), and a session
  reset removes that session's conversion entities.

`pytest.ini` sets `asyncio_mode = auto`, so the async tests carry no decorator. Seams
reused by name from the per-epic conversion tests.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.leads.conversion as conversion_module
from app.demo import purge as purge_module
from app.demo.purge import Session, purge_sessions
from app.demo.session import DEMO_SESSION_COOKIE_NAME
from app.events.catalog import EventType
from app.leads.state import LeadStatus
from app.tenancy.registry import SUNSHINE

from tests.test_endpoints_db import login_as, seeded  # noqa: F401
from tests.test_lead_convert import (
    SUNSHINE_PRODUCT_LINES,
    convert_body,
    login_agent_and_insert_qualified_lead,
    read_all,
    read_one,
)
from tests.test_lead_intake import read_outbox_rows_for_entity
from tests.test_lead_reads import (
    insert_lead,
    login_agent_for_slug,
    mint_live_demo_session,
    tenant_id_for_slug,
    unique_contact,
    unique_marker,
)


@pytest.fixture
def container_purge_session_factory(database_engine, monkeypatch):
    """Point `app.demo.purge.session_factory` at the migrated container database."""
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    monkeypatch.setattr(purge_module, "session_factory", session_factory)
    return session_factory


async def household_id_for_contact(database_engine, contact_id):
    """Return the household id a contact rolls up to."""
    row = await read_one(
        database_engine,
        f"SELECT household_id FROM {SUNSHINE.schema_name}.contacts WHERE id = :id",
        {"id": contact_id},
    )
    return row.household_id


# --- Phase 1: happy-path conversion ------------------------------------------


async def test_happy_path_conversion_end_to_end(
    seeded, db_client, database_engine
):
    """A full conversion writes every entity, freezes the lead, and emits four events."""
    _, lead_id, _ = await login_agent_and_insert_qualified_lead(
        db_client, database_engine, notes="Call in the morning."
    )
    correlation_id = (
        await read_one(
            database_engine,
            f"SELECT correlation_id FROM {SUNSHINE.schema_name}.leads WHERE id = :id",
            {"id": lead_id},
        )
    ).correlation_id

    response = await db_client.post(
        f"/api/leads/{lead_id}/convert", json=convert_body()
    )
    assert response.status_code == 200
    frozen = response.json()["lead"]
    assert frozen["status"] == "Converted"
    contact_id = uuid.UUID(frozen["converted_contact_id"])
    opportunity_ids = [uuid.UUID(o) for o in frozen["converted_opportunity_ids"]]
    household_id = await household_id_for_contact(database_engine, contact_id)

    # Every entity exists: a household, the contact, two opportunities, one note-task.
    assert len(opportunity_ids) == len(SUNSHINE_PRODUCT_LINES)
    tasks = await read_all(
        database_engine,
        f"SELECT id FROM {SUNSHINE.schema_name}.tasks WHERE related_entity_id = :id",
        {"id": contact_id},
    )
    assert len(tasks) == 1

    # The four event types, all sharing the lead's correlation id.
    household_events = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.HOUSEHOLD_CREATED, household_id
    )
    contact_events = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.CONTACT_CREATED, contact_id
    )
    converted_events = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.LEAD_CONVERTED, lead_id
    )
    opportunity_events = []
    for opportunity_id in opportunity_ids:
        opportunity_events += await read_outbox_rows_for_entity(
            database_engine,
            SUNSHINE.schema_name,
            EventType.OPPORTUNITY_CREATED,
            opportunity_id,
        )
    assert len(household_events) == 1
    assert len(contact_events) == 1
    assert len(converted_events) == 1
    assert len(opportunity_events) == len(SUNSHINE_PRODUCT_LINES)
    every_event = (
        household_events + contact_events + converted_events + opportunity_events
    )
    assert all(event.correlation_id == correlation_id for event in every_event)

    # The "Converted to" summary reads back...
    summary = (await db_client.get(f"/api/leads/{lead_id}/conversion")).json()
    assert summary["contact"]["last_name"] == "Reader"
    assert summary["household"]["name"] == "Reader Household"
    assert len(summary["opportunities"]) == len(SUNSHINE_PRODUCT_LINES)

    # ...and the frozen lead refuses a mutating resolve-duplicate.
    refuse = await db_client.post(
        f"/api/leads/{lead_id}/resolve-duplicate", json={"action": "new"}
    )
    assert refuse.status_code == 409


# --- Phase 2: duplicate pre-select + new Contact -----------------------------


async def test_duplicate_pre_select_links_a_new_contact_into_the_prior_household(
    seeded, db_client, database_engine
):
    """A duplicate of a converted prior pre-selects, then links a new contact into it."""
    _, prior_lead_id, _ = await login_agent_and_insert_qualified_lead(
        db_client, database_engine
    )
    prior_response = await db_client.post(
        f"/api/leads/{prior_lead_id}/convert", json=convert_body()
    )
    assert prior_response.status_code == 200
    prior_contact_id = uuid.UUID(
        prior_response.json()["lead"]["converted_contact_id"]
    )
    household_id = await household_id_for_contact(database_engine, prior_contact_id)

    # A second lead flagged as a duplicate of the converted prior.
    login_response = await login_agent_for_slug(db_client, SUNSHINE.slug)
    agent_id = uuid.UUID(login_response.json()["user"]["id"])
    tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    email, phone = unique_contact()
    duplicate_lead_id = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        tenant_id,
        first_name=unique_marker(),
        email=email,
        phone=phone,
        status=LeadStatus.QUALIFIED,
        owner_user_id=agent_id,
        owner_username="agent@sunshine.example",
        duplicate_of_lead_id=prior_lead_id,
    )

    # The prefill pre-selects the prior's household.
    prefill = (
        await db_client.get(f"/api/leads/{duplicate_lead_id}/conversion-prefill")
    ).json()
    assert prefill["preselected_household"]["id"] == str(household_id)

    # Linking there opens a NEW contact in the SAME household.
    link_response = await db_client.post(
        f"/api/leads/{duplicate_lead_id}/convert",
        json={
            "household": {"mode": "link", "household_id": str(household_id)},
            "product_lines": SUNSHINE_PRODUCT_LINES,
        },
    )
    assert link_response.status_code == 200
    new_contact_id = uuid.UUID(
        link_response.json()["lead"]["converted_contact_id"]
    )
    assert new_contact_id != prior_contact_id
    assert await household_id_for_contact(database_engine, new_contact_id) == household_id
    # No second household.created — the link reused the household.
    household_events = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.HOUSEHOLD_CREATED, household_id
    )
    assert len(household_events) == 1


# --- Phase 3: forced-failure rollback ----------------------------------------


async def test_forced_failure_rolls_the_whole_conversion_back(
    seeded, db_client, database_engine, monkeypatch
):
    """A failure mid-convert leaves the lead Qualified and writes no converted entities."""
    _, lead_id, _ = await login_agent_and_insert_qualified_lead(
        db_client, database_engine
    )
    correlation_id = (
        await read_one(
            database_engine,
            f"SELECT correlation_id FROM {SUNSHINE.schema_name}.leads WHERE id = :id",
            {"id": lead_id},
        )
    ).correlation_id

    real_enqueue_event = conversion_module.enqueue_event

    async def failing_enqueue_event(db, envelope):
        if envelope.event_type == EventType.LEAD_CONVERTED.value:
            raise RuntimeError("forced mid-convert failure")
        return await real_enqueue_event(db, envelope)

    monkeypatch.setattr(conversion_module, "enqueue_event", failing_enqueue_event)

    try:
        response = await db_client.post(
            f"/api/leads/{lead_id}/convert", json=convert_body()
        )
        assert response.status_code >= 500
    except RuntimeError:
        pass

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


# --- Phase 4: cross-session isolation + purge --------------------------------


async def test_cross_session_isolation_and_purge(
    seeded, db_client, database_engine, container_purge_session_factory
):
    """A session's conversion is invisible to another session, and purges cleanly."""
    session_id = await mint_live_demo_session(database_engine)
    _, lead_id, _ = await login_agent_and_insert_qualified_lead(
        db_client, database_engine, notes="x", demo_session_id=session_id
    )
    db_client.cookies.set(DEMO_SESSION_COOKIE_NAME, str(session_id))
    convert_response = await db_client.post(
        f"/api/leads/{lead_id}/convert", json=convert_body()
    )
    assert convert_response.status_code == 200

    # Another session cannot read this conversion — the foreign-session guard 404s it.
    other_session_id = await mint_live_demo_session(database_engine)
    db_client.cookies.set(DEMO_SESSION_COOKIE_NAME, str(other_session_id))
    foreign = await db_client.get(f"/api/leads/{lead_id}/conversion")
    assert foreign.status_code == 404

    # A reset of the original session removes its conversion entities.
    counts = await purge_sessions(Session(session_id), delete_session_row=False)
    assert counts.households_deleted[SUNSHINE.schema_name] >= 1
    assert counts.contacts_deleted[SUNSHINE.schema_name] >= 1
    remaining_contacts = await read_all(
        database_engine,
        f"SELECT id FROM {SUNSHINE.schema_name}.contacts "
        "WHERE demo_session_id = :sid",
        {"sid": session_id},
    )
    assert remaining_contacts == []
