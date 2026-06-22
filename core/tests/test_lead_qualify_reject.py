"""DB-backed proof of the lead qualify / reject actions (Epic 13, P1.7).

Epic 12 added the first lead action (`claim`, `New → Working`). Epic 13 adds the two
terminal-transition actions an agent runs on a lead they have been working:

- `POST /api/leads/{id}/qualify` — `Working → Qualified`, publishing `lead.qualified`
  (an `entity_id`-only payload). Returns `200` (no resource created).
- `POST /api/leads/{id}/reject` — `Working → Rejected`, storing an **optional**
  free-text `reason` on the new `rejection_reason` column (surfaced in the masked
  read, never on the event) and publishing `lead.rejected` with payload
  `{entity_id, reason_kind: "qualify_reject"}`. A reason-less reject is allowed.

Both gate on `CREATE_EDIT_RECORDS` (**not** claim's `CLAIM_LEADS_MANAGE_TASKS`) and
map an illegal move (the lead is not `Working`) to a `409`, a missing / cross-tenant
id to a `404`, and the anonymous caller to a `401`.

These drive the real endpoints over the DB-backed client (the same `seeded` /
`db_client` / `database_engine` substrate the other endpoint tests use) and read back
over the SELECT-capable superuser `database_engine` connection to prove each happy
transition, its event, the stored-and-masked reject reason, and the error edges. The
controllable `Working` start state (which the create endpoint can make only for the
*entering* agent, never as a free setup) is inserted directly into the tenant schema
through the **normal encryption path** via the shared `insert_lead` seam.

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no
`@pytest.mark.asyncio` decorator. The seams are reused by name from the sibling test
files: `insert_lead` / `login_agent_for_slug` / `tenant_id_for_slug` /
`unique_marker` / `unique_contact` from `test_lead_reads.py`; `read_lead_row` /
`read_outbox_rows_for_entity` from `test_lead_intake.py`; `login_as` / `seeded` from
`test_endpoints_db.py`; the `db_client` / `database_engine` fixtures come via
`conftest.py`.
"""

import uuid

from app.demo.session import DEMO_SESSION_COOKIE_NAME
from app.events.catalog import EventType
from app.leads.state import LeadStatus
from app.models.user import Role
from app.tenancy.registry import FLORIDA, SUNSHINE

from tests.test_demo_assume_persona import assume  # noqa: F401 — used by name
from tests.test_endpoints_db import login_as, seeded  # noqa: F401
from tests.test_lead_intake import read_lead_row, read_outbox_rows_for_entity
from tests.test_lead_reads import (
    insert_lead,
    login_agent_for_slug,
    mint_live_demo_session,
    tenant_id_for_slug,
    unique_contact,
    unique_marker,
)


async def insert_working_lead(database_engine, **kwargs):
    """Insert one `Working` Sunshine lead, returning `(tenant_id, lead_id)`.

    A thin helper over `insert_lead` for the common setup these tests share: a
    Sunshine lead in `Working` (the only legal start state for qualify / reject), with
    a unique marker and contact so the shared container's accumulated rows can't
    collide. Extra keyword arguments (e.g. `owner_user_id`) pass through to
    `insert_lead`.
    """
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
        owner_user_id=uuid.uuid4(),
        owner_username="owner@sunshine.example",
        **kwargs,
    )
    return tenant_id, lead_id


# --- Phase 1: qualify happy path + event -------------------------------------


async def test_qualify_returns_masked_qualified_lead(
    seeded, db_client, database_engine
):
    """Qualifying a `Working` lead → 200 with it now `Qualified`; the row agrees.

    A Sunshine Agent qualifies a `Working` lead: the response is the masked read shape
    with `status = Qualified`, and the stored row reads back `Qualified`.
    """
    _, lead_id = await insert_working_lead(database_engine)

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    response = await db_client.post(f"/api/leads/{lead_id}/qualify")

    assert response.status_code == 200
    assert response.json()["lead"]["status"] == "Qualified"

    row = await read_lead_row(database_engine, SUNSHINE.schema_name, lead_id)
    assert row.status == "Qualified"


