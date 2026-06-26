"""The named acceptance suite (Epic 14, P1.8) — the demo-session lifecycle, end-to-end.

Epics 1–12 built every piece of the P1.8 demo-session lifecycle: the per-visit
`demo_sessions` row + `pf_demo_session` cookie, the session-tagged private New-queue
instantiated on assume-persona (idempotent via the `demo_session_tenant_seed`
ledger), the `visible_to_session` read predicate that hides one visitor's overlay
from another while keeping the shared `demo_session_id IS NULL` historical baseline
visible to all, the `demo_session_id` write-tag flowing onto the lead row **and** its
`lead.created` event, the tri-state `GET /api/demo/session` state read, the
scope-parameterized purge engine (`Session` / `Expired` / `All`), and the visitor's
own `POST /api/demo/session/reset`. This file is the single named proof that the
whole phase contract holds end-to-end on the real substrate.

It adds **no production code.** It drives the already-assembled path on the real
Postgres + RabbitMQ testcontainers, in five append-only phases (simplest first):

- **Phase 1 — write-tagging proven through the broker (the thin end-to-end thread).**
  Assume-persona mints a session; a `POST /api/leads` create tags the lead **row**
  and its `lead.created` **outbox** row with the same `demo_session_id`; and after
  `publish_pending_once` the drained AMQP message round-trips to an envelope still
  carrying `demo_session_id` on the wire (the only proof needing real RabbitMQ).
- **Phase 2 — `GET /api/demo/session` reports active / expired / none.** A live
  session reads `active`; a back-dated `expires_at` reads `expired`; no cookie reads
  `none`.
- **Phase 3 — ledger idempotency.** A second assume-persona for the same session +
  tenant instantiates **no** new queue rows (the ledger marker makes it a no-op),
  proven across both tenant schemas.
- **Phase 4 — read isolation.** Two assume-persona sessions A and B (two clients,
  separate cookie jars). A's created lead is invisible to B — B's
  `GET /api/leads/{a_lead_id}` is 404 and B's list / unassigned queue exclude it —
  while BOTH see the shared `NULL` historical baseline.
- **Phase 5 — purge scopes across BOTH tenant schemas.** `Session` via
  `POST /api/demo/session/reset` (HTTP); `Expired` + `All` via `purge_sessions(...)`
  direct (no operator HTTP trigger beyond the CLI). Each deletes exactly its scope
  across SUNSHINE **and** FLORIDA; the `demo_session_id IS NULL` baseline survives
  all three.

**Drive style is hybrid** — black-box HTTP through every public surface that exists
(assume-persona, lead intake, the leads reads, the session-state endpoint, the reset
endpoint); `purge_sessions(...)` direct only for `Expired` / `All`. Every row
read-back goes through the SELECT-capable superuser `database_engine` connection,
schema-qualified (the tenant role's grants are scoped).

**Robustness against the never-reset substrate.** The container Postgres **and**
RabbitMQ are session-scoped and never reset between tests, and `publish_pending_once`
drains **every** pending outbox row across all tenants. So every assertion keys on
**this** run's own ids — the minted `demo_session_id`, the created lead id, the
event's `event_id` / `message_id` — never on "the table is empty" or a global count.
The one exception is the `All`-scope purge, whose exact-count assertions need a clean
`demo_sessions` slate; that phase wipes both tenants' `leads` + the ledger + the
`demo_sessions` table and re-seeds in setup (the `test_demo_purge_scopes.py` idiom),
then keys on its own freshly-minted ids.

Because `httpx.ASGITransport` does not fire the app lifespan, the broker phase drives
the relay **explicitly** (the established `test_relay.py` / `test_event_bus_acceptance.py`
pattern): the relay opens its **own** session through a module-global
`app.events.relay.session_factory`, so the per-file `container_relay_session_factory`
fixture points that global at the container. The purge engine opens its own
`demo_purge`-role session through `app.demo.purge.session_factory`, pointed at the
container by `container_purge_session_factory`. And because assume-persona seeds a
session's queue by encrypting PII, the suite carries `container_keys_session_factory`.

Requires the Docker daemon (no skip logic — the substrate's deliberate "fail always
when Docker is absent" choice). `pytest.ini` sets `asyncio_mode = auto`; the
DB/broker substrate tests carry an explicit `@pytest.mark.asyncio` to match the other
substrate modules.
"""

