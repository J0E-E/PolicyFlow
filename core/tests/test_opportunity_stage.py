"""DB-backed proof of the opportunity stage-change tracer (P2.2 Epic 2).

`GET /api/opportunities` lists the caller's converted opportunities (minimal rows
with the current stage + the server-computed next enabled stage), and
`POST /api/opportunities/{id}/stage` advances one opportunity, validated by the
pure machine, emitting `opportunity.stage_changed` on the request transaction.

These drive the real endpoints over the DB-backed client (the same `seeded` /
`db_client` / `database_engine` substrate the other endpoint tests use) and read
the stored row / outbox event back over the SELECT-capable superuser engine. The
opportunity under test is created the honest way — by converting a held `Qualified`
lead through the convert endpoint (P2.1) — so the tracer runs against a real
converted opportunity, owned by the converting agent, born at stage `New`.

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no decorator.
Seams reused by name: `login_agent_and_insert_qualified_lead` / `read_one` from
`test_lead_convert.py`; `read_outbox_rows_for_entity` from `test_lead_intake.py`;
`login_as` / `seeded` from `test_endpoints_db.py`.
"""

import uuid

from sqlalchemy import text

from app.demo.session import DEMO_SESSION_COOKIE_NAME
from app.events.catalog import EventType
from app.leads.state import LeadStatus
from app.models.user import Role
from app.tenancy.registry import FLORIDA, SUNSHINE

from tests.test_endpoints_db import login_as, seeded  # noqa: F401
from tests.test_lead_convert import (
    login_agent_and_insert_qualified_lead,
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


async def set_opportunity_session(
    database_engine, schema_name, opportunity_id, demo_session_id
):
    """Tag an opportunity with a demo session, to exercise session write-isolation."""
    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                f"UPDATE {schema_name}.opportunities SET demo_session_id = :sid "
                "WHERE id = :id"
            ),
            {"sid": demo_session_id, "id": opportunity_id},
        )


async def convert_opportunity_for_slug(db_client, database_engine, tenant, product_line):
    """Convert a held `Qualified` lead for `tenant` into one opportunity; return its id.

    The tenant-parameterized sibling of `convert_one_opportunity` (which is
    Sunshine-only): logs in that tenant's agent, inserts a `Qualified` lead they
    own with the given `product_line`, converts it, and returns the new
    opportunity's id. The `db_client` is left logged in as that agent.
    """
    login = await login_agent_for_slug(db_client, tenant.slug)
    assert login.status_code == 200
    agent_id = uuid.UUID(login.json()["user"]["id"])
    tenant_id = await tenant_id_for_slug(database_engine, tenant.slug)
    email, phone = unique_contact()
    lead_id = await insert_lead(
        database_engine,
        tenant.schema_name,
        tenant_id,
        first_name=unique_marker(),
        email=email,
        phone=phone,
        status=LeadStatus.QUALIFIED,
        owner_user_id=agent_id,
        owner_username=f"agent@{tenant.email_domain}",
    )
    response = await db_client.post(
        f"/api/leads/{lead_id}/convert",
        json={"household": {"mode": "new"}, "product_lines": [product_line]},
    )
    assert response.status_code == 200
    contact_id = uuid.UUID(response.json()["lead"]["converted_contact_id"])
    opportunity = await read_one(
        database_engine,
        f"SELECT id FROM {tenant.schema_name}.opportunities WHERE contact_id = :id",
        {"id": contact_id},
    )
    return opportunity.id


async def set_stage(database_engine, schema_name, opportunity_id, stage):
    """Force an opportunity to `stage` directly, to reach a mid-pipeline start state."""
    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                f"UPDATE {schema_name}.opportunities SET stage = :stage WHERE id = :id"
            ),
            {"stage": stage, "id": opportunity_id},
        )


async def set_contact_age_band(database_engine, schema_name, opportunity_id, age_band):
    """Set the age band on the opportunity's contact, to drive the Medicare gate."""
    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                f"UPDATE {schema_name}.contacts SET age_band = :band WHERE id = "
                f"(SELECT contact_id FROM {schema_name}.opportunities WHERE id = :id)"
            ),
            {"band": age_band, "id": opportunity_id},
        )


