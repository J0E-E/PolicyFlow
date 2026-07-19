"""DB proof of the overlay-aware policy read — `GET /api/opportunities/{id}/policy`.

The thin read the opportunity-detail page uses to show an issued policy's status
(P2.4 Epic 6). Drives the real DB-backed client (the `seeded` + `db_client`
substrate), reading the **sole** seeded Sunshine `medicare_advantage` baseline
policy through its originating (conversion) opportunity.

Three cases pin the derive-at-read *Renewal Due* overlay (ADR 0005):

- a baseline policy with **no** renewal opportunity in the caller's session reads
  `Active`;
- after an AEP sweep in the caller's session, the same baseline policy reads
  `Renewal Due` — via the overlay, with no stored status change;
- a **session-owned** policy already carrying the real `Renewal Due` status reads it
  straight through, without the overlay.

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no decorator.
The `seeded`/`db_client` fixtures + `assume` helper come from the shared suites.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.demo.session import DEMO_SESSION_COOKIE_NAME
from app.models.opportunity import Opportunity
from app.models.policy import Policy
from app.models.user import Role
from app.tenancy.registry import SUNSHINE

from .test_demo_assume_persona import assume
from .test_endpoints_db import seeded  # noqa: F401 — used by name


# Both `cleanup_committed_renewals` and `cleanup_committed_cross_sell` now live in
# conftest.py (shared across the sweep / cross-sell suites) and resolve here by name.


async def _seeded_ma_opportunity_id(db_session) -> uuid.UUID:
    """Return the originating opportunity id of the sole baseline Sunshine MA policy."""
    return (
        await db_session.execute(
            text(
                f"SELECT o.id FROM {SUNSHINE.schema_name}.opportunities o "
                f"JOIN {SUNSHINE.schema_name}.policies p "
                "ON p.opportunity_id = o.id "
                "WHERE o.product_line = 'medicare_advantage' "
                "AND o.demo_session_id IS NULL"
            )
        )
    ).scalar_one()


async def _seeded_ma_policy_id(db_session) -> uuid.UUID:
    """Return the id of the sole baseline Sunshine MA policy (the overlay's target)."""
    return (
        await db_session.execute(
            text(
                f"SELECT p.id FROM {SUNSHINE.schema_name}.policies p "
                f"JOIN {SUNSHINE.schema_name}.opportunities o "
                "ON p.opportunity_id = o.id "
                "WHERE o.product_line = 'medicare_advantage' "
                "AND o.demo_session_id IS NULL"
            )
        )
    ).scalar_one()


async def _insert_cross_sell_opportunity(
    database_engine, demo_session_id: uuid.UUID, source_policy_id: uuid.UUID
) -> None:
    """Commit an `origin='cross_sell'` opportunity in `demo_session_id` for the baseline.

    Cross-sell (Epic 13) sets `source_policy_id` just like a renewal does, so this pins
    that the overlay's `origin='renewal'` qualifier is load-bearing. Carries a NULL
    `source_lead_id` (nullable post-0020) → needs the `cleanup_committed_cross_sell`
    teardown so it doesn't break the migration round-trip.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    async with session_factory() as session:
        await session.execute(text(f"SET search_path TO {SUNSHINE.schema_name}"))
        session.add(
            Opportunity(
                contact_id=uuid.uuid4(),
                household_id=uuid.uuid4(),
                product_line="dental_vision_hearing",
                stage="New",
                origin="cross_sell",
                owner_user_id=uuid.uuid4(),
                owner_username="agent.one",
                source_lead_id=None,
                source_policy_id=source_policy_id,
                correlation_id=uuid.uuid4(),
                demo_session_id=demo_session_id,
            )
        )
        await session.commit()


async def _insert_renewal_opportunity(
    database_engine, demo_session_id: uuid.UUID, source_policy_id: uuid.UUID
) -> None:
    """Commit an `origin='renewal'` opportunity in `demo_session_id` for the baseline.

    Used to prove cross-session isolation — a renewal committed under *another* session
    must not lift the baseline for the caller. NULL `source_lead_id` (nullable post-0020)
    → cleaned by `cleanup_committed_renewals`.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    async with session_factory() as session:
        await session.execute(text(f"SET search_path TO {SUNSHINE.schema_name}"))
        session.add(
            Opportunity(
                contact_id=uuid.uuid4(),
                household_id=uuid.uuid4(),
                product_line="medicare_advantage",
                stage="New",
                origin="renewal",
                owner_user_id=uuid.uuid4(),
                owner_username="agent.one",
                source_lead_id=None,
                source_policy_id=source_policy_id,
                renewal_cycle="aep-2026",
                correlation_id=uuid.uuid4(),
                demo_session_id=demo_session_id,
            )
        )
        await session.commit()


async def _insert_session_owned_renewal_due_policy(
    database_engine, demo_session_id: uuid.UUID
) -> uuid.UUID:
    """Commit a session-owned opportunity + a `Renewal Due` policy; return the opp id.

    Inserts into the Sunshine schema via a committed session so the request's
    `get_tenant_db` sees it. The policy carries the **real** `Renewal Due` status and
    is tagged with `demo_session_id`, so the read must surface it straight through
    (never via the baseline overlay).
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    async with session_factory() as session:
        await session.execute(text(f"SET search_path TO {SUNSHINE.schema_name}"))
        opportunity = Opportunity(
            contact_id=uuid.uuid4(),
            household_id=uuid.uuid4(),
            product_line="medicare_advantage",
            stage="Policy Active",
            origin="conversion",
            owner_user_id=uuid.uuid4(),
            owner_username="agent.one",
            source_lead_id=uuid.uuid4(),
            correlation_id=uuid.uuid4(),
            demo_session_id=demo_session_id,
        )
        session.add(opportunity)
        await session.flush()
        session.add(
            Policy(
                opportunity_id=opportunity.id,
                application_id=uuid.uuid4(),
                contact_id=opportunity.contact_id,
                policy_number="MA-SESSIONOWNED",
                carrier="Humana",
                product_label="Gold Plus HMO",
                coverage_amount=7500,
                premium_monthly=29,
                premium_annual=348,
                status="Renewal Due",
                correlation_id=uuid.uuid4(),
                demo_session_id=demo_session_id,
                issued_at=datetime(2022, 3, 1, tzinfo=timezone.utc),
            )
        )
        await session.commit()
        return opportunity.id


async def test_baseline_policy_without_a_renewal_reads_active(
    seeded,  # noqa: F811 — fixture param, not a redefinition
    db_client,
    db_session,
    container_keys_session_factory,
):
    """With no renewal opportunity in the caller's session, the policy reads Active."""
    assert (
        await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT)
    ).status_code == 200
    opportunity_id = await _seeded_ma_opportunity_id(db_session)

    response = await db_client.get(f"/api/opportunities/{opportunity_id}/policy")

    assert response.status_code == 200
    assert response.json()["policy"]["status"] == "Active"


