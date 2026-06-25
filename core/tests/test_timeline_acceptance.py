"""Named acceptance + isolation suite for the per-lead event timeline (P1.9 Epic 7).

This is the final, test-only hardening epic. It does not change production code; it
ties the five TDD §8 acceptance criteria to *named* end-to-end assertions through the
real `GET /api/leads/{lead_id}/timeline` endpoint, and adds the one genuinely-missing
isolation proof the per-slice tests don't already cover.

What the per-slice tests already prove (built on, not re-created here):

- `test_lead_timeline.py` proves the three `404` cases — a missing id, a cross-*tenant*
  id, and a cross-*session* id all return `404 "lead not found"`: a visitor cannot even
  *open* another tenant's or session's lead. It exposes `insert_lead`,
  `mint_live_demo_session`, `tenant_id_for_slug`, `unique_contact`, and `unique_marker`,
  reused here by name.
- `test_seed_event_trails.py` (Epic 5) proves the seeded trail at the seed layer.
- `test_lead_timeline_reactions.py` (Epic 2) proves reaction-row derivation in isolation.

What this suite adds:

- **Acceptance #5 — no cross-contamination on a *visible* timeline.** The 404 tests prove
  a visitor can't open a *foreign* lead; they do not prove that when a visitor opens their
  *own* lead, none of a *concurrent* session's events / reactions leak in. Two leads are
  inserted into the *same* Sunshine schema under two live demo sessions (A and B), each
  given its own synthesized outbox + processed_events trail (riding `consumers_for_event_type`,
  never re-deriving the routing). Session A, reading its *own* lead's timeline, sees only
  A's event_ids and consumer rows — none of B's. The linkage rides `payload->>'entity_id'
  = lead_id` plus the `event_id` join: `processed_events` carries no `demo_session_id`, so a
  foreign reaction could only appear via a globally-unique shared `event_id`, which cannot
  occur. This test makes that concrete. Cross-tenant non-leak is reaffirmed the same way.
- **Acceptance #2 / #3 — the seeded coherent trail + both stub reactions as siblings,
  through the endpoint.** A seeded baseline lead (`demo_session_id IS NULL`) opens through
  the HTTP endpoint with its full status-derived trail oldest-first, every reaction `done`,
  the enrichment reaction carrying its quality-score summary and `sync.logger` carrying
  null, and `lead.created` returning *both* stub reactions (`enrichment.stub` then
  `sync.logger`) as sibling rows in registry order.

The synthesis helper mirrors the seed's schema-qualified raw `text()` INSERT idiom
(`app.seed._seed_lead_event_trail`) — `published_at = occurred_at` so every reaction
derives `done`, payload bound as a JSON *string* with `CAST(:payload AS jsonb)` (the
asyncpg raw-JSONB carry-forward), and the enrichment summary reused from
`enrichment_result_summary` so seed == live. Every delivery / isolation assertion is keyed
on explicit ids (lead_id / session_id / event_id), never "the next row" — the session-scoped
container is never reset. `pytest.ini` sets `asyncio_mode = auto`, so these async tests carry
no decorator. The `seeded` / `db_client` / `database_engine` fixtures and `login_as` are
reused by name.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.demo.session import DEMO_SESSION_COOKIE_NAME
from app.events.catalog import (
    ENRICHMENT_STUB,
    SCHEMA_VERSION,
    SYNC_LOGGER,
    EventType,
    consumers_for_event_type,
)
from app.events.enrichment import enrichment_result_summary
from app.leads.state import LeadStatus
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

# A backdated anchor for the synthesized trails — days in the past, so every
# derived stamp stays comfortably before now (mirrors the seed's backdating).
TRAIL_ANCHOR = datetime(2026, 1, 10, 9, 0, 0, tzinfo=timezone.utc)


def _synthesized_events(created_at: datetime) -> list[tuple[EventType, datetime]]:
    """A created → assigned → qualified trail, oldest-first, spread one hour apart.

    Mirrors `app.seed._synthesized_lead_events` for a Qualified lead: every lead
    carries `lead.created`, an owned lead adds `lead.assigned`, a Qualified lead adds
    the terminal `lead.qualified`. Three events give the isolation read more than one
    event_id to confuse with the other session's, which is the point.
    """
    return [
        (EventType.LEAD_CREATED, created_at),
        (EventType.LEAD_ASSIGNED, created_at + timedelta(hours=1)),
        (EventType.LEAD_QUALIFIED, created_at + timedelta(hours=2)),
    ]


async def _synthesize_trail(
    database_engine,
    *,
    schema_name: str,
    tenant_id: uuid.UUID,
    lead_id: uuid.UUID,
    created_at: datetime,
) -> list[uuid.UUID]:
    """Insert one lead's outbox + processed_events trail; return its event_ids.

    Mirrors `app.seed._seed_lead_event_trail`'s schema-qualified raw `text()` INSERT
    idiom exactly: one `outbox` row per status-derived event (`published_at = occurred_at`
    so the read derives a terminal `done`, payload bound as a JSON string with
    `CAST(:payload AS jsonb)` — the asyncpg raw-JSONB carry-forward), then one
    `processed_events` row per consumer the catalog fans the event out to
    (`consumers_for_event_type`, registry-ordered), the enrichment row carrying
    `enrichment_result_summary(event_id)` and `sync.logger` carrying null. The schema
    name comes only from the registry; every value is a bound parameter. Returns the
    list of synthesized event_ids so the isolation read can assert membership by id.
    """
    correlation_id = uuid.uuid4()
    event_ids: list[uuid.UUID] = []
    async with database_engine.begin() as connection:
        for event_type, occurred_at in _synthesized_events(created_at):
            event_id = uuid.uuid4()
            event_ids.append(event_id)
            payload: dict[str, str] = {"entity_id": str(lead_id)}
            if event_type is EventType.LEAD_CREATED:
                payload["entity_type"] = "lead"

            await connection.execute(
                text(
                    f"INSERT INTO {schema_name}.outbox "
                    "(id, event_id, event_type, schema_version, tenant_id, "
                    "correlation_id, causation_id, actor_user_id, actor_role, "
                    "demo_session_id, payload, occurred_at, published_at) "
                    "VALUES (:id, :event_id, :event_type, :schema_version, "
                    ":tenant_id, :correlation_id, NULL, NULL, NULL, NULL, "
                    "CAST(:payload AS jsonb), :occurred_at, :published_at)"
                ),
                {
                    "id": uuid.uuid4(),
                    "event_id": event_id,
                    "event_type": event_type.value,
                    "schema_version": SCHEMA_VERSION,
                    "tenant_id": tenant_id,
                    "correlation_id": correlation_id,
                    "payload": json.dumps(payload),
                    "occurred_at": occurred_at,
                    "published_at": occurred_at,
                },
            )

            processed_at = occurred_at + timedelta(minutes=1)
            for consumer_name in consumers_for_event_type(event_type.value):
                result_summary = (
                    enrichment_result_summary(event_id)
                    if consumer_name == ENRICHMENT_STUB
                    else None
                )
                await connection.execute(
                    text(
                        f"INSERT INTO {schema_name}.processed_events "
                        "(id, consumer_name, event_id, tenant_id, event_type, "
                        "correlation_id, processed_at, result_summary) "
                        "VALUES (:id, :consumer_name, :event_id, :tenant_id, "
                        ":event_type, :correlation_id, :processed_at, "
                        ":result_summary)"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "consumer_name": consumer_name,
                        "event_id": event_id,
                        "tenant_id": tenant_id,
                        "event_type": event_type.value,
                        "correlation_id": correlation_id,
                        "processed_at": processed_at,
                        "result_summary": result_summary,
                    },
                )
    return event_ids


# --- Acceptance #5 — isolation on a *visible* timeline -----------------------


async def test_a_visible_timeline_never_leaks_a_concurrent_sessions_rows(
    seeded, db_client, database_engine
):
    """Acceptance #5: session A's own timeline carries only A's events / reactions.

    Two leads live in the *same* Sunshine schema under two live demo sessions, each with
    its own synthesized trail. Session A, opening its *own* lead, sees exactly A's three
    event_ids and their consumer rows — none of B's event_ids appear, and every reaction
    row's `event_id` is one of A's. This is distinct from the existing "a visitor can't
    *open* B's lead = 404" proof: here the visitor opens a lead they legitimately own and
    we prove no foreign-session row contaminates that *visible* trail. The linkage rides
    `payload->>'entity_id' = lead_id` + the `event_id` join; `processed_events` carries no
    `demo_session_id`, so B's reactions can only match via a shared (globally unique)
    `event_id`, which never happens.
    """
    sunshine_tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    session_a = await mint_live_demo_session(database_engine)
    session_b = await mint_live_demo_session(database_engine)

    email_a, phone_a = unique_contact()
    lead_a = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        sunshine_tenant_id,
        first_name=unique_marker(),
        email=email_a,
        phone=phone_a,
        demo_session_id=session_a,
    )
    email_b, phone_b = unique_contact()
    lead_b = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        sunshine_tenant_id,
        first_name=unique_marker(),
        email=email_b,
        phone=phone_b,
        demo_session_id=session_b,
    )

    events_a = await _synthesize_trail(
        database_engine,
        schema_name=SUNSHINE.schema_name,
        tenant_id=sunshine_tenant_id,
        lead_id=lead_a,
        created_at=TRAIL_ANCHOR,
    )
    events_b = await _synthesize_trail(
        database_engine,
        schema_name=SUNSHINE.schema_name,
        tenant_id=sunshine_tenant_id,
        lead_id=lead_b,
        created_at=TRAIL_ANCHOR,
    )

    assert (await login_as(db_client, Role.AGENT)).status_code == 200  # Sunshine

    db_client.cookies.set(DEMO_SESSION_COOKIE_NAME, str(session_a))
    try:
        response = await db_client.get(f"/api/leads/{lead_a}/timeline")
        assert response.status_code == 200
        rows = response.json()["rows"]
    finally:
        db_client.cookies.delete(DEMO_SESSION_COOKIE_NAME)

    seen_event_ids = {row["event_id"] for row in rows}
    own_event_ids = {str(event_id) for event_id in events_a}
    foreign_event_ids = {str(event_id) for event_id in events_b}

    # A's timeline carries exactly A's three event_ids — no more, no fewer.
    assert seen_event_ids == own_event_ids
    # Not one of B's event_ids leaks in (the no-cross-contamination proof).
    assert seen_event_ids.isdisjoint(foreign_event_ids)
    # And every reaction row hangs off one of A's events, never a foreign one.
    reaction_event_ids = {
        row["event_id"] for row in rows if row["kind"] == "reaction"
    }
    assert reaction_event_ids, "expected at least one reaction row"
    assert reaction_event_ids <= own_event_ids


async def test_a_visible_timeline_never_leaks_another_tenants_rows(
    seeded, db_client, database_engine
):
    """Acceptance #5 (cross-tenant reaffirmation): no Florida row reaches a Sunshine read.

    A Sunshine lead and a Florida lead each get a synthesized trail. A Sunshine Agent
    opens the Sunshine lead's timeline and sees only its own three event_ids; the Florida
    trail's event_ids never appear. `get_tenant_db` scopes the outbox query to Sunshine's
    schema, so Florida's rows are physically out of reach — schema isolation reaffirmed on
    the visible-timeline surface, not just the 404 open-probe.
    """
    sunshine_tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    florida_tenant_id = await tenant_id_for_slug(database_engine, FLORIDA.slug)

    email_s, phone_s = unique_contact()
    sunshine_lead = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        sunshine_tenant_id,
        first_name=unique_marker(),
        email=email_s,
        phone=phone_s,
    )
    email_f, phone_f = unique_contact()
    florida_lead = await insert_lead(
        database_engine,
        FLORIDA.schema_name,
        florida_tenant_id,
        first_name=unique_marker(),
        email=email_f,
        phone=phone_f,
    )

    sunshine_events = await _synthesize_trail(
        database_engine,
        schema_name=SUNSHINE.schema_name,
        tenant_id=sunshine_tenant_id,
        lead_id=sunshine_lead,
        created_at=TRAIL_ANCHOR,
    )
    florida_events = await _synthesize_trail(
        database_engine,
        schema_name=FLORIDA.schema_name,
        tenant_id=florida_tenant_id,
        lead_id=florida_lead,
        created_at=TRAIL_ANCHOR,
    )

    assert (await login_as(db_client, Role.AGENT)).status_code == 200  # Sunshine
    response = await db_client.get(f"/api/leads/{sunshine_lead}/timeline")
    assert response.status_code == 200
    rows = response.json()["rows"]

    seen_event_ids = {row["event_id"] for row in rows}
    assert seen_event_ids == {str(event_id) for event_id in sunshine_events}
    assert seen_event_ids.isdisjoint(
        {str(event_id) for event_id in florida_events}
    )


# --- Acceptance #2 / #3 — the seeded coherent trail, through the endpoint -----


async def _baseline_lead_id_with_status(database_engine, schema_name, status_value):
    """Return one seeded baseline (`demo_session_id IS NULL`) lead id of a status.

    Keyed on the explicit status; the shared container's seed always carries the three
    baseline status variants per tenant, so this resolves a stable, openable seed lead.
    """
    async with database_engine.connect() as connection:
        return (
            await connection.execute(
                text(
                    f"SELECT id FROM {schema_name}.leads "
                    "WHERE status = :status AND demo_session_id IS NULL LIMIT 1"
                ),
                {"status": status_value},
            )
        ).scalar_one()


async def test_seeded_qualified_lead_opens_with_a_coherent_done_trail(
    seeded, db_client, database_engine
):
    """Acceptance #2: a seeded Qualified lead opens (via HTTP) with a full `done` trail.

    Through the real endpoint, not just the seed layer: the trail is created → assigned →
    qualified oldest-first, every reaction terminal `done`, the enrichment reaction carries
    its deterministic quality-score summary (matching `enrichment_result_summary` for that
    event), and `sync.logger` carries a null summary. One shared correlation id — one trace.
    """
    sunshine_tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    lead_id = await _baseline_lead_id_with_status(
        database_engine, SUNSHINE.schema_name, LeadStatus.QUALIFIED.value
    )

    assert (await login_as(db_client, Role.AGENT)).status_code == 200  # Sunshine
    response = await db_client.get(f"/api/leads/{lead_id}/timeline")
    assert response.status_code == 200
    rows = response.json()["rows"]
    assert rows, "a seeded baseline lead must open with a non-empty trail"

    # Coherent, status-derived, oldest-first.
    event_types = [row["event_type"] for row in rows if row["kind"] == "event"]
    assert event_types == ["lead.created", "lead.assigned", "lead.qualified"]
    # One trace across the whole trail.
    assert len({row["correlation_id"] for row in rows}) == 1

    reactions = [row for row in rows if row["kind"] == "reaction"]
    assert reactions, "expected reaction rows on the seeded trail"
    # Every reaction is terminal `done` (the seed sets `published_at = occurred_at`).
    assert all(reaction["status"] == "done" for reaction in reactions)

    created_event = next(
        row
        for row in rows
        if row["kind"] == "event" and row["event_type"] == "lead.created"
    )
    enrichment = next(
        reaction
        for reaction in reactions
        if reaction["event_id"] == created_event["event_id"]
        and reaction["consumer_name"] == ENRICHMENT_STUB
    )
    # The quality score appears and matches the shared derivation (seed == live).
    assert enrichment["result_summary"] == enrichment_result_summary(
        uuid.UUID(created_event["event_id"])
    )
    # Every sync.logger reaction is done with a null summary (a logger yields no result).
    sync_reactions = [
        reaction for reaction in reactions if reaction["consumer_name"] == SYNC_LOGGER
    ]
    assert sync_reactions
    assert all(reaction["result_summary"] is None for reaction in sync_reactions)


async def test_seeded_created_event_shows_both_stub_reactions_as_siblings(
    seeded, db_client, database_engine
):
    """Acceptance #3: `lead.created` returns both stub reactions as sibling rows.

    Through the endpoint, `lead.created` fans out to `enrichment.stub` *and* `sync.logger`
    as sibling reaction rows in registry order — the two stub kinds the BRD requires the
    timeline to show side by side.
    """
    lead_id = await _baseline_lead_id_with_status(
        database_engine, SUNSHINE.schema_name, LeadStatus.WORKING.value
    )

    assert (await login_as(db_client, Role.AGENT)).status_code == 200  # Sunshine
    response = await db_client.get(f"/api/leads/{lead_id}/timeline")
    assert response.status_code == 200
    rows = response.json()["rows"]

    created_event = next(
        row
        for row in rows
        if row["kind"] == "event" and row["event_type"] == "lead.created"
    )
    created_reaction_consumers = [
        row["consumer_name"]
        for row in rows
        if row["kind"] == "reaction" and row["event_id"] == created_event["event_id"]
    ]
    assert created_reaction_consumers == [ENRICHMENT_STUB, SYNC_LOGGER]
