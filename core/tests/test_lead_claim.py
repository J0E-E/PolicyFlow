"""DB-backed proof of the lead claim action (Epic 12, P1.7).

Epic 11 added the authenticated, tenant-scoped, masked lead reads (the queue list
and the detail). Epic 12 adds the first lead *action*: `POST /api/leads/{id}/claim`
lets an agent pick an unclaimed `New` lead off the queue and take ownership — the
lead moves `New → Working`, its owner becomes the calling agent, and a
`lead.assigned` event is published. No new resource is created (the lead already
exists), so the success status is `200`, not `201`.

This drives the real endpoint over the DB-backed client (the same `seeded` /
`db_client` / `database_engine` substrate the other endpoint tests use) and reads
back over the SELECT-capable superuser `database_engine` connection
(schema-qualified — the tenant role is INSERT-only on its own `outbox`) to prove:

- **Happy path** — an Agent claims an unowned `New` lead → 200 with the masked lead
  now `Working`, owned by the Agent; the stored row is `Working` / owned by the
  Agent too.
- **The `lead.assigned` event** — exactly one outbox row, with the right non-PII
  payload (the entity reference + the new owner's id), actor = the Agent, and a
  `correlation_id` equal to the lead's own (one lead's events share one trace id).
- **Illegal transition → 409** — claiming an already-`Working` lead, and a
  `Rejected` lead: the state machine rejects the move and the edge maps it to a 409.
- **RBAC** — a Read-Only user lacks `CLAIM_LEADS_MANAGE_TASKS` → 403; an anonymous
  caller → 401.
- **Not found → 404** — an unknown id, and a *Florida* lead a Sunshine Agent tries
  to claim (tenant isolation): both 404 `"lead not found"`, indistinguishable.

The controllable lead states the create endpoint cannot itself produce (an unowned
`New` queue lead, an unowned `Rejected` lead) are inserted directly into the tenant
schema through the **normal encryption path** via the shared `insert_lead` seam.
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


# --- Phase 1: happy path — masked body + claimed state -----------------------


async def test_claim_returns_masked_working_lead_owned_by_agent(
    seeded, db_client, database_engine
):
    """Claiming an unowned `New` lead → 200 with it now `Working`, owned by the Agent.

    A Sunshine Agent claims an unowned `New` queue lead: the response is the masked
    read shape with `status = Working` and `owner_user_id` = the Agent, and the stored
    row reads back `Working` / owned by the Agent (`owner_user_id` / `owner_username`).
    """
    sunshine_tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    email, phone = unique_contact()
    lead_id = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        sunshine_tenant_id,
        first_name=unique_marker(),
        email=email,
        phone=phone,
        status=LeadStatus.NEW,
        owner_user_id=None,
    )

    login_response = await login_agent_for_slug(db_client, SUNSHINE.slug)
    assert login_response.status_code == 200
    agent = login_response.json()["user"]

    response = await db_client.post(f"/api/leads/{lead_id}/claim")

    assert response.status_code == 200
    lead = response.json()["lead"]
    assert lead["status"] == "Working"
    assert lead["owner_user_id"] == agent["id"]

    row = await read_lead_row(database_engine, SUNSHINE.schema_name, lead_id)
    assert row.status == "Working"
    assert row.owner_user_id == uuid.UUID(agent["id"])
    assert row.owner_username == agent["username"]


# --- Phase 2: the `lead.assigned` event --------------------------------------


async def test_claim_enqueues_one_lead_assigned_event(
    seeded, db_client, database_engine
):
    """A claim enqueues exactly one `lead.assigned` outbox row sharing the trace id.

    Exactly one `lead.assigned` row lands in the Agent's own tenant `outbox`, on the
    same request transaction as the status change. Its payload carries the entity
    reference plus the new owner's id, the actor is the Agent (`actor_role = AGENT`),
    and its `correlation_id` equals the lead's own `correlation_id` — every event for
    one lead shares one trace id.
    """
    sunshine_tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    email, phone = unique_contact()
    lead_id = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        sunshine_tenant_id,
        first_name=unique_marker(),
        email=email,
        phone=phone,
        status=LeadStatus.NEW,
        owner_user_id=None,
    )

    login_response = await login_agent_for_slug(db_client, SUNSHINE.slug)
    assert login_response.status_code == 200
    agent_id = login_response.json()["user"]["id"]

    response = await db_client.post(f"/api/leads/{lead_id}/claim")
    assert response.status_code == 200

    rows = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.LEAD_ASSIGNED, lead_id
    )
    assert len(rows) == 1
    assigned = rows[0]
    assert assigned.payload == {
        "entity_id": str(lead_id),
        "owner_user_id": agent_id,
    }
    assert assigned.actor_user_id == uuid.UUID(agent_id)
    assert assigned.actor_role == Role.AGENT

    # The event reuses the lead's own correlation id (one lead, one trace id).
    row = await read_lead_row(database_engine, SUNSHINE.schema_name, lead_id)
    assert assigned.correlation_id == row.correlation_id


# --- Phase 2b: the `lead.assigned` event carries the demo session (Epic 3) ----


async def test_claim_event_carries_the_cookie_demo_session(
    seeded, db_client, database_engine
):
    """A claim under a demo cookie tags its `lead.assigned` event with the session id.

    `assume` mints the demo session (setting `pf_demo_session`) and logs the Agent in;
    the following claim resolves that cookie read-only and stamps the event's
    `demo_session_id` with the minted id. The lead is tagged with the minted session so
    it is the caller's **own** row — under Epic 5's write-isolation a visitor-in-session
    may act only on their own (or no) row, so `assume` runs first and the insert carries
    that session id.
    """
    sunshine_tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)

    assert (
        await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT)
    ).status_code == 200
    minted_id = uuid.UUID(db_client.cookies[DEMO_SESSION_COOKIE_NAME])

    email, phone = unique_contact()
    lead_id = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        sunshine_tenant_id,
        first_name=unique_marker(),
        email=email,
        phone=phone,
        status=LeadStatus.NEW,
        owner_user_id=None,
        demo_session_id=minted_id,
    )

    response = await db_client.post(f"/api/leads/{lead_id}/claim")
    assert response.status_code == 200

    rows = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.LEAD_ASSIGNED, lead_id
    )
    assert len(rows) == 1
    assert rows[0].demo_session_id == minted_id


async def test_claim_event_demo_session_is_none_without_a_cookie(
    seeded, db_client, database_engine
):
    """A claim with no demo cookie leaves the event's `demo_session_id` NULL.

    `login_agent_for_slug` authenticates the Agent without minting a demo session, so
    no `pf_demo_session` cookie is present and the `lead.assigned` event is untagged.
    """
    sunshine_tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    email, phone = unique_contact()
    lead_id = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        sunshine_tenant_id,
        first_name=unique_marker(),
        email=email,
        phone=phone,
        status=LeadStatus.NEW,
        owner_user_id=None,
    )

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    assert DEMO_SESSION_COOKIE_NAME not in db_client.cookies

    response = await db_client.post(f"/api/leads/{lead_id}/claim")
    assert response.status_code == 200

    rows = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.LEAD_ASSIGNED, lead_id
    )
    assert len(rows) == 1
    assert rows[0].demo_session_id is None


# --- Phase 3: illegal transition → 409 ---------------------------------------


async def test_claiming_a_working_lead_is_409(seeded, db_client, database_engine):
    """Claiming an already-`Working` lead → 409 (`Working → Working` is illegal).

    The state machine allows only `New → Working`; a lead already `Working` is not a
    legal claim target, so the framework-free `InvalidLeadTransition` the guard raises
    is mapped to a 409 at the edge.
    """
    sunshine_tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    email, phone = unique_contact()
    lead_id = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        sunshine_tenant_id,
        first_name=unique_marker(),
        email=email,
        phone=phone,
        status=LeadStatus.WORKING,
        owner_user_id=uuid.uuid4(),
        owner_username="someone@sunshine.example",
    )

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    response = await db_client.post(f"/api/leads/{lead_id}/claim")

    assert response.status_code == 409


async def test_claiming_a_rejected_lead_is_409(seeded, db_client, database_engine):
    """Claiming a `Rejected` lead → 409 (`Rejected` is terminal — no claim out of it).

    `Rejected` is a terminal status with no outgoing transitions, so a claim attempt
    is rejected the same way as the already-`Working` case — a 409 from the mapped
    `InvalidLeadTransition`.
    """
    sunshine_tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    email, phone = unique_contact()
    lead_id = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        sunshine_tenant_id,
        first_name=unique_marker(),
        email=email,
        phone=phone,
        status=LeadStatus.REJECTED,
        owner_user_id=None,
    )

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    response = await db_client.post(f"/api/leads/{lead_id}/claim")

    assert response.status_code == 409


# --- Phase 4: RBAC -----------------------------------------------------------


async def test_claim_forbidden_for_read_only(seeded, db_client, database_engine):
    """A Read-Only user lacks `CLAIM_LEADS_MANAGE_TASKS` → 403."""
    sunshine_tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    email, phone = unique_contact()
    lead_id = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        sunshine_tenant_id,
        first_name=unique_marker(),
        email=email,
        phone=phone,
        status=LeadStatus.NEW,
        owner_user_id=None,
    )

    assert (await login_as(db_client, Role.READ_ONLY)).status_code == 200
    response = await db_client.post(f"/api/leads/{lead_id}/claim")

    assert response.status_code == 403
    assert response.json() == {"detail": "insufficient permissions"}


async def test_claim_unauthenticated_is_401(seeded, db_client):
    """A fresh client with no session cookie → 401."""
    response = await db_client.post(f"/api/leads/{uuid.uuid4()}/claim")

    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}


# --- Phase 5: not found → 404 ------------------------------------------------


async def test_claim_unknown_id_is_404(seeded, db_client):
    """A lead id that exists nowhere → 404 `"lead not found"`."""
    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200

    response = await db_client.post(f"/api/leads/{uuid.uuid4()}/claim")

    assert response.status_code == 404
    assert response.json() == {"detail": "lead not found"}


async def test_claim_cross_tenant_id_is_404(seeded, db_client, database_engine):
    """A Florida lead a Sunshine Agent tries to claim → 404, identical to missing.

    A lead is inserted into Florida's schema; a logged-in Sunshine Agent claiming it
    by id gets a 404 — `get_tenant_db` scopes the lookup to Sunshine's schema, so
    Florida's row is physically out of reach and a caller can neither act on nor probe
    for another tenant's leads.
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
        status=LeadStatus.NEW,
        owner_user_id=None,
    )

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    response = await db_client.post(f"/api/leads/{florida_lead_id}/claim")

    assert response.status_code == 404
    assert response.json() == {"detail": "lead not found"}