async def convert_one_opportunity(db_client, database_engine):
    """Convert a held `Qualified` Sunshine lead into one opportunity; return its ids.

    Returns `(agent_id, opportunity_id, contact_id, household_id)`. The opportunity
    is owned by the logged-in converting agent (so it clears the holder guard) and
    is born at stage `New`. The `db_client` is left logged in as that agent.
    """
    _, lead_id, agent_id = await login_agent_and_insert_qualified_lead(
        db_client, database_engine
    )
    response = await db_client.post(
        f"/api/leads/{lead_id}/convert",
        json={"household": {"mode": "new"}, "product_lines": ["medicare_advantage"]},
    )
    assert response.status_code == 200
    contact_id = uuid.UUID(response.json()["lead"]["converted_contact_id"])

    opportunity = await read_one(
        database_engine,
        f"SELECT id, household_id FROM {SUNSHINE.schema_name}.opportunities "
        "WHERE contact_id = :id",
        {"id": contact_id},
    )
    return agent_id, opportunity.id, contact_id, opportunity.household_id


def find_row(board, opportunity_id):
    """Pull the one board row matching `opportunity_id` from a GET board payload."""
    matches = [
        row for row in board["opportunities"] if row["id"] == str(opportunity_id)
    ]
    assert len(matches) == 1, matches
    return matches[0]


# --- Happy path: advance one stage, end to end -------------------------------


async def test_advance_moves_stage_and_emits_event(
    seeded, db_client, database_engine
):
    """Advancing `New → Qualified` → 200, the row moves, and one event is enqueued."""
    _, opportunity_id, contact_id, household_id = await convert_one_opportunity(
        db_client, database_engine
    )

    # The board shows the new opportunity at `New` with `Qualified` as its next stage.
    board = (await db_client.get("/api/opportunities")).json()
    row = find_row(board, opportunity_id)
    assert row["stage"] == "New"
    assert row["next_stage"] == "Qualified"

    response = await db_client.post(
        f"/api/opportunities/{opportunity_id}/stage",
        json={"target_stage": "Qualified"},
    )
    assert response.status_code == 200
    moved = response.json()["opportunity"]
    assert moved["stage"] == "Qualified"
    assert moved["next_stage"] == "Quoted"

    # The stored stage actually changed.
    stored = await read_one(
        database_engine,
        f"SELECT stage FROM {SUNSHINE.schema_name}.opportunities WHERE id = :id",
        {"id": opportunity_id},
    )
    assert stored.stage == "Qualified"

    # Exactly one `opportunity.stage_changed` event, non-PII payload, unpublished.
    events = await read_outbox_rows_for_entity(
        database_engine,
        SUNSHINE.schema_name,
        EventType.OPPORTUNITY_STAGE_CHANGED,
        opportunity_id,
    )
    assert len(events) == 1
    event = events[0]
    assert event.payload == {
        "entity_id": str(opportunity_id),
        "from_stage": "New",
        "to_stage": "Qualified",
        "contact_id": str(contact_id),
        "household_id": str(household_id),
    }
    assert event.correlation_id is not None
    assert event.published_at is None
    assert event.actor_role == Role.AGENT.value


# --- Guard rails -------------------------------------------------------------


async def test_change_stage_unknown_opportunity_is_404(
    seeded, db_client, database_engine
):
    """A stage move against an unknown / cross-tenant id is a 404."""
    await login_agent_and_insert_qualified_lead(db_client, database_engine)
    response = await db_client.post(
        f"/api/opportunities/{uuid.uuid4()}/stage",
        json={"target_stage": "Qualified"},
    )
    assert response.status_code == 404


async def test_illegal_move_is_409(seeded, db_client, database_engine):
    """A multi-step skip (`New → Submitted`) is refused with a 409."""
    _, opportunity_id, _, _ = await convert_one_opportunity(db_client, database_engine)
    response = await db_client.post(
        f"/api/opportunities/{opportunity_id}/stage",
        json={"target_stage": "Submitted"},
    )
    assert response.status_code == 409