import uuid
from datetime import datetime, timedelta, timezone

import asyncio

import aio_pika
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.demo import purge as purge_module
from app.demo.instantiation import ensure_session_leads
from app.demo.purge import All, Expired, purge_sessions
from app.demo.session import DEMO_SESSION_COOKIE_NAME
from app.events import relay as relay_module
from app.events.broker import declare_topology
from app.events.catalog import SYNC_LOGGER, EventType
from app.events.envelope import from_message_body
from app.events.relay import publish_pending_once
from app.main import app
from app.models.user import Role
from app.seed import seed
from app.tenancy.registry import FLORIDA, SUNSHINE
from tests.conftest import build_amqp_url

from .test_demo_assume_persona import assume
from .test_endpoints_db import (  # noqa: F401 — `seeded` fixture is used by name
    seeded,
)
from .test_lead_intake import read_lead_row, read_outbox_rows_for_entity, unique_contact

# The broker phase drains the published `lead.created` message off the `sync.logger`
# consumer queue: it binds on `#`, so it receives every event type — the simplest
# place to round-trip a `lead.created` envelope off the wire. (`enrichment.stub` also
# binds `lead.created`, but `sync.logger`'s `#` is unambiguous.) The name is the
# catalog constant so it can never drift from the topology.
LEAD_CREATED_DRAIN_QUEUE = SYNC_LOGGER

# A full create body the lead-intake phases reuse, with a per-call unique contact so
# the never-reset container's duplicate matcher cannot cross-match an unrelated run.
BASE_LEAD_BODY = {
    "first_name": "Acceptance",
    "last_name": "Visitor",
    "date_of_birth": "1950-03-15",
    "zip_code": "33101",
    "product_lines_of_interest": ["medicare_advantage"],
}


def lead_body() -> dict:
    """Return a fresh create body with a per-call unique email + phone."""
    email, phone = unique_contact()
    return {**BASE_LEAD_BODY, "email": email, "phone": phone}


# --- Substrate: fixtures -----------------------------------------------------


@pytest.fixture
def container_relay_session_factory(database_engine, monkeypatch):
    """Point `app.events.relay.session_factory` at the migrated container database.

    The relay opens its **own** session through this module-global (as the
    `outbox_relay` role) — separate from any request's `get_db`. The substrate must
    point that global at the container, else the relay's sweep would hit the
    unreachable eager default engine. A verbatim mirror of the same-named fixture in
    `test_relay.py` / `test_event_bus_acceptance.py`; `monkeypatch` restores the real
    factory after each test.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    monkeypatch.setattr(relay_module, "session_factory", session_factory)
    return session_factory


@pytest.fixture
def container_purge_session_factory(database_engine, monkeypatch):
    """Point `app.demo.purge.session_factory` at the migrated container database.

    The purge engine (and the reset endpoint, which runs it) opens its **own**
    session through this module-global as the `demo_purge` role — separate from the
    request's `get_db`. The substrate must point that global at the container, else
    the purge would hit the unreachable eager default engine. A mirror of the
    same-named fixture in `test_demo_purge_scopes.py` / `test_demo_session_reset_endpoint.py`;
    `monkeypatch` restores the real factory after each test.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    monkeypatch.setattr(purge_module, "session_factory", session_factory)
    return session_factory


@pytest_asyncio.fixture
async def broker_channel(rabbitmq_container):
    """Yield one aio-pika channel against the RabbitMQ container, closed after.

    Opens a single robust connection and one channel — the "one shared connection,
    one channel per task" lifecycle — and tears both down when the test finishes so
    no connection leaks across tests. A mirror of the `broker_channel` fixture in
    `test_relay.py` / `test_event_bus_acceptance.py`.
    """
    connection = await aio_pika.connect_robust(build_amqp_url(rabbitmq_container))
    channel = await connection.channel()
    try:
        yield channel
    finally:
        await channel.close()
        await connection.close()


# --- Substrate: helpers (entity- / session-pinned) ---------------------------