async def test_qualify_enqueues_one_lead_qualified_event(
    seeded, db_client, database_engine
):
    """A qualify enqueues exactly one `lead.qualified` row with an `entity_id`-only payload.

    Exactly one `lead.qualified` row lands in the tenant `outbox`, its payload is
    `entity_id` only (no owner, no reason), the actor is the Agent, and its
    `correlation_id` equals the lead's own — one lead, one trace id.
    """
    _, lead_id = await insert_working_lead(database_engine)

    login_response = await login_agent_for_slug(db_client, SUNSHINE.slug)
    assert login_response.status_code == 200
    agent_id = login_response.json()["user"]["id"]

    response = await db_client.post(f"/api/leads/{lead_id}/qualify")
    assert response.status_code == 200

    rows = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.LEAD_QUALIFIED, lead_id
    )
    assert len(rows) == 1
    qualified = rows[0]
    assert qualified.payload == {"entity_id": str(lead_id)}
    assert qualified.actor_user_id == uuid.UUID(agent_id)
    assert qualified.actor_role == Role.AGENT

    row = await read_lead_row(database_engine, SUNSHINE.schema_name, lead_id)
    assert qualified.correlation_id == row.correlation_id


# --- Phase 2: reject happy path + event + stored reason ----------------------


async def test_reject_with_reason_stores_and_masks_it(
    seeded, db_client, database_engine
):
    """Rejecting with a reason → 200 `Rejected`, reason stored and shown in the masked read.

    A Sunshine Agent rejects a `Working` lead with a free-text reason: the response is
    `Rejected` with `rejection_reason` equal to the supplied text, and the masked
    detail read surfaces the same reason (it lives on the row, like `notes`).
    """
    _, lead_id = await insert_working_lead(database_engine)
    reason = "Not interested after follow-up call."

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    response = await db_client.post(
        f"/api/leads/{lead_id}/reject", json={"reason": reason}
    )

    assert response.status_code == 200
    lead = response.json()["lead"]
    assert lead["status"] == "Rejected"
    assert lead["rejection_reason"] == reason

    # The reason is visible on the masked detail read too (stored on the row).
    detail = await db_client.get(f"/api/leads/{lead_id}")
    assert detail.status_code == 200
    assert detail.json()["lead"]["rejection_reason"] == reason


async def test_reject_without_reason_is_allowed(seeded, db_client, database_engine):
    """A reason-less reject → 200 `Rejected` with a null `rejection_reason`.

    The `reason` field is optional. Omitting it still moves the lead to `Rejected`;
    `rejection_reason` stays null and the `reason_kind` on the event categorizes it.
    """
    _, lead_id = await insert_working_lead(database_engine)

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    response = await db_client.post(f"/api/leads/{lead_id}/reject", json={})

    assert response.status_code == 200
    lead = response.json()["lead"]
    assert lead["status"] == "Rejected"
    assert lead["rejection_reason"] is None

    row = await read_lead_row(database_engine, SUNSHINE.schema_name, lead_id)
    assert row.status == "Rejected"


async def test_reject_enqueues_one_lead_rejected_event(
    seeded, db_client, database_engine
):
    """A reject enqueues exactly one `lead.rejected` row carrying `reason_kind` not the reason.

    Exactly one `lead.rejected` row lands in the tenant `outbox`; its payload is the
    entity reference plus `reason_kind = "qualify_reject"` and **never** the free-text
    reason. The actor is the Agent and its `correlation_id` equals the lead's own.
    """
    _, lead_id = await insert_working_lead(database_engine)

    login_response = await login_agent_for_slug(db_client, SUNSHINE.slug)
    assert login_response.status_code == 200
    agent_id = login_response.json()["user"]["id"]

    response = await db_client.post(
        f"/api/leads/{lead_id}/reject", json={"reason": "secret rationale"}
    )
    assert response.status_code == 200

    rows = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.LEAD_REJECTED, lead_id
    )
    assert len(rows) == 1
    rejected = rows[0]
    assert rejected.payload == {
        "entity_id": str(lead_id),
        "reason_kind": "qualify_reject",
    }
    assert rejected.actor_user_id == uuid.UUID(agent_id)
    assert rejected.actor_role == Role.AGENT

    row = await read_lead_row(database_engine, SUNSHINE.schema_name, lead_id)
    assert rejected.correlation_id == row.correlation_id


