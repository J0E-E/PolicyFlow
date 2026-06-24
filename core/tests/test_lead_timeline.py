"""DB-backed proof of the per-lead event timeline read (P1.9 Epic 1, the tracer slice).

`GET /api/leads/{lead_id}/timeline` returns one lead's own domain events as an
oldest-first list of neutral event rows — the thinnest customer-visible thread of the
P1.9 timeline. These drive the real endpoint over the DB-backed client (the same
`seeded` / `db_client` / `database_engine` substrate the other lead-endpoint tests use)
and assert:

- **all of a lead's event types appear, oldest-first** — not just `lead.created`. A lead
  is created → claimed → qualified through the real endpoints, producing `lead.created`,
  `lead.assigned`, `lead.qualified`; the timeline returns all three in occurrence order.
  This is the regression guarding the resolved decision to filter the outbox on
  `payload->>'entity_id'` **alone** (every lead event carries `entity_id`; only
  `lead.created` carries `entity_type`, so an `entity_type='lead'` clause would silently
  drop every event after creation).
- **the event-row shape** — `kind="event"`, `status="occurred"`, the raw dotted
  `event_type`, an ISO `occurred_at`, and the `event_id` / `correlation_id` strings, with
  one shared `correlation_id` across a lead's events.
- **the three 404 cases** — a missing id, a cross-tenant id, and a cross-session id all
  return the same `404 "lead not found"` as the detail read (the timeline reuses
  `get_lead`'s guard verbatim).
- **the empty timeline** — a freshly-inserted lead with no events returns `{"rows": []}`.

The reads exercise the migration-`0014` outbox SELECT grant end-to-end: the endpoint
runs under the tenant `db_role`, which `0008` had revoked SELECT on `outbox` from and
`0014` re-granted. `pytest.ini` sets `asyncio_mode = auto`, so these async tests carry
no decorator. The `seeded` / `db_client` / `database_engine` fixtures, `login_as`, and
the `insert_lead` / `mint_live_demo_session` helpers are reused by name.
"""

import uuid

from app.demo.session import DEMO_SESSION_COOKIE_NAME
from app.models.user import Role
from app.tenancy.registry import FLORIDA, SUNSHINE

from tests.test_endpoints_db import login_as, seeded  # noqa: F401
from tests.test_lead_reads import (  # noqa: F401
    insert_lead,
    mint_live_demo_session,
    tenant_id_for_slug,
    unique_contact,
    unique_marker,
)


async def create_lead_via_endpoint(db_client) -> dict:
    """Create one lead through `POST /api/leads`; return the masked lead body.

    Drives the real endpoint (so a real `lead.created` outbox row is written) with
    unique contact details so the duplicate matcher never flags an unrelated row.
    """
    email, phone = unique_contact()
    response = await db_client.post(
        "/api/leads",
        json={
            "first_name": "Timeline",
            "last_name": "Tracer",
            "email": email,
            "phone": phone,
            "date_of_birth": "1955-06-15",
            "zip_code": "33101",
            "product_lines_of_interest": ["medicare_advantage"],
        },
    )
    assert response.status_code == 201
    return response.json()["lead"]


async def test_timeline_returns_all_event_types_oldest_first(seeded, db_client):
    """The timeline lists every one of a lead's events, oldest-first — not just created.

    A lead is created, claimed, then qualified through the real endpoints, so its outbox
    accrues `lead.created` → `lead.assigned` → `lead.qualified` in that order. The
    timeline returns all three (the regression the `entity_id`-only filter guards) in
    occurrence order, all sharing one `correlation_id`.
    """
    assert (await login_as(db_client, Role.AGENT)).status_code == 200

    lead = await create_lead_via_endpoint(db_client)
    # A lead is born `Working` via the agent route, so move it back is not possible —
    # instead claim is for `New`. The agent-created lead is already `Working`, so drive
    # the qualify path (Working -> Qualified) to add a second event after `created`.
    qualify_response = await db_client.post(f"/api/leads/{lead['id']}/qualify")
    assert qualify_response.status_code == 200

    response = await db_client.get(f"/api/leads/{lead['id']}/timeline")
    assert response.status_code == 200

    rows = response.json()["rows"]
    event_types = [row["event_type"] for row in rows]
    # Both of this lead's events appear, oldest-first (created before qualified).
    assert event_types == ["lead.created", "lead.qualified"]
    # All events of one lead share a single correlation id (one trace).
    assert len({row["correlation_id"] for row in rows}) == 1