async def drain_for_event_id(
    broker_channel,
    queue_name,
    event_id,
    max_messages=5000,
    empty_polls=20,
    empty_poll_delay=0.1,
):
    """Get the message whose `message_id` equals `event_id` off `queue_name`.

    The container broker is never reset and `publish_pending_once` flushes **every**
    tenant's accumulated unpublished outbox rows — the whole suite's backlog — and
    `sync.logger` binds `#`, so this queue can hold a large backlog of unrelated
    messages ahead of this run's event. This `get`s (and acks, via `no_ack=True`) up
    to `max_messages`, returning the first whose AMQP `message_id` is this run's
    `event_id` and discarding the rest. `max_messages` is deliberately high so a big
    backlog cannot exhaust the budget before the target is reached (the cause of the
    earlier "never arrived" flake under full-suite load).

    An empty `get` does **not** end the drain: the relay publishes asynchronously, so
    the message can still be in flight. The drain waits out up to `empty_polls`
    **consecutive** empty reads (`empty_poll_delay` apart) for more to arrive before
    giving up; any delivery resets that counter. Returns `None` only if the matching
    message never arrives within the budget.
    """
    queue = await broker_channel.get_queue(queue_name)
    seen_messages = 0
    seen_empty = 0
    while seen_messages < max_messages and seen_empty < empty_polls:
        message = await queue.get(no_ack=True, fail=False)
        if message is None:
            seen_empty += 1
            await asyncio.sleep(empty_poll_delay)
            continue
        seen_empty = 0
        if message.message_id == str(event_id):
            return message
        seen_messages += 1
    return None


async def count_session_leads(database_engine, schema_name, demo_session_id) -> int:
    """Count `<schema>.leads` rows tagged with one demo session id (superuser read)."""
    async with database_engine.connect() as connection:
        return (
            await connection.execute(
                text(
                    f"SELECT COUNT(*) FROM {schema_name}.leads "
                    "WHERE demo_session_id = :demo_session_id"
                ),
                {"demo_session_id": demo_session_id},
            )
        ).scalar_one()


async def count_seed_baseline_leads(database_engine, schema_name) -> int:
    """Count the shared `demo_session_id IS NULL` historical baseline rows (superuser)."""
    async with database_engine.connect() as connection:
        return (
            await connection.execute(
                text(
                    f"SELECT COUNT(*) FROM {schema_name}.leads "
                    "WHERE demo_session_id IS NULL"
                )
            )
        ).scalar_one()


async def demo_session_row_exists(database_engine, demo_session_id) -> bool:
    """Return whether the `platform.demo_sessions` row still exists (superuser read)."""
    async with database_engine.connect() as connection:
        found = (
            await connection.execute(
                text("SELECT 1 FROM platform.demo_sessions WHERE id = :id"),
                {"id": demo_session_id},
            )
        ).first()
    return found is not None


async def back_date_session_expiry(database_engine, demo_session_id) -> None:
    """Force one `demo_sessions` row's `expires_at` into the past via the superuser.

    Test setup, not app behavior: the session was minted live, and this drops its
    window so `read_demo_session_state` reports it `EXPIRED` — the seam the
    `expired`-branch endpoint assertion needs without waiting out the real 24h window.
    """
    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE platform.demo_sessions SET expires_at = :expires_at "
                "WHERE id = :id"
            ),
            {
                "id": demo_session_id,
                "expires_at": datetime.now(timezone.utc) - timedelta(hours=1),
            },
        )


async def mint_session_via_agent(client) -> uuid.UUID:
    """Assume a Sunshine Agent on `client`; return the minted demo-session id.

    The black-box mint path: assuming a tenant-scoped Agent mints the
    `demo_sessions` row, sets the `pf_demo_session` cookie on the client, and
    instantiates that session's private New-queue (Epic 7). Returns the id parsed
    from the cookie.
    """
    response = await assume(client, tenant_slug=SUNSHINE.slug, role=Role.AGENT)
    assert response.status_code == 200
    return uuid.UUID(client.cookies[DEMO_SESSION_COOKIE_NAME])


