"""DB tests for the boot seed's synthesized event trails on baseline leads — P1.9 Epic 5.

The boot seed inserts the shared read-only historical leads (`SHARED_HISTORICAL_LEADS`,
2 Working / 2 Qualified / 2 Rejected per tenant). Epic 5 extends that seed so each
baseline lead also opens with a coherent, status-derived event timeline — never empty.
For each lead the seed synthesizes its `outbox` event trail (`lead.created` always;
`+ lead.assigned` because every baseline lead is owned; `+ lead.qualified` / `lead.rejected`
for the terminal status) plus one `done` `processed_events` row per consumer the catalog
fans each event out to (`enrichment.stub` carrying `enrichment_result_summary(event_id)`,
`sync.logger` carrying null). All rows are `demo_session_id IS NULL`, backdated, and ride
the lead's own `correlation_id`.

These run against the real Postgres booted in Docker (the same `database_engine` substrate
as the other seed tests). The container database is **session-scoped and shared**, so each
test first **clears** both tenants' `leads`, `outbox`, and `processed_events` tables —
owning its precondition — then seeds. The seeded outbox rows carry `published_at = occurred_at`,
so the read-time reaction derivation reports every reaction `done`. The timeline read
(`get_lead_timeline_rows`) is schema-less (search-path-bound), so each read sets the
session `search_path` to the tenant schema first. `pytest.ini` sets `asyncio_mode = auto`,
so the async tests carry no decorator.
"""

import uuid

from sqlalchemy import text

from app.events.catalog import ENRICHMENT_STUB, SYNC_LOGGER
from app.events.enrichment import enrichment_result_summary
from app.leads.state import LeadStatus
from app.leads.timeline import get_lead_timeline_rows
from app.seed import seed
from app.tenancy.registry import FLORIDA, SUNSHINE


async def _clear_demo_trails(db_session) -> None:
    """Empty both tenants' `leads`, `outbox`, and `processed_events` tables.

    The container database is shared across the whole test session, so this owns the
    precondition for the count assertions below regardless of what other tests wrote.
    The schema identifiers come only from the registry, never user input. Committed so
    the seed (its own transaction) sees the cleared tables.
    """
    for schema_name in (SUNSHINE.schema_name, FLORIDA.schema_name):
        await db_session.execute(text(f"DELETE FROM {schema_name}.processed_events"))
        await db_session.execute(text(f"DELETE FROM {schema_name}.outbox"))
        await db_session.execute(text(f"DELETE FROM {schema_name}.leads"))
    await db_session.commit()


async def _lead_id_for_status(db_session, schema_name: str, status: LeadStatus):
    """Return the id of one seeded baseline lead with the given status."""
    return (
        await db_session.execute(
            text(
                f"SELECT id FROM {schema_name}.leads "
                "WHERE status = :status AND demo_session_id IS NULL LIMIT 1"
            ),
            {"status": status.value},
        )
    ).scalar_one()


async def _timeline_rows(db_session, schema_name: str, lead_id: uuid.UUID) -> list[dict]:
    """Read one lead's merged timeline rows under the tenant schema's search_path.

    `get_lead_timeline_rows` resolves the schema-less `outbox` / `processed_events`
    against the active `search_path`, so the session is pointed at the tenant schema
    (then the public schema for anything else) before the read.
    """
    await db_session.execute(text(f"SET search_path TO {schema_name}, public"))
    rows = await get_lead_timeline_rows(db_session, lead_id)
    await db_session.execute(text("SET search_path TO public"))
    return rows


async def _count(db_session, schema_name: str, table: str) -> int:
    """Return the row count of `<schema_name>.<table>`."""
    return (
        await db_session.execute(
            text(f"SELECT COUNT(*) FROM {schema_name}.{table}")
        )
    ).scalar_one()


def _event_types(rows: list[dict]) -> list[str]:
    """The event-row event types from a merged timeline, in their oldest-first order."""
    return [row["event_type"] for row in rows if row["kind"] == "event"]


def _reactions_for_event(rows: list[dict], event_id: str) -> list[dict]:
    """The reaction rows of a merged timeline that belong to one event id."""
    return [
        row
        for row in rows
        if row["kind"] == "reaction" and row["event_id"] == event_id
    ]


async def test_working_lead_opens_with_created_then_assigned(
    container_keys_session_factory, db_session
):
    """A seeded Working baseline lead's timeline shows lead.created then lead.assigned.

    Every baseline lead is owned, so the trail always carries `lead.assigned`; a
    Working lead has no terminal event, so the trail stops there — oldest-first.
    """
    await _clear_demo_trails(db_session)
    await seed(db_session)

    lead_id = await _lead_id_for_status(
        db_session, SUNSHINE.schema_name, LeadStatus.WORKING
    )
    rows = await _timeline_rows(db_session, SUNSHINE.schema_name, lead_id)

    assert _event_types(rows) == ["lead.created", "lead.assigned"]
    # One shared correlation id across the whole trail (one trace per lead).
    assert len({row["correlation_id"] for row in rows}) == 1


async def test_qualified_lead_adds_the_qualified_event(
    container_keys_session_factory, db_session
):
    """A seeded Qualified baseline lead adds lead.qualified after created/assigned."""
    await _clear_demo_trails(db_session)
    await seed(db_session)

    lead_id = await _lead_id_for_status(
        db_session, SUNSHINE.schema_name, LeadStatus.QUALIFIED
    )
    rows = await _timeline_rows(db_session, SUNSHINE.schema_name, lead_id)

    assert _event_types(rows) == ["lead.created", "lead.assigned", "lead.qualified"]