async def test_unknown_stage_is_422(seeded, db_client, database_engine):
    """A `target_stage` that is not a known stage value is a 422."""
    _, opportunity_id, _, _ = await convert_one_opportunity(db_client, database_engine)
    response = await db_client.post(
        f"/api/opportunities/{opportunity_id}/stage",
        json={"target_stage": "Not A Stage"},
    )
    assert response.status_code == 422


async def test_change_stage_without_capability_is_403(seeded, db_client):
    """A Read-Only user lacks `CREATE_EDIT_RECORDS`, so a stage move is a 403.

    The capability guard fires before any lookup, so no opportunity is needed.
    """
    assert (await login_as(db_client, Role.READ_ONLY)).status_code == 200
    response = await db_client.post(
        f"/api/opportunities/{uuid.uuid4()}/stage",
        json={"target_stage": "Qualified"},
    )
    assert response.status_code == 403


async def test_non_owner_non_admin_agent_is_403(
    seeded, db_client, database_engine
):
    """A capable agent who neither owns the opportunity nor is an admin gets a 403."""
    _, opportunity_id, _, _ = await convert_one_opportunity(db_client, database_engine)
    # Flip ownership to someone else, leaving the caller a capable non-owner non-admin.
    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                f"UPDATE {SUNSHINE.schema_name}.opportunities "
                "SET owner_user_id = :other WHERE id = :id"
            ),
            {"other": uuid.uuid4(), "id": opportunity_id},
        )
    response = await db_client.post(
        f"/api/opportunities/{opportunity_id}/stage",
        json={"target_stage": "Qualified"},
    )
    assert response.status_code == 403


async def test_tenant_admin_can_advance_another_agents_opportunity(
    seeded, db_client, database_engine
):
    """A Tenant Admin may move an opportunity they do not own (owner-or-admin, D5)."""
    _, opportunity_id, _, _ = await convert_one_opportunity(db_client, database_engine)
    # Re-auth as the tenant admin (not the owning agent) and advance the card.
    assert (await login_as(db_client, Role.TENANT_ADMIN)).status_code == 200
    response = await db_client.post(
        f"/api/opportunities/{opportunity_id}/stage",
        json={"target_stage": "Qualified"},
    )
    assert response.status_code == 200
    assert response.json()["opportunity"]["stage"] == "Qualified"


# --- Board pipeline config (Epic 3) ------------------------------------------


async def test_board_carries_sunshine_pipeline_stages(seeded, db_client):
    """The board payload carries Sunshine's enabled, relabeled stages in order."""
    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    board = (await db_client.get("/api/opportunities")).json()
    stages = [
        (stage["key"], stage["label"], stage["is_optional"])
        for stage in board["pipeline"]["stages"]
    ]
    assert stages == [
        ("New", "New", False),
        ("Qualified", "Needs Assessment", False),
        ("Quoted", "Quoted", True),
        ("Application Started", "Application Started", False),
        ("Submitted", "Submitted", False),
        ("Approved", "Approved", True),
        ("Policy Active", "Enrolled", False),
    ]


async def test_board_carries_florida_pipeline_stages_with_approved_skipped(
    seeded, db_client
):
    """Florida's board omits the disabled Approved stage and uses its relabels."""
    assert (await login_agent_for_slug(db_client, FLORIDA.slug)).status_code == 200
    board = (await db_client.get("/api/opportunities")).json()
    keys = [stage["key"] for stage in board["pipeline"]["stages"]]
    assert "Approved" not in keys
    assert len(keys) == 6
    labels = {stage["key"]: stage["label"] for stage in board["pipeline"]["stages"]}
    assert labels["Quoted"] == "Proposal Sent"
    assert labels["Application Started"] == "App In Progress"


# --- Enabled-set skip semantics in transitions (Epic 4) ----------------------


def _board_row(board, opportunity_id):
    rows = [
        row for row in board["opportunities"] if row["id"] == str(opportunity_id)
    ]
    assert len(rows) == 1, rows
    return rows[0]