async def reset_demo_sessions_state(database_engine) -> None:
    """Wipe both tenants' leads + the ledger + `demo_sessions`, then re-seed.

    The clean slate the `All`-scope phase needs for exact-count assertions: the
    never-reset container accumulates `demo_sessions` rows across tests, so an `All`
    sweep would hit strays. Mirrors `_reset_state` in `test_demo_purge_scopes.py`;
    re-seeding restores the shared `NULL` historical baseline the phase asserts
    survives.
    """
    async with database_engine.begin() as connection:
        for schema_name in (SUNSHINE.schema_name, FLORIDA.schema_name):
            await connection.execute(text(f"DELETE FROM {schema_name}.leads"))
        await connection.execute(
            text("DELETE FROM platform.demo_session_tenant_seed")
        )
        await connection.execute(text("DELETE FROM platform.demo_sessions"))
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    async with session_factory() as session:
        await seed(session)


# --- Phase 1: write-tagging proven through the broker (the thin thread) -------


@pytest.mark.asyncio
async def test_created_lead_and_its_event_carry_the_session_id_through_the_broker(
    seeded,
    db_client,
    database_engine,
    container_relay_session_factory,
    broker_channel,
):
    """A created lead, its outbox row, AND the drained AMQP envelope carry the session id.

    The headline end-to-end thread. Assuming a Sunshine Agent mints the demo session
    (cookie set on the client); a following `POST /api/leads` tags the stored lead
    **row** and its single `lead.created` **outbox** row with that `demo_session_id`.
    Then declare the topology and `publish_pending_once`: the relay publishes the row,
    the message arrives on `lead.created` keyed by `message_id`, and its body
    round-trips to an envelope still carrying the same `demo_session_id` on the wire —
    the only proof needing real RabbitMQ (it de-risks the M3 sidecar's session tag).
    """
    minted_id = await mint_session_via_agent(db_client)

    create_response = await db_client.post("/api/leads", json=lead_body())
    assert create_response.status_code == 201
    lead_id = uuid.UUID(create_response.json()["lead"]["id"])

    # The lead row carries the minted demo-session id.
    row = await read_lead_row(database_engine, SUNSHINE.schema_name, lead_id)
    assert row.demo_session_id == minted_id

    # The single `lead.created` outbox row carries it too (and is not yet published).
    created_rows = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.LEAD_CREATED, lead_id
    )
    assert len(created_rows) == 1
    enqueued = created_rows[0]
    assert enqueued.demo_session_id == minted_id
    assert enqueued.published_at is None
    event_id = enqueued.event_id

    # Publish through the relay; the message round-trips to an envelope on the wire
    # that STILL carries the session id (not just the DB row). Purge the drain queue
    # first so the never-reset broker's leftovers do not exhaust the poll budget.
    await declare_topology(broker_channel)
    drain_queue = await broker_channel.get_queue(LEAD_CREATED_DRAIN_QUEUE)
    await drain_queue.purge()
    published_count = await publish_pending_once(broker_channel)
    assert published_count >= 1

    message = await drain_for_event_id(
        broker_channel, LEAD_CREATED_DRAIN_QUEUE, event_id
    )
    assert message is not None, (
        f"event {event_id} never arrived on {LEAD_CREATED_DRAIN_QUEUE}"
    )
    round_tripped = from_message_body(message.body)
    assert round_tripped.event_id == event_id
    assert round_tripped.demo_session_id == minted_id


# --- Phase 2: GET /api/demo/session reports active / expired / none -----------


@pytest.mark.asyncio
async def test_session_state_endpoint_reports_active_expired_and_none(
    seeded, db_client, database_engine
):
    """`GET /api/demo/session` reads `active` (live), `expired` (back-dated), `none`.

    The tri-state seam the masthead countdown consumes, end-to-end. A live session
    minted via assume-persona reads `active` with its id + expiry. Back-dating that
    same row's `expires_at` (superuser) flips the next read to `expired`, still
    naming the id. Dropping the cookie reads a bare `none`.
    """
    minted_id = await mint_session_via_agent(db_client)

    # Active: the live, minted session.
    active = await db_client.get("/api/demo/session")
    assert active.status_code == 200
    active_body = active.json()
    assert active_body["status"] == "active"
    assert active_body["demo_session_id"] == str(minted_id)
    assert "expires_at" in active_body

    # Expired: back-date the same row's window, then read it back.
    await back_date_session_expiry(database_engine, minted_id)
    expired = await db_client.get("/api/demo/session")
    assert expired.status_code == 200
    expired_body = expired.json()
    assert expired_body["status"] == "expired"
    assert expired_body["demo_session_id"] == str(minted_id)

    # None: no cookie at all.
    db_client.cookies.delete(DEMO_SESSION_COOKIE_NAME)
    none = await db_client.get("/api/demo/session")
    assert none.status_code == 200
    assert none.json() == {"status": "none"}


