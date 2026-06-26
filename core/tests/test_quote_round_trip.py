"""DB-backed proof of the carrier-quote round-trip tracer (P2.3 Epic 3).

The one new event-driven flow end to end on the real Postgres substrate:

- **`POST /api/opportunities/{id}/quote-requests`** opens a round-trip — writes a
  `quote_requests` row `pending` and enqueues `quote.requested` on the request
  transaction. Pre-checks: the opportunity must be *Qualified* (else 409) and clear
  the Medicare gate (else 422).
- **The `carrier.quote` consumer effect** (`complete_quote_request`) generates the
  options from the registry catalog, writes the `quotes` rows, marks the request
  `completed`, enqueues `quote.completed`, and moves the opportunity to *Quoted* —
  all idempotently (a redelivery is a no-op).
- **`GET /api/opportunities/{id}/quote-requests/{rid}`** polls the status and, once
  `completed`, renders the attached options — a pure read.

These drive the real endpoints over the DB-backed client (the `seeded` / `db_client`
/ `database_engine` substrate the other endpoint tests use) and invoke the consumer
effect directly, pointing its module-global `session_factory` at the container
database (the `container_consumers_session_factory` idiom from `test_consumers.py`).
The opportunity under test is born the honest way — converting a held `Qualified`
lead — then forced to a start stage.

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no decorator.
Seams reused by name: `convert_opportunity_for_slug` / `set_stage` /
`set_contact_age_band` from `test_opportunity_stage.py`; `read_outbox_rows_for_entity`
from `test_lead_intake.py`; `tenant_id_for_slug` from `test_lead_reads.py`;
`login_as` / `seeded` from `test_endpoints_db.py`.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.events.catalog import EventType
from app.events.envelope import build_envelope
from app.models.user import Role
from app.quotes import service as quotes_service_module
from app.tenancy.registry import SUNSHINE

from tests.test_endpoints_db import login_as, seeded  # noqa: F401
from tests.test_lead_intake import read_outbox_rows_for_entity
from tests.test_lead_reads import tenant_id_for_slug
from tests.test_opportunity_stage import (
    convert_opportunity_for_slug,
    set_contact_age_band,
    set_stage,
)

# The final-expense line is non-Medicare-gated and carries three option templates
# (registry Epic 2), so a clean round-trip yields exactly three quotes.
HAPPY_PATH_LINE = "final_expense"
HAPPY_PATH_QUOTE_COUNT = 3


@pytest.fixture
def container_quotes_session_factory(database_engine, monkeypatch):
    """Point `app.quotes.service.session_factory` at the migrated container database.

    The `carrier.quote` consumer effect opens its **own** session through the
    module-global `app.quotes.service.session_factory` — separate from any request's
    `get_db`, the own-session shape `test_consumers.py` patches for the stub
    consumers. The DB substrate must point that global at the container database,
    else the effect's domain write would hit the unreachable eager default engine.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    monkeypatch.setattr(quotes_service_module, "session_factory", session_factory)
    return session_factory


async def qualified_opportunity(db_client, database_engine, product_line):
    """Convert a Sunshine opportunity on `product_line` and force it to *Qualified*.

    Returns the opportunity id. The `db_client` is left logged in as the owning
    agent (so it clears the holder guard on the quote-request endpoint).
    """
    opportunity_id = await convert_opportunity_for_slug(
        db_client, database_engine, SUNSHINE, product_line
    )
    await set_stage(database_engine, SUNSHINE.schema_name, opportunity_id, "Qualified")
    return opportunity_id


def quote_requested_envelope(tenant_id, quote_request_id, opportunity_id, product_line):
    """Build the `quote.requested` envelope the relay would hand the consumer.

    The effect reads the request row from the DB by `entity_id`, so only the tenant
    routing id and the `entity_id` payload key matter; the rest mirrors the real
    `request_quotes` enqueue for fidelity.
    """
    return build_envelope(
        event_type=EventType.QUOTE_REQUESTED,
        tenant_id=tenant_id,
        actor_user_id=uuid.uuid4(),
        actor_role=Role.AGENT.value,
        payload={
            "entity_id": str(quote_request_id),
            "opportunity_id": str(opportunity_id),
            "product_line": product_line,
        },
    )


async def count_quotes(database_engine, schema_name, quote_request_id):
    """Count `quotes` rows for one request, via the SELECT-capable superuser engine."""
    async with database_engine.connect() as connection:
        return (
            await connection.execute(
                text(
                    f"SELECT count(*) FROM {schema_name}.quotes "
                    "WHERE quote_request_id = :rid"
                ),
                {"rid": quote_request_id},
            )
        ).scalar_one()