async def test_florida_submitted_skips_disabled_approved_to_policy_active(
    seeded, db_client, database_engine
):
    """Florida's board skips the disabled Approved stage; the skip-target is automation-owned.

    The board's `next_stage` still computes the skip (Submitted → Policy Active), but
    *Policy Active* is automation-owned, so the board suppresses Advance (`can_advance`
    is false) and a manual advance into it is a 422 (D6 lockdown).
    """
    opportunity_id = await convert_opportunity_for_slug(
        db_client, database_engine, FLORIDA, "term_life"
    )
    await set_stage(database_engine, FLORIDA.schema_name, opportunity_id, "Submitted")

    # The board's next_stage skips the disabled Approved stage, but Advance is
    # suppressed because the skip-target is automation-owned.
    board = (await db_client.get("/api/opportunities")).json()
    row = _board_row(board, opportunity_id)
    assert row["stage"] == "Submitted"
    assert row["next_stage"] == "Policy Active"
    assert row["can_advance"] is False

    # The disabled stage is an illegal target (409); the automation-owned skip-target
    # is a 422 (lifecycle-driven), never a manual 200.
    blocked = await db_client.post(
        f"/api/opportunities/{opportunity_id}/stage",
        json={"target_stage": "Approved"},
    )
    assert blocked.status_code == 409
    locked = await db_client.post(
        f"/api/opportunities/{opportunity_id}/stage",
        json={"target_stage": "Policy Active"},
    )
    assert locked.status_code == 422


async def test_sunshine_submitted_to_approved_is_lifecycle_locked(
    seeded, db_client, database_engine
):
    """Sunshine's board shows Approved as the next stage, but it is automation-owned.

    `next_stage` is *Approved* (no skip — it is enabled), yet a manual advance into it
    is a 422 and the board suppresses Advance (D6 lockdown).
    """
    opportunity_id = await convert_opportunity_for_slug(
        db_client, database_engine, SUNSHINE, "final_expense"
    )
    await set_stage(database_engine, SUNSHINE.schema_name, opportunity_id, "Submitted")

    board = (await db_client.get("/api/opportunities")).json()
    row = _board_row(board, opportunity_id)
    assert row["next_stage"] == "Approved"
    assert row["can_advance"] is False

    locked = await db_client.post(
        f"/api/opportunities/{opportunity_id}/stage",
        json={"target_stage": "Approved"},
    )
    assert locked.status_code == 422


# --- Medicare eligibility gate (Epic 5) --------------------------------------


async def test_medicare_gate_blocks_under_65_entry_to_quoted(
    seeded, db_client, database_engine
):
    """A Medicare line + under-65 contact → Quoted is refused with a 422."""
    opportunity_id = await convert_opportunity_for_slug(
        db_client, database_engine, SUNSHINE, "medicare_advantage"
    )
    await set_stage(database_engine, SUNSHINE.schema_name, opportunity_id, "Qualified")
    await set_contact_age_band(
        database_engine, SUNSHINE.schema_name, opportunity_id, "55-64"
    )

    response = await db_client.post(
        f"/api/opportunities/{opportunity_id}/stage",
        json={"target_stage": "Quoted"},
    )
    assert response.status_code == 422
    assert "65" in response.json()["detail"]

    # The blocked move never changed the stage.
    stored = await read_one(
        database_engine,
        f"SELECT stage FROM {SUNSHINE.schema_name}.opportunities WHERE id = :id",
        {"id": opportunity_id},
    )
    assert stored.stage == "Qualified"


async def test_medicare_gate_allows_65_plus_entry_to_quoted(
    seeded, db_client, database_engine
):
    """A Medicare line + a `65+` contact may enter Quoted (200)."""
    opportunity_id = await convert_opportunity_for_slug(
        db_client, database_engine, SUNSHINE, "medicare_advantage"
    )
    await set_stage(database_engine, SUNSHINE.schema_name, opportunity_id, "Qualified")
    await set_contact_age_band(
        database_engine, SUNSHINE.schema_name, opportunity_id, "65+"
    )

    response = await db_client.post(
        f"/api/opportunities/{opportunity_id}/stage",
        json={"target_stage": "Quoted"},
    )
    assert response.status_code == 200
    assert response.json()["opportunity"]["stage"] == "Quoted"


