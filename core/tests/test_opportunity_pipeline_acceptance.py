"""End-to-end acceptance for the P2.2 opportunity pipeline, on the real substrate.

Drives the real `/api/opportunities` endpoints over the DB-backed client (real
Postgres + RabbitMQ via the `seeded` / `db_client` / `database_engine` substrate)
and reads the stored rows / outbox events back over the superuser engine. Proves
the whole phase as one named suite (mirroring `test_lead_conversion_acceptance.py`):

- the **machine** — advancing the full enabled spine, an invalid multi-step move
  refused, and Lost terminal;
- the **Medicare gate** — under-65 blocked from Quoted (422), allowed at 65+;
- **per-tenant config + the Florida skip** — Florida's 6 relabeled stages and the
  Submitted → Policy Active skip;
- **isolation** — a foreign demo-session opportunity is a 404, and a Florida
  opportunity never appears on a Sunshine caller's board;
- **events** — both `opportunity.stage_changed` and `opportunity.lost` land on the
  outbox carrying `tenant_id`, the caller's `demo_session_id`, and the forwarded
  `correlation_id` (the opportunity's).

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no decorator.
The opportunity-creation + mutation helpers are reused by name from
`test_opportunity_stage.py`; the outbox reader from `test_lead_intake.py`.
"""

from sqlalchemy import text

from app.demo.session import DEMO_SESSION_COOKIE_NAME
from app.events.catalog import EventType
from app.tenancy.registry import FLORIDA, SUNSHINE

from tests.test_endpoints_db import seeded  # noqa: F401
from tests.test_lead_convert import read_one
from tests.test_lead_intake import read_outbox_rows_for_entity
from tests.test_lead_reads import (
    login_agent_for_slug,
    mint_live_demo_session,
    tenant_id_for_slug,
)
from tests.test_opportunity_stage import (
    convert_opportunity_for_slug,
    set_contact_age_band,
    set_opportunity_session,
    set_stage,
)


async def read_opportunity_correlation_id(database_engine, schema_name, opportunity_id):
    """Return the opportunity's own correlation id (the events must forward it)."""
    row = await read_one(
        database_engine,
        f"SELECT correlation_id FROM {schema_name}.opportunities WHERE id = :id",
        {"id": opportunity_id},
    )
    return row.correlation_id


async def advance(db_client, opportunity_id, target_stage):
    return await db_client.post(
        f"/api/opportunities/{opportunity_id}/stage",
        json={"target_stage": target_stage},
    )


# --- The machine ------------------------------------------------------------


async def test_machine_walks_the_full_enabled_spine(
    seeded, db_client, database_engine
):
    """A Sunshine opportunity advances one-by-one along the whole enabled spine."""
    opportunity_id = await convert_opportunity_for_slug(
        db_client, database_engine, SUNSHINE, "final_expense"
    )
    spine = [
        "Qualified",
        "Quoted",
        "Application Started",
        "Submitted",
        "Approved",
        "Policy Active",
    ]
    for target in spine:
        response = await advance(db_client, opportunity_id, target)
        assert response.status_code == 200, target
        assert response.json()["opportunity"]["stage"] == target


async def test_invalid_multi_step_move_is_refused(
    seeded, db_client, database_engine
):
    """A multi-step skip (New → Approved) is a 409."""
    opportunity_id = await convert_opportunity_for_slug(
        db_client, database_engine, SUNSHINE, "final_expense"
    )
    assert (await advance(db_client, opportunity_id, "Approved")).status_code == 409


async def test_lost_is_terminal(seeded, db_client, database_engine):
    """Marking Lost succeeds, then every further move is a 409."""
    opportunity_id = await convert_opportunity_for_slug(
        db_client, database_engine, SUNSHINE, "final_expense"
    )
    assert (await advance(db_client, opportunity_id, "Lost")).status_code == 200
    assert (await advance(db_client, opportunity_id, "Qualified")).status_code == 409


# --- The Medicare gate ------------------------------------------------------


async def test_medicare_gate_blocks_under_65_then_allows_65_plus(
    seeded, db_client, database_engine
):
    """A Medicare line is 422 to Quoted under 65, and 200 once the contact is 65+."""
    opportunity_id = await convert_opportunity_for_slug(
        db_client, database_engine, SUNSHINE, "medicare_advantage"
    )
    await set_stage(database_engine, SUNSHINE.schema_name, opportunity_id, "Qualified")

    await set_contact_age_band(
        database_engine, SUNSHINE.schema_name, opportunity_id, "55-64"
    )
    assert (await advance(db_client, opportunity_id, "Quoted")).status_code == 422

    await set_contact_age_band(
        database_engine, SUNSHINE.schema_name, opportunity_id, "65+"
    )
    assert (await advance(db_client, opportunity_id, "Quoted")).status_code == 200