async def test_quote_round_trip_attaches_options_and_moves_to_quoted(
    db_client, database_engine, seeded, container_quotes_session_factory
):
    """Request → consume → poll: options attach and the opportunity reaches *Quoted*."""
    opportunity_id = await qualified_opportunity(db_client, database_engine, HAPPY_PATH_LINE)
    tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)

    # Request: a pending round-trip + a quote.requested outbox row on the request txn.
    request_response = await db_client.post(
        f"/api/opportunities/{opportunity_id}/quote-requests"
    )
    assert request_response.status_code == 200
    body = request_response.json()["quote_request"]
    assert body["status"] == "pending"
    quote_request_id = uuid.UUID(body["id"])

    requested_rows = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.QUOTE_REQUESTED, quote_request_id
    )
    assert len(requested_rows) == 1

    # Consume: the effect generates the options, completes the request, advances stage.
    await quotes_service_module.complete_quote_request(
        quote_requested_envelope(
            tenant_id, quote_request_id, opportunity_id, HAPPY_PATH_LINE
        ),
        SUNSHINE.schema_name,
    )
    assert await count_quotes(database_engine, SUNSHINE.schema_name, quote_request_id) == (
        HAPPY_PATH_QUOTE_COUNT
    )

    completed_rows = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.QUOTE_COMPLETED, quote_request_id
    )
    assert len(completed_rows) == 1
    stage_rows = await read_outbox_rows_for_entity(
        database_engine,
        SUNSHINE.schema_name,
        EventType.OPPORTUNITY_STAGE_CHANGED,
        opportunity_id,
    )
    assert any(row.payload["to_stage"] == "Quoted" for row in stage_rows)

    # Poll: the completed request renders its options and reflects the Quoted move.
    poll_response = await db_client.get(
        f"/api/opportunities/{opportunity_id}/quote-requests/{quote_request_id}"
    )
    assert poll_response.status_code == 200
    poll = poll_response.json()
    assert poll["quote_request"]["status"] == "completed"
    assert len(poll["quotes"]) == HAPPY_PATH_QUOTE_COUNT
    assert poll["opportunity_stage"] == "Quoted"
    # Every option carries the registry shape, annual = monthly × 12.
    for quote in poll["quotes"]:
        assert quote["premium_annual"] == quote["premium_monthly"] * 12
        assert quote["coverage_amount"] > 0


async def test_quote_completion_is_idempotent_on_redelivery(
    db_client, database_engine, seeded, container_quotes_session_factory
):
    """A redelivered quote.requested is a no-op — the options are never duplicated."""
    opportunity_id = await qualified_opportunity(db_client, database_engine, HAPPY_PATH_LINE)
    tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    request_response = await db_client.post(
        f"/api/opportunities/{opportunity_id}/quote-requests"
    )
    quote_request_id = uuid.UUID(request_response.json()["quote_request"]["id"])
    envelope = quote_requested_envelope(
        tenant_id, quote_request_id, opportunity_id, HAPPY_PATH_LINE
    )

    await quotes_service_module.complete_quote_request(envelope, SUNSHINE.schema_name)
    await quotes_service_module.complete_quote_request(envelope, SUNSHINE.schema_name)

    # Still exactly one set of options, and exactly one completion event.
    assert await count_quotes(database_engine, SUNSHINE.schema_name, quote_request_id) == (
        HAPPY_PATH_QUOTE_COUNT
    )
    completed_rows = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.QUOTE_COMPLETED, quote_request_id
    )
    assert len(completed_rows) == 1


async def test_poll_before_completion_returns_pending_with_no_options(
    db_client, database_engine, seeded
):
    """Polling a still-pending request returns `pending` and an empty quote list."""
    opportunity_id = await qualified_opportunity(db_client, database_engine, HAPPY_PATH_LINE)
    request_response = await db_client.post(
        f"/api/opportunities/{opportunity_id}/quote-requests"
    )
    quote_request_id = request_response.json()["quote_request"]["id"]

    poll_response = await db_client.get(
        f"/api/opportunities/{opportunity_id}/quote-requests/{quote_request_id}"
    )
    assert poll_response.status_code == 200
    poll = poll_response.json()
    assert poll["quote_request"]["status"] == "pending"
    assert poll["quotes"] == []
    assert poll["opportunity_stage"] == "Qualified"


async def test_request_quotes_requires_a_qualified_opportunity(
    db_client, database_engine, seeded
):
    """Requesting quotes from a non-Qualified opportunity is a 409."""
    opportunity_id = await convert_opportunity_for_slug(
        db_client, database_engine, SUNSHINE, HAPPY_PATH_LINE
    )
    # Left at the born stage `New` — never advanced to Qualified.
    response = await db_client.post(
        f"/api/opportunities/{opportunity_id}/quote-requests"
    )
    assert response.status_code == 409


async def test_request_quotes_is_blocked_for_an_under_65_medicare_line(
    db_client, database_engine, seeded
):
    """A Medicare-gated line for an under-65 contact is a 422, with no round-trip opened."""
    opportunity_id = await qualified_opportunity(
        db_client, database_engine, "medicare_advantage"
    )
    await set_contact_age_band(
        database_engine, SUNSHINE.schema_name, opportunity_id, "55-64"
    )
    response = await db_client.post(
        f"/api/opportunities/{opportunity_id}/quote-requests"
    )
    assert response.status_code == 422