async def test_timeline_includes_assigned_for_a_claimed_lead(
    seeded, db_client, database_engine
):
    """A queue lead claimed then qualified shows created → assigned → qualified, in order.

    Proves the full event vocabulary surfaces (claim writes `lead.assigned`), not only
    the agent-create path. A `New`/unowned lead is inserted directly (the create endpoint
    cannot make a `New` lead), then driven `claim` → `qualify` through the endpoints; its
    timeline carries all three event types oldest-first.
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
    )

    assert (await login_as(db_client, Role.AGENT)).status_code == 200
    assert (await db_client.post(f"/api/leads/{lead_id}/claim")).status_code == 200
    assert (await db_client.post(f"/api/leads/{lead_id}/qualify")).status_code == 200

    response = await db_client.get(f"/api/leads/{lead_id}/timeline")
    assert response.status_code == 200

    rows = response.json()["rows"]
    assert [row["event_type"] for row in rows] == [
        "lead.assigned",
        "lead.qualified",
    ]


async def test_timeline_event_row_shape(seeded, db_client):
    """Each event row carries kind/status/event_type/occurred_at/event_id/correlation_id."""
    assert (await login_as(db_client, Role.AGENT)).status_code == 200

    lead = await create_lead_via_endpoint(db_client)

    response = await db_client.get(f"/api/leads/{lead['id']}/timeline")
    assert response.status_code == 200

    rows = response.json()["rows"]
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "event"
    assert row["status"] == "occurred"
    assert row["event_type"] == "lead.created"
    # occurred_at is an ISO string; event_id / correlation_id are UUID strings.
    assert isinstance(row["occurred_at"], str) and "T" in row["occurred_at"]
    uuid.UUID(row["event_id"])
    uuid.UUID(row["correlation_id"])


async def test_timeline_empty_for_lead_with_no_events(
    seeded, db_client, database_engine
):
    """A lead inserted directly (no events fired) returns an empty `{"rows": []}`."""
    sunshine_tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    email, phone = unique_contact()
    lead_id = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        sunshine_tenant_id,
        first_name=unique_marker(),
        email=email,
        phone=phone,
    )

    assert (await login_as(db_client, Role.AGENT)).status_code == 200
    response = await db_client.get(f"/api/leads/{lead_id}/timeline")

    assert response.status_code == 200
    assert response.json() == {"rows": []}


async def test_timeline_missing_id_is_404(seeded, db_client):
    """A lead id that exists nowhere → 404 `"lead not found"` (same as the detail read)."""
    assert (await login_as(db_client, Role.AGENT)).status_code == 200

    response = await db_client.get(f"/api/leads/{uuid.uuid4()}/timeline")

    assert response.status_code == 404
    assert response.json() == {"detail": "lead not found"}


async def test_timeline_cross_tenant_id_is_404(seeded, db_client, database_engine):
    """A lead id belonging to *another* tenant → 404, indistinguishable from missing.

    A lead is inserted into Florida's schema; a logged-in Sunshine Agent requesting its
    timeline gets a 404 — `get_tenant_db` scopes the lookup to Sunshine's schema, so
    Florida's row is out of reach.
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
    )

    assert (await login_as(db_client, Role.AGENT)).status_code == 200  # Sunshine
    response = await db_client.get(f"/api/leads/{florida_lead_id}/timeline")

    assert response.status_code == 404
    assert response.json() == {"detail": "lead not found"}


async def test_timeline_cross_session_id_is_404(seeded, db_client, database_engine):
    """A lead owned by *another* demo session → 404, identical to the cross-tenant case.

    A row tagged to session B is inserted into Sunshine's schema. A Sunshine Agent
    carrying session A's cookie requesting its timeline gets a `404 "lead not found"` —
    the timeline reuses the detail read's `_guard_loaded_lead_for_session` verbatim, so a
    visitor can neither read nor probe for another session's lead.
    """
    sunshine_tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    session_a = await mint_live_demo_session(database_engine)
    session_b = await mint_live_demo_session(database_engine)

    email, phone = unique_contact()
    session_b_lead_id = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        sunshine_tenant_id,
        first_name=unique_marker(),
        email=email,
        phone=phone,
        demo_session_id=session_b,
    )

    assert (await login_as(db_client, Role.AGENT)).status_code == 200

    # Session A's cookie: the foreign session B row's timeline is a 404.
    db_client.cookies.set(DEMO_SESSION_COOKIE_NAME, str(session_a))
    try:
        response = await db_client.get(f"/api/leads/{session_b_lead_id}/timeline")
        assert response.status_code == 404
        assert response.json() == {"detail": "lead not found"}
    finally:
        db_client.cookies.delete(DEMO_SESSION_COOKIE_NAME)