# --- Phase 2b: qualify / reject events carry the demo session (Epic 3) --------


async def test_qualify_event_carries_the_cookie_demo_session(
    seeded, db_client, database_engine
):
    """A qualify under a demo cookie tags its `lead.qualified` event with the session id.

    `assume` mints the demo session (setting `pf_demo_session`) and logs the Agent in;
    the qualify resolves that cookie read-only and stamps the event's `demo_session_id`.
    The lead is tagged with the minted session so it is the caller's **own** row — under
    Epic 5's write-isolation a visitor-in-session may act only on their own (or no) row,
    so `assume` runs first and the insert carries that session id.
    """
    assert (
        await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT)
    ).status_code == 200
    minted_id = uuid.UUID(db_client.cookies[DEMO_SESSION_COOKIE_NAME])

    _, lead_id = await insert_working_lead(database_engine, demo_session_id=minted_id)

    response = await db_client.post(f"/api/leads/{lead_id}/qualify")
    assert response.status_code == 200

    rows = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.LEAD_QUALIFIED, lead_id
    )
    assert len(rows) == 1
    assert rows[0].demo_session_id == minted_id


async def test_qualify_event_demo_session_is_none_without_a_cookie(
    seeded, db_client, database_engine
):
    """A qualify with no demo cookie leaves the `lead.qualified` event's session NULL."""
    _, lead_id = await insert_working_lead(database_engine)

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    assert DEMO_SESSION_COOKIE_NAME not in db_client.cookies

    response = await db_client.post(f"/api/leads/{lead_id}/qualify")
    assert response.status_code == 200

    rows = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.LEAD_QUALIFIED, lead_id
    )
    assert len(rows) == 1
    assert rows[0].demo_session_id is None


async def test_reject_event_carries_the_cookie_demo_session(
    seeded, db_client, database_engine
):
    """A reject under a demo cookie tags its `lead.rejected` event with the session id.

    The lead is tagged with the minted session so it is the caller's **own** row — under
    Epic 5's write-isolation a visitor-in-session may act only on their own (or no) row,
    so `assume` runs first and the insert carries that session id.
    """
    assert (
        await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT)
    ).status_code == 200
    minted_id = uuid.UUID(db_client.cookies[DEMO_SESSION_COOKIE_NAME])

    _, lead_id = await insert_working_lead(database_engine, demo_session_id=minted_id)

    response = await db_client.post(f"/api/leads/{lead_id}/reject", json={})
    assert response.status_code == 200

    rows = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.LEAD_REJECTED, lead_id
    )
    assert len(rows) == 1
    assert rows[0].demo_session_id == minted_id


async def test_reject_event_demo_session_is_none_without_a_cookie(
    seeded, db_client, database_engine
):
    """A reject with no demo cookie leaves the `lead.rejected` event's session NULL."""
    _, lead_id = await insert_working_lead(database_engine)

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    assert DEMO_SESSION_COOKIE_NAME not in db_client.cookies

    response = await db_client.post(f"/api/leads/{lead_id}/reject", json={})
    assert response.status_code == 200

    rows = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.LEAD_REJECTED, lead_id
    )
    assert len(rows) == 1
    assert rows[0].demo_session_id is None


# --- Phase 3: illegal transition → 409 ---------------------------------------


async def test_qualifying_a_new_lead_is_409(seeded, db_client, database_engine):
    """Qualifying a non-`Working` (`New`) lead → 409 (`New → Qualified` is illegal)."""
    tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    email, phone = unique_contact()
    lead_id = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        tenant_id,
        first_name=unique_marker(),
        email=email,
        phone=phone,
        status=LeadStatus.NEW,
        owner_user_id=None,
    )

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    response = await db_client.post(f"/api/leads/{lead_id}/qualify")

    assert response.status_code == 409