async def test_non_medicare_line_under_65_is_not_gated_into_quoted(
    seeded, db_client, database_engine
):
    """A non-Medicare line never gates, so an under-65 contact enters Quoted (200)."""
    opportunity_id = await convert_opportunity_for_slug(
        db_client, database_engine, SUNSHINE, "final_expense"
    )
    await set_stage(database_engine, SUNSHINE.schema_name, opportunity_id, "Qualified")
    await set_contact_age_band(
        database_engine, SUNSHINE.schema_name, opportunity_id, "55-64"
    )

    response = await db_client.post(
        f"/api/opportunities/{opportunity_id}/stage",
        json={"target_stage": "Quoted"},
    )
    assert response.status_code == 200
    assert response.json()["opportunity"]["stage"] == "Quoted"


# --- Mark Lost (Epic 6) ------------------------------------------------------


async def test_mark_lost_moves_to_lost_and_emits_both_events(
    seeded, db_client, database_engine
):
    """Marking an active opportunity Lost → 200, terminal, and BOTH events fire."""
    _, opportunity_id, contact_id, household_id = await convert_one_opportunity(
        db_client, database_engine
    )

    response = await db_client.post(
        f"/api/opportunities/{opportunity_id}/stage",
        json={"target_stage": "Lost"},
    )
    assert response.status_code == 200
    moved = response.json()["opportunity"]
    assert moved["stage"] == "Lost"
    assert moved["next_stage"] is None
    assert moved["can_mark_lost"] is False

    # Both events on the outbox, sharing the opportunity's correlation id.
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
    assert stage_changed[0].payload["to_stage"] == "Lost"
    assert len(lost) == 1
    assert lost[0].payload == {
        "entity_id": str(opportunity_id),
        "from_stage": "New",
        "contact_id": str(contact_id),
        "household_id": str(household_id),
    }
    assert lost[0].correlation_id == stage_changed[0].correlation_id


async def test_lost_is_terminal_no_further_moves(seeded, db_client, database_engine):
    """A Lost opportunity cannot move anywhere — every target is a 409."""
    _, opportunity_id, _, _ = await convert_one_opportunity(db_client, database_engine)
    await set_stage(database_engine, SUNSHINE.schema_name, opportunity_id, "Lost")

    for target in ("Qualified", "Lost", "Policy Active"):
        response = await db_client.post(
            f"/api/opportunities/{opportunity_id}/stage",
            json={"target_stage": target},
        )
        assert response.status_code == 409, target


async def test_can_mark_lost_flag_tracks_active_stages(
    seeded, db_client, database_engine
):
    """`can_mark_lost` is true at an active stage, false once terminal."""
    _, opportunity_id, _, _ = await convert_one_opportunity(db_client, database_engine)

    def flag_for(board):
        return _board_row(board, opportunity_id)["can_mark_lost"]

    assert flag_for((await db_client.get("/api/opportunities")).json()) is True
    await set_stage(
        database_engine, SUNSHINE.schema_name, opportunity_id, "Policy Active"
    )
    assert flag_for((await db_client.get("/api/opportunities")).json()) is False
    await set_stage(database_engine, SUNSHINE.schema_name, opportunity_id, "Lost")
    assert flag_for((await db_client.get("/api/opportunities")).json()) is False


# --- Session isolation + enriched read (Epic 7) ------------------------------