# --- Phase 3: ledger idempotency ---------------------------------------------


@pytest.mark.asyncio
async def test_second_assume_inserts_no_new_session_leads(
    seeded, db_client, database_engine
):
    """A second assume for the same session + tenant instantiates no new queue rows.

    Assuming a Sunshine Agent mints the session and seeds its 4-row private queue.
    A second assume on the same client (a role switch to Read-Only) reuses the same
    `pf_demo_session` cookie — the `demo_session_tenant_seed` ledger marker makes the
    re-instantiation a no-op, so the session's lead count is unchanged across BOTH
    tenant schemas (the ledger guard is the ledger only — a second visit legitimately
    shares the dup-bait email).
    """
    minted_id = await mint_session_via_agent(db_client)

    before = {
        schema_name: await count_session_leads(database_engine, schema_name, minted_id)
        for schema_name in (SUNSHINE.schema_name, FLORIDA.schema_name)
    }
    assert before[SUNSHINE.schema_name] == 4  # the assumed tenant's private queue

    # Re-assume within the same visit (a role switch) — the same cookie is reused.
    second = await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.READ_ONLY)
    assert second.status_code == 200
    assert uuid.UUID(db_client.cookies[DEMO_SESSION_COOKIE_NAME]) == minted_id

    # No new rows in either schema — the ledger absorbed the re-instantiation.
    for schema_name in (SUNSHINE.schema_name, FLORIDA.schema_name):
        after = await count_session_leads(database_engine, schema_name, minted_id)
        assert after == before[schema_name]


# --- Phase 4: read isolation --------------------------------------------------


@pytest.mark.asyncio
async def test_one_sessions_lead_is_invisible_to_another(
    seeded, db_client, database_engine
):
    """Session A's lead is hidden from session B; both see the shared `NULL` baseline.

    Two independent visits (two clients, separate cookie jars): `db_client` is
    session A, a fresh client on the same app + `get_db` override is session B. A
    creates a lead (tagged with A's session id). B — carrying its own cookie — cannot
    reach it: `GET /api/leads/{a_lead_id}` is a `404 "lead not found"` (identical to a
    missing id, so B cannot even probe), and A's lead is absent from B's list and its
    `unassigned` queue. Yet BOTH A and B see the shared `demo_session_id IS NULL`
    historical baseline, proving the hiding is per-session isolation, not a blanket
    blackout.
    """
    # Session A: create a lead, capture its id and A's session id.
    session_a_id = await mint_session_via_agent(db_client)
    a_create = await db_client.post("/api/leads", json=lead_body())
    assert a_create.status_code == 201
    a_lead_id = uuid.UUID(a_create.json()["lead"]["id"])
    a_row = await read_lead_row(database_engine, SUNSHINE.schema_name, a_lead_id)
    assert a_row.demo_session_id == session_a_id

    # A sees its own lead AND the shared baseline.
    a_detail = await db_client.get(f"/api/leads/{a_lead_id}")
    assert a_detail.status_code == 200
    a_list = await db_client.get("/api/leads")
    assert a_list.status_code == 200
    a_list_leads = a_list.json()["leads"]
    assert any(lead["id"] == str(a_lead_id) for lead in a_list_leads)
    assert any(lead.get("is_seed") for lead in a_list_leads), "A sees no shared baseline"

    # Session B: a fresh client (empty cookie jar) on the same app + get_db override.
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as session_b_client:
        session_b_id = await mint_session_via_agent(session_b_client)
        assert session_b_id != session_a_id

        # B cannot read A's lead by id — 404, indistinguishable from a missing id.
        b_detail = await session_b_client.get(f"/api/leads/{a_lead_id}")
        assert b_detail.status_code == 404
        assert b_detail.json() == {"detail": "lead not found"}

        # A's lead is absent from B's list and its unassigned queue.
        b_list = await session_b_client.get("/api/leads")
        assert b_list.status_code == 200
        b_list_leads = b_list.json()["leads"]
        assert all(lead["id"] != str(a_lead_id) for lead in b_list_leads)

        b_queue = await session_b_client.get(
            "/api/leads", params={"unassigned": "true"}
        )
        assert b_queue.status_code == 200
        assert all(
            lead["id"] != str(a_lead_id) for lead in b_queue.json()["leads"]
        )

        # But B DOES see the shared `NULL` baseline — isolation, not a blackout.
        assert any(
            lead.get("is_seed") for lead in b_list_leads
        ), "B sees no shared baseline"