async def test_baseline_policy_reads_renewal_due_after_a_sweep(
    seeded,  # noqa: F811 — fixture param, not a redefinition
    db_client,
    db_session,
    container_keys_session_factory,
    cleanup_committed_renewals,
):
    """After an AEP sweep in the caller's session, the baseline policy reads Renewal Due.

    Agent → Platform Admin (runs the sweep in the shared demo session) → Agent again,
    all one demo session — so the reader's session holds the renewal opportunity the
    overlay keys on.
    """
    assert (
        await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT)
    ).status_code == 200
    assert (
        await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.PLATFORM_ADMIN)
    ).status_code == 200
    sweep = await db_client.post("/api/renewals/aep-sweep")
    assert sweep.json() == {"generated": 1, "skipped": 0}

    # Back to a tenant user in the same demo session to read the policy.
    assert (
        await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT)
    ).status_code == 200
    opportunity_id = await _seeded_ma_opportunity_id(db_session)

    response = await db_client.get(f"/api/opportunities/{opportunity_id}/policy")

    assert response.status_code == 200
    assert response.json()["policy"]["status"] == "Renewal Due"


async def test_cross_sell_opportunity_does_not_trigger_the_overlay(
    seeded,  # noqa: F811 — fixture param, not a redefinition
    db_client,
    db_session,
    database_engine,
    container_keys_session_factory,
    cleanup_committed_cross_sell,
):
    """A `cross_sell` opportunity on the baseline policy leaves it reading Active.

    Cross-sell (Epic 13) sets `source_policy_id` exactly like a renewal, but the overlay
    predicate keys on `origin='renewal'`. With only a cross-sell opportunity in the
    caller's session pointing at the baseline policy, that policy must STILL read Active
    — proving the `origin='renewal'` qualifier is load-bearing (never a false positive
    from a cross-sell origin).
    """
    assert (
        await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT)
    ).status_code == 200
    demo_session_id = uuid.UUID(db_client.cookies[DEMO_SESSION_COOKIE_NAME])
    policy_id = await _seeded_ma_policy_id(db_session)
    await _insert_cross_sell_opportunity(database_engine, demo_session_id, policy_id)
    opportunity_id = await _seeded_ma_opportunity_id(db_session)

    response = await db_client.get(f"/api/opportunities/{opportunity_id}/policy")

    assert response.status_code == 200
    assert response.json()["policy"]["status"] == "Active"


async def test_renewal_in_another_session_does_not_leak_to_the_caller(
    seeded,  # noqa: F811 — fixture param, not a redefinition
    db_client,
    db_session,
    database_engine,
    container_keys_session_factory,
    cleanup_committed_renewals,
):
    """A renewal in a DIFFERENT demo session leaves the caller reading Active.

    The overlay is session-scoped: it lifts a baseline policy only when the *reader's*
    session holds the `origin='renewal'` opportunity. A renewal committed under another
    session must not bleed across — the caller still reads Active.
    """
    assert (
        await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT)
    ).status_code == 200
    caller_session_id = uuid.UUID(db_client.cookies[DEMO_SESSION_COOKIE_NAME])
    policy_id = await _seeded_ma_policy_id(db_session)
    other_session_id = uuid.uuid4()
    assert other_session_id != caller_session_id
    await _insert_renewal_opportunity(database_engine, other_session_id, policy_id)
    opportunity_id = await _seeded_ma_opportunity_id(db_session)

    response = await db_client.get(f"/api/opportunities/{opportunity_id}/policy")

    assert response.status_code == 200
    assert response.json()["policy"]["status"] == "Active"


async def test_session_owned_policy_reads_its_stored_renewal_due_status(
    seeded,  # noqa: F811 — fixture param, not a redefinition
    db_client,
    database_engine,
    container_keys_session_factory,
):
    """A session-owned policy stored as Renewal Due reads it straight through."""
    assert (
        await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT)
    ).status_code == 200
    demo_session_id = uuid.UUID(db_client.cookies[DEMO_SESSION_COOKIE_NAME])
    opportunity_id = await _insert_session_owned_renewal_due_policy(
        database_engine, demo_session_id
    )

    response = await db_client.get(f"/api/opportunities/{opportunity_id}/policy")

    assert response.status_code == 200
    assert response.json()["policy"]["status"] == "Renewal Due"
