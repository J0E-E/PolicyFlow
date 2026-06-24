"""Unit test for the reaction-row synthesis + status derivation (P1.9 Epic 2).

`get_lead_timeline_rows` merges a lead's outbox events with synthesized reaction
sibling rows: each event row is followed by one reaction row per consumer that
binds the event type (from the catalog `consumers_for_event_type`), and each
reaction's status is *derived* from real bus state — never stored:

- **pending** — the parent event is unpublished (`published_at IS NULL`); the relay
  has not fanned it out yet.
- **processing** — the parent event is published but the consumer has recorded no
  `processed_events` row yet; it is mid-flight.
- **done** — a `processed_events` row exists for that `(event_id, consumer_name)`.

`failed` is in the vocabulary but dormant — this derivation never emits it.

These are pure-logic tests over a tiny fake `AsyncSession` (the matcher-test
pattern in `test_lead_matching.py`), so no DB / Docker / async fixtures: the two
queries the function runs (events, then `processed_events`) are answered from
canned rows by call order. `pytest.ini` sets `asyncio_mode = auto`, so the async
tests carry no decorator.
"""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from app.events.catalog import ENRICHMENT_STUB, SYNC_LOGGER
from app.leads.timeline import get_lead_timeline_rows

LEAD_ID = uuid.uuid4()


def make_event(event_type: str, *, is_published: bool):
    """Build a fake outbox-event row carrying just the fields the read touches."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        event_type=event_type,
        correlation_id=uuid.uuid4(),
        occurred_at=datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc),
        published_at=(
            datetime(2026, 6, 24, 12, 0, 1, tzinfo=timezone.utc)
            if is_published
            else None
        ),
    )


def make_processed_row(event_id: uuid.UUID, consumer_name: str, *, result_summary=None):
    """Build a fake `processed_events` row for one `(event_id, consumer_name)`."""
    return SimpleNamespace(
        event_id=event_id,
        consumer_name=consumer_name,
        processed_at=datetime(2026, 6, 24, 12, 0, 2, tzinfo=timezone.utc),
        result_summary=result_summary,
    )


class FakeScalarResult:
    """The thin slice of a SQLAlchemy `Result` the read reaches for: `scalars().all()`."""

    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class FakeSession:
    """A stand-in `AsyncSession` answering the read's two queries by call order.

    `get_lead_timeline_rows` runs the events query first, then (only when events
    exist) the `processed_events` query, so the fake returns the pre-set events on
    the first `execute` and the pre-set processed rows on the second. No real
    database is touched.
    """

    def __init__(self, events, processed_rows):
        self._results = [FakeScalarResult(events), FakeScalarResult(processed_rows)]
        self._call_index = 0

    async def execute(self, query):
        result = self._results[self._call_index]
        self._call_index += 1
        return result


def reaction_rows(rows):
    """The reaction rows from a merged timeline, in their merged order."""
    return [row for row in rows if row["kind"] == "reaction"]


async def test_reaction_is_pending_when_parent_event_unpublished():
    """An unpublished parent event's reactions all read `pending` with no `occurred_at`."""
    event = make_event("lead.created", is_published=False)
    session = FakeSession([event], [])

    rows = await get_lead_timeline_rows(session, LEAD_ID)

    for reaction in reaction_rows(rows):
        assert reaction["status"] == "pending"
        assert reaction["occurred_at"] is None
        assert reaction["result_summary"] is None


async def test_reaction_is_processing_when_published_but_unprocessed():
    """A published parent with no processed row reads `processing` (mid-flight)."""
    event = make_event("lead.qualified", is_published=True)
    session = FakeSession([event], [])

    rows = await get_lead_timeline_rows(session, LEAD_ID)

    reactions = reaction_rows(rows)
    assert reactions, "expected at least one reaction"
    for reaction in reactions:
        assert reaction["status"] == "processing"
        assert reaction["occurred_at"] is None


async def test_reaction_is_done_when_a_processed_row_exists():
    """A processed row flips that one reaction to `done` with the row's `processed_at`."""
    event = make_event("lead.qualified", is_published=True)
    processed = make_processed_row(event.event_id, SYNC_LOGGER)
    session = FakeSession([event], [processed])

    rows = await get_lead_timeline_rows(session, LEAD_ID)

    sync_reaction = next(
        reaction
        for reaction in reaction_rows(rows)
        if reaction["consumer_name"] == SYNC_LOGGER
    )
    assert sync_reaction["status"] == "done"
    assert sync_reaction["occurred_at"] == processed.processed_at.isoformat()


async def test_done_reaction_passes_result_summary_through_verbatim():
    """A processed row's `result_summary` is passed through verbatim onto the reaction.

    Null until Epic 3 fills the column; here a non-null value proves the read forwards
    whatever the processed row carries rather than hardcoding ``None``.
    """
    event = make_event("lead.qualified", is_published=True)
    processed = make_processed_row(
        event.event_id, SYNC_LOGGER, result_summary="quality score: 87"
    )
    session = FakeSession([event], [processed])

    rows = await get_lead_timeline_rows(session, LEAD_ID)

    sync_reaction = next(
        reaction
        for reaction in reaction_rows(rows)
        if reaction["consumer_name"] == SYNC_LOGGER
    )
    assert sync_reaction["result_summary"] == "quality score: 87"


async def test_lead_created_fans_out_to_both_consumers_in_binding_order():
    """`lead.created` synthesizes enrichment then sync-logger reaction rows, in order."""
    event = make_event("lead.created", is_published=True)
    session = FakeSession([event], [])

    rows = await get_lead_timeline_rows(session, LEAD_ID)

    consumer_names = [reaction["consumer_name"] for reaction in reaction_rows(rows)]
    assert consumer_names == [ENRICHMENT_STUB, SYNC_LOGGER]


async def test_other_lead_event_fans_out_to_sync_logger_only():
    """A `lead.assigned` event synthesizes a single sync-logger reaction (via `#`)."""
    event = make_event("lead.assigned", is_published=True)
    session = FakeSession([event], [])

    rows = await get_lead_timeline_rows(session, LEAD_ID)

    consumer_names = [reaction["consumer_name"] for reaction in reaction_rows(rows)]
    assert consumer_names == [SYNC_LOGGER]


async def test_each_reaction_follows_its_parent_event_oldest_first():
    """The merged list is event, its reactions, next event, its reactions — oldest-first.

    Two events (created then assigned) produce: the created event, its two reactions,
    then the assigned event, its one reaction — each reaction immediately under its
    own parent, and reaction rows carry the parent's event_id / correlation_id.
    """
    created = make_event("lead.created", is_published=True)
    assigned = make_event("lead.assigned", is_published=True)
    session = FakeSession([created, assigned], [])

    rows = await get_lead_timeline_rows(session, LEAD_ID)

    kinds = [row["kind"] for row in rows]
    assert kinds == ["event", "reaction", "reaction", "event", "reaction"]

    # The first three rows belong to `created`; the last two to `assigned`.
    created_event_id = str(created.event_id)
    assigned_event_id = str(assigned.event_id)
    assert rows[0]["event_id"] == created_event_id
    assert rows[1]["event_id"] == created_event_id
    assert rows[2]["event_id"] == created_event_id
    assert rows[3]["event_id"] == assigned_event_id
    assert rows[4]["event_id"] == assigned_event_id
    # Each reaction inherits its parent's correlation id.
    assert rows[1]["correlation_id"] == str(created.correlation_id)
    assert rows[4]["correlation_id"] == str(assigned.correlation_id)