async def test_rejecting_a_new_lead_is_409(seeded, db_client, database_engine):
    """Rejecting a non-`Working` (`New`) lead → 409 (`New → Rejected` is not this path).

    `New → Rejected` is reserved for Epic 14's duplicate-resolution reject, not this
    qualify/reject path which guards `Working → Rejected`; a `New` lead here is a 409.
    """
    tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    email, phone = unique_contact()
    lead_id = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        tenant_id,
        first_name=unique_marker(),
        email=email,
        phone=phone,
        status=LeadStatus.NEW,
        owner_user_id=None,
    )

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    response = await db_client.post(f"/api/leads/{lead_id}/reject", json={})

    assert response.status_code == 409


# --- Phase 4: RBAC -----------------------------------------------------------


async def test_qualify_forbidden_for_read_only(seeded, db_client, database_engine):
    """A Read-Only user lacks `CREATE_EDIT_RECORDS` → 403 on qualify."""
    _, lead_id = await insert_working_lead(database_engine)

    assert (await login_as(db_client, Role.READ_ONLY)).status_code == 200
    response = await db_client.post(f"/api/leads/{lead_id}/qualify")

    assert response.status_code == 403
    assert response.json() == {"detail": "insufficient permissions"}


async def test_reject_forbidden_for_read_only(seeded, db_client, database_engine):
    """A Read-Only user lacks `CREATE_EDIT_RECORDS` → 403 on reject."""
    _, lead_id = await insert_working_lead(database_engine)

    assert (await login_as(db_client, Role.READ_ONLY)).status_code == 200
    response = await db_client.post(f"/api/leads/{lead_id}/reject", json={})

    assert response.status_code == 403
    assert response.json() == {"detail": "insufficient permissions"}


async def test_qualify_unauthenticated_is_401(seeded, db_client):
    """A fresh client with no session cookie → 401 on qualify."""
    response = await db_client.post(f"/api/leads/{uuid.uuid4()}/qualify")

    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}


async def test_reject_unauthenticated_is_401(seeded, db_client):
    """A fresh client with no session cookie → 401 on reject."""
    response = await db_client.post(f"/api/leads/{uuid.uuid4()}/reject", json={})

    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}


# --- Phase 5: not found → 404 (missing + cross-tenant) -----------------------


async def test_qualify_unknown_id_is_404(seeded, db_client):
    """A qualify on a lead id that exists nowhere → 404 `"lead not found"`."""
    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200

    response = await db_client.post(f"/api/leads/{uuid.uuid4()}/qualify")

    assert response.status_code == 404
    assert response.json() == {"detail": "lead not found"}


async def test_reject_unknown_id_is_404(seeded, db_client):
    """A reject on a lead id that exists nowhere → 404 `"lead not found"`."""
    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200

    response = await db_client.post(f"/api/leads/{uuid.uuid4()}/reject", json={})

    assert response.status_code == 404
    assert response.json() == {"detail": "lead not found"}


async def test_qualify_cross_tenant_id_is_404(seeded, db_client, database_engine):
    """A Florida lead a Sunshine Agent tries to qualify → 404, identical to missing.

    `get_tenant_db` scopes the lookup to Sunshine's schema, so Florida's row is
    physically out of reach — a caller can neither act on nor probe for another
    tenant's leads.
    """
    florida_tenant_id = await tenant_id_for_slug(database_engine, FLORIDA.slug)
    email, phone = unique_contact()
    florida_lead_id = await insert_lead(
        database_engine,
        FLORIDA.schema_name,
        florida_tenant_id,
        first_name=unique_marker(),
        email=email,
        phone=phone,
        status=LeadStatus.WORKING,
        owner_user_id=uuid.uuid4(),
        owner_username="owner@florida.example",
    )

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    response = await db_client.post(f"/api/leads/{florida_lead_id}/qualify")

    assert response.status_code == 404
    assert response.json() == {"detail": "lead not found"}


