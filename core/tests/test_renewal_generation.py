"""DB tests for the renewal generation core (`app.renewals.service`, P2.4 Epic 4).

`generate_renewals` is the service each sweep endpoint (Epic 6/8) will call: it
selects the session-visible active policies on a rule's product lines, skips any
already renewed this cycle, and for the rest writes a Renewal Opportunity + a
renewal-review Task + two outbox events, flipping session-owned policies to
*Renewal Due*. These prove that behavior directly against the real migrated
Postgres — no endpoint exists yet.

**Fixture, not the app seed (TDD §5.4 / the epic plan).** Each test inserts just the
two rows the service reads — an originating `Opportunity` and its `Policy` — since
the service copies the renewal's owner / contact / household forward from the
opportunity and never touches a Contact or Household row. Everything runs inside one
**uncommitted** scoped session: the service does not commit, its flushed rows are
visible to reads in the same transaction, and letting the session close without a
commit rolls it all back — so tests never leak rows into the shared container
database (baseline `NULL`-session policies would otherwise be visible to every other
test's sweep).

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no decorator.
"""

import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.opportunity import Opportunity
from app.models.outbox_event import OutboxEvent
from app.models.policy import Policy
from app.models.task import Task
from app.renewals.service import generate_renewals
from app.tenancy.registry import SUNSHINE

# A fixed "today" so the AEP cycle year (and its Dec 7 deadline) and every
# anniversary window are deterministic regardless of when the suite runs.
_TODAY = date(2026, 7, 18)


@asynccontextmanager
async def _scoped_session(database_engine, schema_name):
    """Yield a session with `search_path` set to `schema_name`, rolled back on exit.

    The `database_engine` connects as the container superuser, so setting the
    search path is enough for the service's schema-less ORM models to resolve into
    the tenant schema (the app does the same with `SET LOCAL search_path`). Nothing
    is committed, so the whole transaction — the clear below, the fixture rows, and
    the service's writes — rolls back when the block ends, isolating each test on the
    shared substrate.

    Inside the transaction it first clears the schema's `opportunities`, `policies`,
    and `tasks` so each test controls exactly which policies the sweep can see. The
    boot seed (run by other tests on this session-scoped container) commits baseline
    money-path policies (P2.4 Epic 5) with `demo_session_id IS NULL`, and those are
    visible to *every* session's sweep — so without this clear a seeded baseline
    policy would be renewed alongside a test's own fixtures and inflate the counts.
    The deletes are part of this uncommitted transaction, so they roll back on exit
    and never remove the committed baseline rows other tests rely on.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    async with session_factory() as session:
        await session.execute(text(f"SET search_path TO {schema_name}"))
        await session.execute(text("DELETE FROM tasks"))
        await session.execute(text("DELETE FROM policies"))
        await session.execute(text("DELETE FROM opportunities"))
        try:
            yield session
        finally:
            await session.rollback()


async def _insert_policy_chain(
    db,
    *,
    product_line,
    demo_session_id,
    issued_at,
    status="Active",
    policy_number,
    owner_username="agent-ana",
):
    """Insert an originating opportunity + its issued policy; return `(opp, policy)`.

    Mirrors what the money path leaves behind: a `conversion` opportunity carrying
    the owner / contact / household, and a `Policy` linked to it via
    `opportunity_id`. Only the fields the service reads or copies are meaningful; the
    rest are valid filler.
    """
    owner_user_id = uuid.uuid4()
    contact_id = uuid.uuid4()
    household_id = uuid.uuid4()
    origin_opportunity = Opportunity(
        contact_id=contact_id,
        household_id=household_id,
        product_line=product_line,
        stage="Policy Active",
        origin="conversion",
        owner_user_id=owner_user_id,
        owner_username=owner_username,
        source_lead_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        demo_session_id=demo_session_id,
    )
    db.add(origin_opportunity)
    await db.flush()
    policy = Policy(
        opportunity_id=origin_opportunity.id,
        application_id=uuid.uuid4(),
        contact_id=contact_id,
        policy_number=policy_number,
        carrier="Humana",
        product_label="Gold Plus HMO",
        coverage_amount=7500,
        premium_monthly=29,
        premium_annual=348,
        status=status,
        correlation_id=uuid.uuid4(),
        demo_session_id=demo_session_id,
        issued_at=issued_at,
    )
    db.add(policy)
    await db.flush()
    return origin_opportunity, policy


async def _renewal_opportunities(db, demo_session_id):
    """Return the session's renewal opportunities, oldest first."""
    return (
        (
            await db.execute(
                select(Opportunity)
                .where(
                    Opportunity.origin == "renewal",
                    Opportunity.demo_session_id == demo_session_id,
                )
                .order_by(Opportunity.created_at, Opportunity.id)
            )
        )
        .scalars()
        .all()
    )


