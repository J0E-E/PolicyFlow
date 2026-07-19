"""DB-backed proof of the household detail read — `GET /api/households/{id}` (P2.4 Epic 13).

The read backing the household detail page: one household's contacts, its **active**
policies (overlay-aware), and a live cross-sell coverage check (one suggestion per
uncovered tenant product line, ADR 0002). Driven against the real seeded baseline
households (Epic 5): Sunshine's **Ramirez** household covers three of four lines
(partial → a `dental_vision_hearing` prompt); Florida's **Familia** household covers
all four (full → no prompt).

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no decorator.
"""

import uuid

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.user import Role
from app.tenancy.registry import FLORIDA, SUNSHINE

from .test_demo_assume_persona import assume
from .test_endpoints_db import seeded  # noqa: F401 — used by name
from .test_household_search import convert_one_lead


@pytest_asyncio.fixture
async def cleanup_foreign_session_households(database_engine):
    """Delete every foreign-session household a test committed (both schemas).

    The foreign-session `404` test must commit a session-tagged household so the
    request's own connection can read it (then be scoped out). Households carry no
    `source_lead_id`, so they don't threaten the 0020 round-trip — but the row still
    leaks into the shared container, so this clears it by its unique marker name.
    """
    yield
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    async with session_factory() as session:
        for tenant in (SUNSHINE, FLORIDA):
            await session.execute(
                text(
                    f"DELETE FROM {tenant.schema_name}.households "
                    "WHERE name = 'Foreign Session Household'"
                )
            )
        await session.commit()


async def _insert_foreign_session_household(database_engine, tenant) -> uuid.UUID:
    """Commit a household tagged with a *different* demo session; return its id."""
    household_id = uuid.uuid4()
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    async with session_factory() as session:
        await session.execute(text(f"SET search_path TO {tenant.schema_name}"))
        await session.execute(
            text(
                "INSERT INTO households (id, name, correlation_id, demo_session_id) "
                "VALUES (:id, :name, :correlation_id, :demo_session_id)"
            ),
            {
                "id": household_id,
                "name": "Foreign Session Household",
                "correlation_id": uuid.uuid4(),
                "demo_session_id": uuid.uuid4(),
            },
        )
        await session.commit()
    return household_id


async def _baseline_household_id(db_session, tenant, name: str) -> uuid.UUID:
    """Return the id of the sole baseline (`demo_session_id IS NULL`) household by name."""
    return (
        await db_session.execute(
            text(
                f"SELECT id FROM {tenant.schema_name}.households "
                "WHERE name = :name AND demo_session_id IS NULL"
            ),
            {"name": name},
        )
    ).scalar_one()


async def test_partial_household_returns_contacts_policies_and_open_line(
    seeded,  # noqa: F811 — fixture param, not a redefinition
    db_client,
    db_session,
    container_keys_session_factory,
):
    """Ramirez (partial): its contact, three active policies, and the one uncovered line."""
    assert (
        await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT)
    ).status_code == 200
    household_id = await _baseline_household_id(
        db_session, SUNSHINE, "Ramirez Household"
    )

    response = await db_client.get(f"/api/households/{household_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["household"] == {"id": str(household_id), "name": "Ramirez Household"}
    assert any(
        contact["first_name"] == "Margaret" and contact["last_name"] == "Ramirez"
        for contact in body["contacts"]
    )
    # Covered {medicare_advantage, medicare_supplement, final_expense} → three active
    # policies, all reading a normal status (no renewal in this session).
    assert len(body["policies"]) == 3
    assert {policy["status"] for policy in body["policies"]} == {"Active"}
    # Only `dental_vision_hearing` is uncovered → the sole cross-sell suggestion.
    assert body["cross_sell"] == [
        {
            "product_line": "dental_vision_hearing",
            "product_line_label": "Dental, Vision & Hearing",
        }
    ]


async def test_fully_covered_household_suppresses_cross_sell(
    seeded,  # noqa: F811 — fixture param, not a redefinition
    db_client,
    db_session,
    container_keys_session_factory,
):
    """Familia (all four Florida lines covered) → four active policies, no suggestion."""
    assert (
        await assume(db_client, tenant_slug=FLORIDA.slug, role=Role.AGENT)
    ).status_code == 200
    household_id = await _baseline_household_id(
        db_session, FLORIDA, "Familia Household"
    )

    response = await db_client.get(f"/api/households/{household_id}")

    assert response.status_code == 200
    body = response.json()
    assert len(body["policies"]) == 4
    assert body["cross_sell"] == []


async def test_household_with_no_active_policy_suppresses_cross_sell(
    seeded,  # noqa: F811 — fixture param, not a redefinition
    db_client,
    database_engine,
):
    """A freshly converted household (contact + opportunity, no policy) → no prompt.

    Conversion creates the household → contact → opportunity but issues no policy, so
    the household has zero active policies — cross-sell is suppressed (empty), never a
    dead prompt for every line.
    """
    household_id = await convert_one_lead(db_client, database_engine)

    response = await db_client.get(f"/api/households/{household_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["policies"] == []
    assert body["cross_sell"] == []


async def test_unknown_household_is_404(
    seeded,  # noqa: F811 — fixture param, not a redefinition
    db_client,
):
    """An id no household has is a 404 (indistinguishable from not-visible)."""
    assert (
        await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT)
    ).status_code == 200

    response = await db_client.get(f"/api/households/{uuid.uuid4()}")

    assert response.status_code == 404


async def test_foreign_session_household_is_404(
    seeded,  # noqa: F811 — fixture param, not a redefinition
    db_client,
    database_engine,
    cleanup_foreign_session_households,
):
    """A household owned by *another* demo session is a 404 for the caller."""
    assert (
        await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT)
    ).status_code == 200
    foreign_household_id = await _insert_foreign_session_household(
        database_engine, SUNSHINE
    )

    response = await db_client.get(f"/api/households/{foreign_household_id}")

    assert response.status_code == 404