# --- Phase 5: purge scopes across BOTH tenant schemas -------------------------


@pytest.mark.asyncio
async def test_session_reset_purges_only_the_callers_overlay_keeping_the_baseline(
    seeded,
    db_client,
    database_engine,
    container_keys_session_factory,
    container_purge_session_factory,
):
    """`POST /api/demo/session/reset` (the `Session` scope) deletes only the caller's overlay.

    The visitor's self-service reset over HTTP. Assume a Sunshine Agent (minting the
    session + its private queue), then role-switch to Platform Admin (reusing the same
    session + cookie; the admin passes no tenant slug so the cookie is untouched) and
    call the reset. The caller's session-tagged leads are gone across BOTH tenant
    schemas, but the `demo_sessions` row survives (the visit continues) and the shared
    `NULL` baseline is untouched.
    """
    minted_id = await mint_session_via_agent(db_client)
    baseline = {
        schema_name: await count_seed_baseline_leads(database_engine, schema_name)
        for schema_name in (SUNSHINE.schema_name, FLORIDA.schema_name)
    }
    assert all(count > 0 for count in baseline.values())
    assert (
        await count_session_leads(database_engine, SUNSHINE.schema_name, minted_id) > 0
    )

    # Role-switch to Platform Admin (reuses the same demo session + cookie).
    admin = await assume(
        db_client, tenant_slug=SUNSHINE.slug, role=Role.PLATFORM_ADMIN
    )
    assert admin.status_code == 200
    assert uuid.UUID(db_client.cookies[DEMO_SESSION_COOKIE_NAME]) == minted_id

    reset = await db_client.post("/api/demo/session/reset")
    assert reset.status_code == 200

    # The caller's overlay is gone in both schemas; the session row survives.
    for schema_name in (SUNSHINE.schema_name, FLORIDA.schema_name):
        assert await count_session_leads(database_engine, schema_name, minted_id) == 0
    assert await demo_session_row_exists(database_engine, minted_id) is True

    # The shared `NULL` baseline is untouched in both schemas.
    for schema_name in (SUNSHINE.schema_name, FLORIDA.schema_name):
        assert (
            await count_seed_baseline_leads(database_engine, schema_name)
            == baseline[schema_name]
        )