async def _renewal_tasks(db, demo_session_id):
    """Return the session's renewal-review tasks."""
    return (
        (
            await db.execute(
                select(Task).where(
                    Task.task_type == "renewal_review",
                    Task.demo_session_id == demo_session_id,
                )
            )
        )
        .scalars()
        .all()
    )


async def _outbox_events(db, demo_session_id):
    """Return the session's outbox rows, oldest first."""
    return (
        (
            await db.execute(
                select(OutboxEvent)
                .where(OutboxEvent.demo_session_id == demo_session_id)
                .order_by(OutboxEvent.occurred_at, OutboxEvent.id)
            )
        )
        .scalars()
        .all()
    )


# --- Phase 2: AEP sweep (happy path) -----------------------------------------


async def test_aep_sweep_renews_a_session_visible_active_policy(database_engine):
    """An active Medicare Advantage policy yields one full renewal chain."""
    async with _scoped_session(database_engine, SUNSHINE.schema_name) as db:
        session_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        origin_opportunity, policy = await _insert_policy_chain(
            db,
            product_line="medicare_advantage",
            demo_session_id=None,  # baseline: visible to every session
            issued_at=datetime(2022, 3, 1, tzinfo=timezone.utc),
            policy_number="MA-1001",
        )

        result = await generate_renewals(
            db,
            SUNSHINE,
            tenant_id=tenant_id,
            rule="aep",
            demo_session_id=session_id,
            today=_TODAY,
        )
        assert result == {"generated": 1, "skipped": 0}

        # One renewal opportunity, owner/line copied from the originating one.
        renewals = await _renewal_opportunities(db, session_id)
        assert len(renewals) == 1
        renewal = renewals[0]
        assert renewal.origin == "renewal"
        assert renewal.stage == "New"
        assert renewal.product_line == "medicare_advantage"
        assert renewal.owner_user_id == origin_opportunity.owner_user_id
        assert renewal.owner_username == origin_opportunity.owner_username
        assert renewal.source_policy_id == policy.id
        assert renewal.source_lead_id is None
        assert renewal.renewal_cycle == "aep-2026"
        assert renewal.target_close_date == date(2026, 12, 7)
        assert renewal.demo_session_id == session_id

        # One renewal-review task, assigned to the owning agent, due on the deadline.
        tasks = await _renewal_tasks(db, session_id)
        assert len(tasks) == 1
        task = tasks[0]
        assert task.related_entity_type == "opportunity"
        assert task.related_entity_id == renewal.id
        assert task.assignee_user_id == origin_opportunity.owner_user_id
        assert task.status == "open"
        assert "MA-1001" in task.body and "Medicare Advantage" in task.body
        assert task.due_date == datetime(2026, 12, 7, tzinfo=timezone.utc)
        assert task.correlation_id == renewal.correlation_id

        # Both events, one shared new correlation, system actor, causation None.
        events = await _outbox_events(db, session_id)
        by_type = {event.event_type: event for event in events}
        assert set(by_type) == {"opportunity.created", "policy.renewal_due"}
        opportunity_created = by_type["opportunity.created"]
        renewal_due = by_type["policy.renewal_due"]
        assert opportunity_created.correlation_id == renewal.correlation_id
        assert renewal_due.correlation_id == renewal.correlation_id
        for event in (opportunity_created, renewal_due):
            assert event.causation_id is None
            assert event.actor_user_id is None
            assert event.actor_role is None
        assert opportunity_created.payload == {
            "entity_id": str(renewal.id),
            "contact_id": str(origin_opportunity.contact_id),
            "household_id": str(origin_opportunity.household_id),
            "origin": "renewal",
            "source_policy_id": str(policy.id),
        }
        assert renewal_due.payload == {
            "entity_id": str(policy.id),
            "opportunity_id": str(renewal.id),
            "contact_id": str(origin_opportunity.contact_id),
            "household_id": str(origin_opportunity.household_id),
            "renewal_kind": "aep",
            "due_date": "2026-12-07",
        }