async def test_rejected_lead_adds_the_rejected_event(
    container_keys_session_factory, db_session
):
    """A seeded Rejected baseline lead adds lead.rejected after created/assigned."""
    await _clear_demo_trails(db_session)
    await seed(db_session)

    lead_id = await _lead_id_for_status(
        db_session, SUNSHINE.schema_name, LeadStatus.REJECTED
    )
    rows = await _timeline_rows(db_session, SUNSHINE.schema_name, lead_id)

    assert _event_types(rows) == ["lead.created", "lead.assigned", "lead.rejected"]


async def test_every_baseline_status_variant_opens_non_empty(
    container_keys_session_factory, db_session
):
    """No baseline status variant (Working/Qualified/Rejected) opens with an empty timeline."""
    await _clear_demo_trails(db_session)
    await seed(db_session)

    for status in (LeadStatus.WORKING, LeadStatus.QUALIFIED, LeadStatus.REJECTED):
        for schema_name in (SUNSHINE.schema_name, FLORIDA.schema_name):
            lead_id = await _lead_id_for_status(db_session, schema_name, status)
            rows = await _timeline_rows(db_session, schema_name, lead_id)
            assert rows, f"{status.value} lead in {schema_name} opened empty"


async def test_enrichment_reaction_is_done_with_the_matching_quality_score(
    container_keys_session_factory, db_session
):
    """The seeded enrichment reaction is `done` and carries the deterministic quality score.

    The enrichment.stub reaction fires on lead.created; the seeded score equals
    `enrichment_result_summary(event_id)` for that event — proving the seed reuses the
    shared derivation rather than re-deriving it, so seed == live.
    """
    await _clear_demo_trails(db_session)
    await seed(db_session)

    lead_id = await _lead_id_for_status(
        db_session, SUNSHINE.schema_name, LeadStatus.WORKING
    )
    rows = await _timeline_rows(db_session, SUNSHINE.schema_name, lead_id)

    created_event = next(
        row for row in rows if row["kind"] == "event" and row["event_type"] == "lead.created"
    )
    enrichment = next(
        row
        for row in _reactions_for_event(rows, created_event["event_id"])
        if row["consumer_name"] == ENRICHMENT_STUB
    )
    assert enrichment["status"] == "done"
    expected = enrichment_result_summary(uuid.UUID(created_event["event_id"]))
    assert enrichment["result_summary"] == expected


async def test_sync_logger_reactions_are_done_with_null_summary(
    container_keys_session_factory, db_session
):
    """Every sync.logger reaction is `done` and carries a null result summary."""
    await _clear_demo_trails(db_session)
    await seed(db_session)

    lead_id = await _lead_id_for_status(
        db_session, SUNSHINE.schema_name, LeadStatus.QUALIFIED
    )
    rows = await _timeline_rows(db_session, SUNSHINE.schema_name, lead_id)

    sync_reactions = [
        row
        for row in rows
        if row["kind"] == "reaction" and row["consumer_name"] == SYNC_LOGGER
    ]
    assert sync_reactions, "expected at least one sync.logger reaction"
    for reaction in sync_reactions:
        assert reaction["status"] == "done"
        assert reaction["result_summary"] is None


async def test_created_fans_out_to_both_consumers_lifecycle_to_sync_logger_only(
    container_keys_session_factory, db_session
):
    """lead.created seeds both enrichment.stub and sync.logger; lifecycle events sync.logger only."""
    await _clear_demo_trails(db_session)
    await seed(db_session)

    lead_id = await _lead_id_for_status(
        db_session, SUNSHINE.schema_name, LeadStatus.QUALIFIED
    )
    rows = await _timeline_rows(db_session, SUNSHINE.schema_name, lead_id)

    by_type = {
        row["event_type"]: row["event_id"]
        for row in rows
        if row["kind"] == "event"
    }

    created_consumers = [
        row["consumer_name"]
        for row in _reactions_for_event(rows, by_type["lead.created"])
    ]
    assert created_consumers == [ENRICHMENT_STUB, SYNC_LOGGER]

    for lifecycle_type in ("lead.assigned", "lead.qualified"):
        consumers = [
            row["consumer_name"]
            for row in _reactions_for_event(rows, by_type[lifecycle_type])
        ]
        assert consumers == [SYNC_LOGGER]


async def test_re_seed_inserts_no_duplicate_trails(
    container_keys_session_factory, db_session
):
    """A second boot seed adds zero new outbox / processed_events rows (idempotent).

    The synthesis lives inside the seed's `demo_session_id IS NULL` count-gate, so a
    re-seed that finds baseline leads skips the whole block — trails never duplicate.
    """
    await _clear_demo_trails(db_session)
    await seed(db_session)

    outbox_after_first = {
        schema: await _count(db_session, schema, "outbox")
        for schema in (SUNSHINE.schema_name, FLORIDA.schema_name)
    }
    processed_after_first = {
        schema: await _count(db_session, schema, "processed_events")
        for schema in (SUNSHINE.schema_name, FLORIDA.schema_name)
    }

    await seed(db_session)

    for schema in (SUNSHINE.schema_name, FLORIDA.schema_name):
        assert await _count(db_session, schema, "outbox") == outbox_after_first[schema]
        assert (
            await _count(db_session, schema, "processed_events")
            == processed_after_first[schema]
        )
    # And the trail is actually non-empty (guards against a vacuous all-zero pass).
    assert all(count > 0 for count in outbox_after_first.values())
    assert all(count > 0 for count in processed_after_first.values())