async def test_list_is_scoped_to_seed_plus_caller_session(
    seeded, db_client, database_engine
):
    """The board shows the seed baseline ∪ the caller's session, never another's."""
    session_a = await mint_live_demo_session(database_engine)
    session_b = await mint_live_demo_session(database_engine)
    _, seed_opp, _, _ = await convert_one_opportunity(db_client, database_engine)
    _, opp_a, _, _ = await convert_one_opportunity(db_client, database_engine)
    _, opp_b, _, _ = await convert_one_opportunity(db_client, database_engine)
    await set_opportunity_session(database_engine, SUNSHINE.schema_name, opp_a, session_a)
    await set_opportunity_session(database_engine, SUNSHINE.schema_name, opp_b, session_b)

    def ids_for(board):
        return {row["id"] for row in board["opportunities"]}

    # Session A's cookie: seed + A's row, never B's.
    db_client.cookies.set(DEMO_SESSION_COOKIE_NAME, str(session_a))
    visible = ids_for((await db_client.get("/api/opportunities")).json())
    assert str(seed_opp) in visible
    assert str(opp_a) in visible
    assert str(opp_b) not in visible

    # No demo cookie ⇒ seed-only.
    db_client.cookies.delete(DEMO_SESSION_COOKIE_NAME)
    seed_only = ids_for((await db_client.get("/api/opportunities")).json())
    assert str(seed_opp) in seed_only
    assert str(opp_a) not in seed_only
    assert str(opp_b) not in seed_only


async def test_list_row_carries_enriched_fields(
    seeded, db_client, database_engine
):
    """A board row carries the value fields, contact name, owner, and eligibility."""
    _, opportunity_id, _, household_id = await convert_one_opportunity(
        db_client, database_engine
    )
    await set_contact_age_band(
        database_engine, SUNSHINE.schema_name, opportunity_id, "65+"
    )

    row = _board_row((await db_client.get("/api/opportunities")).json(), opportunity_id)
    assert row["household_id"] == str(household_id)
    assert row["product_line"] == "medicare_advantage"
    assert row["product_line_label"] == "Medicare Advantage"
    assert row["contact_first_name"] is not None
    assert row["contact_last_name"] is not None
    assert row["owner_username"] is not None
    # P2.1 conversion leaves the value fields null (the board renders em-dash).
    assert row["estimated_annual_premium"] is None
    assert row["target_close_date"] is None
    # Medicare line + a 65+ contact → gated and age-eligible.
    assert row["eligibility"] == {"medicare_gated": True, "age_eligible": True}


async def test_mutation_refuses_a_foreign_session_row_with_404(
    seeded, db_client, database_engine
):
    """Advancing another session's opportunity is a 404 (indistinguishable from absent)."""
    session_a = await mint_live_demo_session(database_engine)
    _, opportunity_id, _, _ = await convert_one_opportunity(db_client, database_engine)
    await set_opportunity_session(
        database_engine, SUNSHINE.schema_name, opportunity_id, session_a
    )
    # Caller has no demo session → the session_a row is foreign → 404.
    response = await db_client.post(
        f"/api/opportunities/{opportunity_id}/stage",
        json={"target_stage": "Qualified"},
    )
    assert response.status_code == 404


async def test_mutation_refuses_a_seed_row_in_a_live_session_with_409(
    seeded, db_client, database_engine
):
    """A demo visitor cannot modify a shared seed opportunity (409)."""
    session_a = await mint_live_demo_session(database_engine)
    _, opportunity_id, _, _ = await convert_one_opportunity(db_client, database_engine)
    # Caller is in a live session; the opportunity is a shared seed (NULL) row → 409.
    db_client.cookies.set(DEMO_SESSION_COOKIE_NAME, str(session_a))
    response = await db_client.post(
        f"/api/opportunities/{opportunity_id}/stage",
        json={"target_stage": "Qualified"},
    )
    assert response.status_code == 409


async def test_mutation_allows_the_callers_own_session_row(
    seeded, db_client, database_engine
):
    """Advancing an opportunity in the caller's own session succeeds (200)."""
    session_a = await mint_live_demo_session(database_engine)
    _, opportunity_id, _, _ = await convert_one_opportunity(db_client, database_engine)
    await set_opportunity_session(
        database_engine, SUNSHINE.schema_name, opportunity_id, session_a
    )
    db_client.cookies.set(DEMO_SESSION_COOKIE_NAME, str(session_a))
    response = await db_client.post(
        f"/api/opportunities/{opportunity_id}/stage",
        json={"target_stage": "Qualified"},
    )
    assert response.status_code == 200
    assert response.json()["opportunity"]["stage"] == "Qualified"
