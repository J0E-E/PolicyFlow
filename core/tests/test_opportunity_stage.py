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
    tenant_id_for_slug,
    unique_contact,
    unique_marker,
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
    """With Approved disabled, Florida's Submitted advances straight to Policy Active."""
    opportunity_id = await convert_opportunity_for_slug(
        db_client, database_engine, FLORIDA, "term_life"
    )
    await set_stage(database_engine, FLORIDA.schema_name, opportunity_id, "Submitted")

    # The board's next_stage skips the disabled Approved stage.
    board = (await db_client.get("/api/opportunities")).json()
    row = _board_row(board, opportunity_id)
    assert row["stage"] == "Submitted"
    assert row["next_stage"] == "Policy Active"

    # The skipped stage is not a legal target; the skip-to stage is.
    blocked = await db_client.post(
        f"/api/opportunities/{opportunity_id}/stage",
        json={"target_stage": "Approved"},
    )
    assert blocked.status_code == 409
    advanced = await db_client.post(
        f"/api/opportunities/{opportunity_id}/stage",
        json={"target_stage": "Policy Active"},
    )
    assert advanced.status_code == 200
    assert advanced.json()["opportunity"]["stage"] == "Policy Active"


async def test_sunshine_submitted_still_steps_through_approved(
    seeded, db_client, database_engine
):
    """With Approved enabled, Sunshine's Submitted advances to Approved (no skip)."""
    opportunity_id = await convert_opportunity_for_slug(
        db_client, database_engine, SUNSHINE, "final_expense"
    )
    await set_stage(database_engine, SUNSHINE.schema_name, opportunity_id, "Submitted")

    board = (await db_client.get("/api/opportunities")).json()
    assert _board_row(board, opportunity_id)["next_stage"] == "Approved"

    advanced = await db_client.post(
        f"/api/opportunities/{opportunity_id}/stage",
        json={"target_stage": "Approved"},
    )
    assert advanced.status_code == 200
    assert advanced.json()["opportunity"]["stage"] == "Approved"