@pytest.mark.asyncio
async def test_expired_scope_purges_only_expired_sessions_keeping_live_and_baseline(
    seeded,
    database_engine,
    container_keys_session_factory,
    container_purge_session_factory,
):
    """`purge_sessions(Expired, delete_session_row=True)` clears only expired footprints.

    Mint two sessions whose private queues are instantiated in both tenants, then
    back-date one's `expires_at`. The direct `Expired` purge (no operator HTTP
    trigger beyond the CLI) removes the expired session's leads + `demo_sessions` row
    across BOTH schemas while the live session and the shared `NULL` baseline survive.
    Assertions key on this run's own ids, so accumulated strays from earlier tests do
    not perturb the per-session checks.
    """
    expired_id = uuid.uuid4()
    live_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    # The `demo_sessions` rows are committed BEFORE instantiating the overlay:
    # `ensure_session_leads` rolls back any prior read transaction when it scopes to
    # the tenant role, so an uncommitted row insert would be lost (the
    # `_mint_demo_session` then `_seed_session_overlay` order in `test_demo_purge_scopes.py`).
    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO platform.demo_sessions (id, expires_at) VALUES "
                "(:expired_id, :past), (:live_id, :future)"
            ),
            {
                "expired_id": expired_id,
                "past": now - timedelta(hours=1),
                "live_id": live_id,
                "future": now + timedelta(days=1),
            },
        )
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    async with session_factory() as session:
        for tenant in (SUNSHINE, FLORIDA):
            await ensure_session_leads(session, tenant, expired_id)
            await ensure_session_leads(session, tenant, live_id)
        await session.commit()

    baseline = {
        schema_name: await count_seed_baseline_leads(database_engine, schema_name)
        for schema_name in (SUNSHINE.schema_name, FLORIDA.schema_name)
    }

    counts = await purge_sessions(Expired(), delete_session_row=True)

    # The run swept the expired session (among any strays); the live id was never in scope.
    assert expired_id in counts.session_ids
    assert live_id not in counts.session_ids

    # The expired session's whole footprint is gone in both schemas; the live one survives.
    assert await demo_session_row_exists(database_engine, expired_id) is False
    assert await demo_session_row_exists(database_engine, live_id) is True
    for schema_name in (SUNSHINE.schema_name, FLORIDA.schema_name):
        assert await count_session_leads(database_engine, schema_name, expired_id) == 0
        assert await count_session_leads(database_engine, schema_name, live_id) == 4
        assert (
            await count_seed_baseline_leads(database_engine, schema_name)
            == baseline[schema_name]
        )


@pytest.mark.asyncio
async def test_all_scope_clears_every_session_overlay_keeping_the_baseline(
    seeded,
    database_engine,
    container_keys_session_factory,
    container_purge_session_factory,
):
    """`purge_sessions(All, delete_session_row=True)` wipes every session, baseline intact.

    The `All` scope needs a clean `demo_sessions` slate for its exact counts, so this
    phase wipes both tenants' leads + the ledger + the `demo_sessions` table and
    re-seeds (restoring the `NULL` baseline) before minting its own two sessions in
    both tenants. The `All` purge then removes every session overlay + row across BOTH
    schemas — 2 sessions x 2 tenants x 4 leads = 16 leads, 4 ledger rows, 2 session
    rows — leaving the shared baseline untouched.
    """
    await reset_demo_sessions_state(database_engine)
    session_one = uuid.uuid4()
    session_two = uuid.uuid4()
    now = datetime.now(timezone.utc)
    # Commit the `demo_sessions` rows first — `ensure_session_leads` rolls back any
    # prior read transaction when it scopes to the tenant role, so an uncommitted row
    # insert would be lost (the `_mint_demo_session` then `_seed_session_overlay` order
    # in `test_demo_purge_scopes.py`).
    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO platform.demo_sessions (id, expires_at) VALUES "
                "(:session_one, :expires_at), (:session_two, :expires_at)"
            ),
            {
                "session_one": session_one,
                "session_two": session_two,
                "expires_at": now + timedelta(days=1),
            },
        )
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    async with session_factory() as session:
        for session_id in (session_one, session_two):
            for tenant in (SUNSHINE, FLORIDA):
                await ensure_session_leads(session, tenant, session_id)
        await session.commit()

    baseline = {
        schema_name: await count_seed_baseline_leads(database_engine, schema_name)
        for schema_name in (SUNSHINE.schema_name, FLORIDA.schema_name)
    }
    assert all(count > 0 for count in baseline.values())

    counts = await purge_sessions(All(), delete_session_row=True)

    assert set(counts.session_ids) == {session_one, session_two}
    assert counts.total_leads_deleted == 16  # 2 sessions x 2 tenants x 4 leads
    assert counts.ledger_deleted == 4
    assert counts.session_rows_deleted == 2

    # Every session overlay + row is gone in both schemas; the baseline survives.
    for session_id in (session_one, session_two):
        assert await demo_session_row_exists(database_engine, session_id) is False
        for schema_name in (SUNSHINE.schema_name, FLORIDA.schema_name):
            assert (
                await count_session_leads(database_engine, schema_name, session_id) == 0
            )
    for schema_name in (SUNSHINE.schema_name, FLORIDA.schema_name):
        assert (
            await count_seed_baseline_leads(database_engine, schema_name)
            == baseline[schema_name]
        )