# --- Per-tenant config + the Florida skip -----------------------------------


async def test_florida_board_config_and_approved_skip(
    seeded, db_client, database_engine
):
    """Florida's board omits Approved (6 relabeled stages) and skips it in transitions."""
    opportunity_id = await convert_opportunity_for_slug(
        db_client, database_engine, FLORIDA, "term_life"
    )
    board = (await db_client.get("/api/opportunities")).json()
    keys = [stage["key"] for stage in board["pipeline"]["stages"]]
    assert "Approved" not in keys
    assert len(keys) == 6
    labels = {stage["key"]: stage["label"] for stage in board["pipeline"]["stages"]}
    assert labels["Quoted"] == "Proposal Sent"
    assert labels["Application Started"] == "App In Progress"

    await set_stage(database_engine, FLORIDA.schema_name, opportunity_id, "Submitted")
    assert (await advance(db_client, opportunity_id, "Approved")).status_code == 409
    assert (await advance(db_client, opportunity_id, "Policy Active")).status_code == 200


# --- Isolation --------------------------------------------------------------


async def test_foreign_session_opportunity_is_a_404(
    seeded, db_client, database_engine
):
    """A session-less caller cannot touch another session's opportunity (404)."""
    session_a = await mint_live_demo_session(database_engine)
    opportunity_id = await convert_opportunity_for_slug(
        db_client, database_engine, SUNSHINE, "final_expense"
    )
    await set_opportunity_session(
        database_engine, SUNSHINE.schema_name, opportunity_id, session_a
    )
    assert (await advance(db_client, opportunity_id, "Qualified")).status_code == 404


async def test_a_florida_opportunity_is_invisible_to_a_sunshine_caller(
    seeded, db_client, database_engine
):
    """Cross-tenant isolation: a Florida opportunity never lists on a Sunshine board."""
    florida_opportunity = await convert_opportunity_for_slug(
        db_client, database_engine, FLORIDA, "term_life"
    )
    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    board = (await db_client.get("/api/opportunities")).json()
    ids = {row["id"] for row in board["opportunities"]}
    assert str(florida_opportunity) not in ids


# --- Events on the outbox ---------------------------------------------------


async def test_stage_changed_event_carries_the_full_envelope(
    seeded, db_client, database_engine
):
    """An advance enqueues one stage_changed event with tenant + session + correlation."""
    session_a = await mint_live_demo_session(database_engine)
    opportunity_id = await convert_opportunity_for_slug(
        db_client, database_engine, SUNSHINE, "final_expense"
    )
    await set_opportunity_session(
        database_engine, SUNSHINE.schema_name, opportunity_id, session_a
    )
    db_client.cookies.set(DEMO_SESSION_COOKIE_NAME, str(session_a))

    assert (await advance(db_client, opportunity_id, "Qualified")).status_code == 200

    tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    correlation_id = await read_opportunity_correlation_id(
        database_engine, SUNSHINE.schema_name, opportunity_id
    )
    events = await read_outbox_rows_for_entity(
        database_engine,
        SUNSHINE.schema_name,
        EventType.OPPORTUNITY_STAGE_CHANGED,
        opportunity_id,
    )
    assert len(events) == 1
    event = events[0]
    assert event.tenant_id == tenant_id
    assert event.demo_session_id == session_a
    assert event.correlation_id == correlation_id


async def test_mark_lost_emits_both_events_forwarding_the_correlation_id(
    seeded, db_client, database_engine
):
    """Marking Lost enqueues both events, each forwarding the opportunity's correlation."""
    opportunity_id = await convert_opportunity_for_slug(
        db_client, database_engine, SUNSHINE, "final_expense"
    )
    correlation_id = await read_opportunity_correlation_id(
        database_engine, SUNSHINE.schema_name, opportunity_id
    )
    tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)

    assert (await advance(db_client, opportunity_id, "Lost")).status_code == 200

    stage_changed = await read_outbox_rows_for_entity(
        database_engine,
        SUNSHINE.schema_name,
        EventType.OPPORTUNITY_STAGE_CHANGED,
        opportunity_id,
    )
    lost = await read_outbox_rows_for_entity(
        database_engine,
        SUNSHINE.schema_name,
        EventType.OPPORTUNITY_LOST,
        opportunity_id,
    )
    assert len(stage_changed) == 1
    assert len(lost) == 1
    assert stage_changed[0].correlation_id == correlation_id
    assert lost[0].correlation_id == correlation_id
    assert lost[0].tenant_id == tenant_id