async def test_aep_re_run_is_idempotent(database_engine):
    """A second sweep of the same cycle generates nothing and reports it skipped."""
    async with _scoped_session(database_engine, SUNSHINE.schema_name) as db:
        session_id = uuid.uuid4()
        await _insert_policy_chain(
            db,
            product_line="medicare_advantage",
            demo_session_id=None,
            issued_at=datetime(2022, 3, 1, tzinfo=timezone.utc),
            policy_number="MA-1002",
        )

        first = await generate_renewals(
            db, SUNSHINE, tenant_id=uuid.uuid4(), rule="aep",
            demo_session_id=session_id, today=_TODAY,
        )
        second = await generate_renewals(
            db, SUNSHINE, tenant_id=uuid.uuid4(), rule="aep",
            demo_session_id=session_id, today=_TODAY,
        )

        assert first == {"generated": 1, "skipped": 0}
        assert second == {"generated": 0, "skipped": 1}
        # Only one renewal opportunity ever exists for the policy + cycle.
        assert len(await _renewal_opportunities(db, session_id)) == 1


async def test_aep_sweep_ignores_policies_on_other_rule_lines(database_engine):
    """The AEP sweep never selects anniversary-line or no-renewal-line policies."""
    async with _scoped_session(database_engine, SUNSHINE.schema_name) as db:
        session_id = uuid.uuid4()
        await _insert_policy_chain(
            db,
            product_line="medicare_supplement",  # anniversary rule
            demo_session_id=None,
            issued_at=datetime(2022, 3, 1, tzinfo=timezone.utc),
            policy_number="MS-1",
        )
        await _insert_policy_chain(
            db,
            product_line="final_expense",  # none rule
            demo_session_id=None,
            issued_at=datetime(2022, 3, 1, tzinfo=timezone.utc),
            policy_number="FE-1",
        )

        result = await generate_renewals(
            db, SUNSHINE, tenant_id=uuid.uuid4(), rule="aep",
            demo_session_id=session_id, today=_TODAY,
        )
        assert result == {"generated": 0, "skipped": 0}
        assert await _renewal_opportunities(db, session_id) == []


async def test_sweep_ignores_a_policy_owned_by_another_session(database_engine):
    """A policy owned by a different demo session is invisible to this sweep.

    The one boundary the inlined session-visibility clause exists to hold: the
    baseline (NULL) plus the caller's own rows are visible, but another visitor's
    private policy is never selected.
    """
    async with _scoped_session(database_engine, SUNSHINE.schema_name) as db:
        session_id = uuid.uuid4()
        other_session_id = uuid.uuid4()
        await _insert_policy_chain(
            db,
            product_line="medicare_advantage",
            demo_session_id=other_session_id,  # owned by a different session
            issued_at=datetime(2022, 3, 1, tzinfo=timezone.utc),
            policy_number="MA-OTHER",
        )

        result = await generate_renewals(
            db, SUNSHINE, tenant_id=uuid.uuid4(), rule="aep",
            demo_session_id=session_id, today=_TODAY,
        )
        assert result == {"generated": 0, "skipped": 0}
        assert await _renewal_opportunities(db, session_id) == []


async def test_aep_sweep_skips_a_non_active_policy(database_engine):
    """A policy that is neither Active nor Renewal Due is not a renewal candidate."""
    async with _scoped_session(database_engine, SUNSHINE.schema_name) as db:
        session_id = uuid.uuid4()
        await _insert_policy_chain(
            db,
            product_line="medicare_advantage",
            demo_session_id=None,
            issued_at=datetime(2022, 3, 1, tzinfo=timezone.utc),
            status="Lapsed",
            policy_number="MA-DEAD",
        )

        result = await generate_renewals(
            db, SUNSHINE, tenant_id=uuid.uuid4(), rule="aep",
            demo_session_id=session_id, today=_TODAY,
        )
        assert result == {"generated": 0, "skipped": 0}


# --- Phase 3: anniversary window + no-renewal & status-write cases ------------