async def test_reject_cross_tenant_id_is_404(seeded, db_client, database_engine):
    """A Florida lead a Sunshine Agent tries to reject → 404, identical to missing."""
    florida_tenant_id = await tenant_id_for_slug(database_engine, FLORIDA.slug)
    email, phone = unique_contact()
    florida_lead_id = await insert_lead(
        database_engine,
        FLORIDA.schema_name,
        florida_tenant_id,
        first_name=unique_marker(),
        email=email,
        phone=phone,
        status=LeadStatus.WORKING,
        owner_user_id=uuid.uuid4(),
        owner_username="owner@florida.example",
    )

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    response = await db_client.post(
        f"/api/leads/{florida_lead_id}/reject", json={}
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "lead not found"}


# --- Phase 6: demo-session write isolation (Epic 5) --------------------------


async def test_qualify_seed_row_is_409(seeded, db_client, database_engine):
    """Qualifying a shared seed row (`demo_session_id IS NULL`) → 409.

    A `Working` seed row is otherwise qualifiable, but the seed-row guard runs first and
    refuses to mutate a row every visitor sees.
    """
    _, lead_id = await insert_working_lead(database_engine, demo_session_id=None)
    session_id = await mint_live_demo_session(database_engine)

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    db_client.cookies.set(DEMO_SESSION_COOKIE_NAME, str(session_id))
    response = await db_client.post(f"/api/leads/{lead_id}/qualify")

    assert response.status_code == 409


async def test_qualify_foreign_session_row_is_404(seeded, db_client, database_engine):
    """Qualifying another session's row → 404, identical to the cross-tenant case."""
    session_a = await mint_live_demo_session(database_engine)
    session_b = await mint_live_demo_session(database_engine)
    _, lead_id = await insert_working_lead(database_engine, demo_session_id=session_b)

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    db_client.cookies.set(DEMO_SESSION_COOKIE_NAME, str(session_a))
    response = await db_client.post(f"/api/leads/{lead_id}/qualify")

    assert response.status_code == 404
    assert response.json() == {"detail": "lead not found"}


async def test_qualify_own_session_row_succeeds(seeded, db_client, database_engine):
    """Qualifying the caller's own session row succeeds normally → 200."""
    session_id = await mint_live_demo_session(database_engine)
    _, lead_id = await insert_working_lead(database_engine, demo_session_id=session_id)

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    db_client.cookies.set(DEMO_SESSION_COOKIE_NAME, str(session_id))
    response = await db_client.post(f"/api/leads/{lead_id}/qualify")

    assert response.status_code == 200
    assert response.json()["lead"]["status"] == "Qualified"


async def test_reject_seed_row_is_409(seeded, db_client, database_engine):
    """Rejecting a shared seed row (`demo_session_id IS NULL`) → 409."""
    _, lead_id = await insert_working_lead(database_engine, demo_session_id=None)
    session_id = await mint_live_demo_session(database_engine)

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    db_client.cookies.set(DEMO_SESSION_COOKIE_NAME, str(session_id))
    response = await db_client.post(f"/api/leads/{lead_id}/reject", json={})

    assert response.status_code == 409


async def test_reject_foreign_session_row_is_404(seeded, db_client, database_engine):
    """Rejecting another session's row → 404, identical to the cross-tenant case."""
    session_a = await mint_live_demo_session(database_engine)
    session_b = await mint_live_demo_session(database_engine)
    _, lead_id = await insert_working_lead(database_engine, demo_session_id=session_b)

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    db_client.cookies.set(DEMO_SESSION_COOKIE_NAME, str(session_a))
    response = await db_client.post(f"/api/leads/{lead_id}/reject", json={})

    assert response.status_code == 404
    assert response.json() == {"detail": "lead not found"}


async def test_reject_own_session_row_succeeds(seeded, db_client, database_engine):
    """Rejecting the caller's own session row succeeds normally → 200."""
    session_id = await mint_live_demo_session(database_engine)
    _, lead_id = await insert_working_lead(database_engine, demo_session_id=session_id)

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    db_client.cookies.set(DEMO_SESSION_COOKIE_NAME, str(session_id))
    response = await db_client.post(f"/api/leads/{lead_id}/reject", json={})

    assert response.status_code == 200
    assert response.json()["lead"]["status"] == "Rejected"