# --- Phase 6: demo-session write isolation (Epic 5) --------------------------


async def test_claim_seed_row_is_409(seeded, db_client, database_engine):
    """Claiming a shared seed row (`demo_session_id IS NULL`) → 409.

    A mutating action must never alter a row every visitor sees. A Sunshine Agent
    carrying a live session cookie tries to claim a `New` seed row and is refused with a
    409 — the seed-row guard runs before the state-machine guard, so an otherwise-claimable
    `New` lead is still refused.
    """
    sunshine_tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    session_id = await mint_live_demo_session(database_engine)
    email, phone = unique_contact()
    seed_lead_id = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        sunshine_tenant_id,
        first_name=unique_marker(),
        email=email,
        phone=phone,
        status=LeadStatus.NEW,
        owner_user_id=None,
        demo_session_id=None,
    )

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    db_client.cookies.set(DEMO_SESSION_COOKIE_NAME, str(session_id))
    response = await db_client.post(f"/api/leads/{seed_lead_id}/claim")

    assert response.status_code == 409


async def test_claim_foreign_session_row_is_404(seeded, db_client, database_engine):
    """Claiming another demo session's row → 404, identical to the cross-tenant case.

    A `New` lead owned by session B is invisible to a caller carrying session A's
    cookie: the foreign-session guard maps it to a `404 "lead not found"`, so one
    visitor can neither act on nor probe for another's lead.
    """
    sunshine_tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    session_a = await mint_live_demo_session(database_engine)
    session_b = await mint_live_demo_session(database_engine)
    email, phone = unique_contact()
    foreign_lead_id = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        sunshine_tenant_id,
        first_name=unique_marker(),
        email=email,
        phone=phone,
        status=LeadStatus.NEW,
        owner_user_id=None,
        demo_session_id=session_b,
    )

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    db_client.cookies.set(DEMO_SESSION_COOKIE_NAME, str(session_a))
    response = await db_client.post(f"/api/leads/{foreign_lead_id}/claim")

    assert response.status_code == 404
    assert response.json() == {"detail": "lead not found"}


async def test_claim_own_session_row_succeeds(seeded, db_client, database_engine):
    """Claiming the caller's own session row succeeds normally → 200.

    The write-isolation guards pass a row the caller owns (`demo_session_id` = the
    caller's session) straight through to the existing claim flow, proving the guards
    refuse only foreign / seed rows, not the visitor's own work.
    """
    sunshine_tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    session_id = await mint_live_demo_session(database_engine)
    email, phone = unique_contact()
    own_lead_id = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        sunshine_tenant_id,
        first_name=unique_marker(),
        email=email,
        phone=phone,
        status=LeadStatus.NEW,
        owner_user_id=None,
        demo_session_id=session_id,
    )

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    db_client.cookies.set(DEMO_SESSION_COOKIE_NAME, str(session_id))
    response = await db_client.post(f"/api/leads/{own_lead_id}/claim")

    assert response.status_code == 200
    assert response.json()["lead"]["status"] == "Working"