async def test_anniversary_sweep_renews_a_policy_inside_the_window(database_engine):
    """An anniversary-line policy whose anniversary is within 60 days renews."""
    async with _scoped_session(database_engine, SUNSHINE.schema_name) as db:
        session_id = uuid.uuid4()
        # Issued Aug 17 → next anniversary 2026-08-17, 30 days after _TODAY.
        _, policy = await _insert_policy_chain(
            db,
            product_line="medicare_supplement",
            demo_session_id=None,
            issued_at=datetime(2020, 8, 17, tzinfo=timezone.utc),
            policy_number="MS-INWINDOW",
        )

        result = await generate_renewals(
            db, SUNSHINE, tenant_id=uuid.uuid4(), rule="anniversary",
            demo_session_id=session_id, today=_TODAY,
        )
        assert result == {"generated": 1, "skipped": 0}

        renewals = await _renewal_opportunities(db, session_id)
        assert len(renewals) == 1
        renewal = renewals[0]
        assert renewal.renewal_cycle == "anniv-2026"
        assert renewal.target_close_date == date(2026, 8, 17)
        assert renewal.source_policy_id == policy.id

        events = await _outbox_events(db, session_id)
        renewal_due = next(e for e in events if e.event_type == "policy.renewal_due")
        assert renewal_due.payload["renewal_kind"] == "anniversary"
        assert renewal_due.payload["due_date"] == "2026-08-17"


async def test_anniversary_sweep_skips_a_policy_outside_the_window(database_engine):
    """An anniversary more than 60 days out is not selected."""
    async with _scoped_session(database_engine, SUNSHINE.schema_name) as db:
        session_id = uuid.uuid4()
        # Issued Nov 5 → next anniversary 2026-11-05, ~110 days after _TODAY.
        await _insert_policy_chain(
            db,
            product_line="medicare_supplement",
            demo_session_id=None,
            issued_at=datetime(2019, 11, 5, tzinfo=timezone.utc),
            policy_number="MS-OUTWINDOW",
        )

        result = await generate_renewals(
            db, SUNSHINE, tenant_id=uuid.uuid4(), rule="anniversary",
            demo_session_id=session_id, today=_TODAY,
        )
        assert result == {"generated": 0, "skipped": 0}
        assert await _renewal_opportunities(db, session_id) == []


async def test_no_renewal_line_policy_is_never_renewed(database_engine):
    """A `none`-rule (life-style) policy is renewed by neither sweep."""
    async with _scoped_session(database_engine, SUNSHINE.schema_name) as db:
        session_id = uuid.uuid4()
        await _insert_policy_chain(
            db,
            product_line="final_expense",
            demo_session_id=None,
            issued_at=datetime(2022, 7, 18, tzinfo=timezone.utc),  # anniversary today
            policy_number="FE-NEVER",
        )

        aep = await generate_renewals(
            db, SUNSHINE, tenant_id=uuid.uuid4(), rule="aep",
            demo_session_id=session_id, today=_TODAY,
        )
        anniversary = await generate_renewals(
            db, SUNSHINE, tenant_id=uuid.uuid4(), rule="anniversary",
            demo_session_id=session_id, today=_TODAY,
        )
        assert aep == {"generated": 0, "skipped": 0}
        assert anniversary == {"generated": 0, "skipped": 0}


async def test_session_owned_policy_flips_status_while_baseline_stays_active(
    database_engine,
):
    """A session-owned policy takes the real Renewal Due write; a baseline does not."""
    async with _scoped_session(database_engine, SUNSHINE.schema_name) as db:
        session_id = uuid.uuid4()
        _, baseline_policy = await _insert_policy_chain(
            db,
            product_line="medicare_advantage",
            demo_session_id=None,  # baseline — overlay handles its status
            issued_at=datetime(2022, 3, 1, tzinfo=timezone.utc),
            policy_number="MA-BASELINE",
        )
        _, session_policy = await _insert_policy_chain(
            db,
            product_line="medicare_advantage",
            demo_session_id=session_id,  # session-owned — real write
            issued_at=datetime(2022, 3, 1, tzinfo=timezone.utc),
            policy_number="MA-SESSION",
        )

        result = await generate_renewals(
            db, SUNSHINE, tenant_id=uuid.uuid4(), rule="aep",
            demo_session_id=session_id, today=_TODAY,
        )
        assert result == {"generated": 2, "skipped": 0}

        # Read the status straight from the database (not the identity-mapped
        # objects the service mutated in memory), so a missing flush would surface
        # as a stale row rather than passing on an in-memory value.
        statuses = dict(
            (
                await db.execute(
                    text(
                        "SELECT id, status FROM policies WHERE id IN "
                        "(:baseline_id, :session_id)"
                    ),
                    {
                        "baseline_id": baseline_policy.id,
                        "session_id": session_policy.id,
                    },
                )
            ).all()
        )
        assert statuses[baseline_policy.id] == "Active"
        assert statuses[session_policy.id] == "Renewal Due"
