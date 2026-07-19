"""DB-backed proof of cross-sell accept — `POST /api/households/{id}/cross-sell` (Epic 13).

Accepting a cross-sell suggestion opens an `origin='cross_sell'`, `stage='New'`
opportunity on the posted line, copying the owner / contact / source policy from the
household's most-recently-issued active policy and emitting `opportunity.created`
(real actor). Driven against the seeded Sunshine **Ramirez** partial household (covers
three of four lines; `dental_vision_hearing` is the open line), owned by `agent.one`.

Committing an `origin='cross_sell'` opportunity (NULL `source_lead_id`) would break the
0020 migration round-trip, so every committing test here reuses Epic 7's
`cleanup_committed_cross_sell` teardown (imported from `test_opportunity_policy_read`).

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no decorator.
"""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.demo.session import DEMO_SESSION_COOKIE_NAME
from app.models.user import Role
from app.tenancy.registry import SUNSHINE

from .test_demo_assume_persona import assume
from .test_endpoints_db import login_as, seeded  # noqa: F401 — used by name
from .test_household_detail import _baseline_household_id
from .test_household_search import convert_one_lead
from .test_lead_reads import mint_live_demo_session
from .test_opportunity_policy_read import (  # noqa: F401 — fixture used by name
    cleanup_committed_cross_sell,
)
from .test_task_queue_endpoint import AGENT_TWO_USERNAME, _login_username


async def _open_line_opportunity(database_engine, tenant, product_line: str):
    """Read back the committed `cross_sell` opportunity for a line (one, cross-schema)."""
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    async with session_factory() as session:
        return (
            await session.execute(
                text(
                    f"SELECT origin, source_policy_id, owner_username, demo_session_id "
                    f"FROM {tenant.schema_name}.opportunities "
                    "WHERE product_line = :line AND origin = 'cross_sell'"
                ),
                {"line": product_line},
            )
        ).one_or_none()


async def test_accept_opens_a_cross_sell_opportunity_on_the_open_line(
    seeded,  # noqa: F811 — fixture param, not a redefinition
    db_client,
    db_session,
    database_engine,
    container_keys_session_factory,
    cleanup_committed_cross_sell,  # noqa: F811 — fixture used by name
):
    """Accepting `dental_vision_hearing` on Ramirez returns the new cross-sell row."""
    assert (
        await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT)
    ).status_code == 200
    household_id = await _baseline_household_id(
        db_session, SUNSHINE, "Ramirez Household"
    )

    response = await db_client.post(
        f"/api/households/{household_id}/cross-sell",
        json={"product_line": "dental_vision_hearing"},
    )

    assert response.status_code == 200
    opportunity = response.json()["opportunity"]
    assert opportunity["origin"] == "cross_sell"
    assert opportunity["stage"] == "New"
    assert opportunity["product_line"] == "dental_vision_hearing"
    assert opportunity["product_line_label"] == "Dental, Vision & Hearing"
    assert opportunity["household_id"] == str(household_id)
    assert opportunity["source_policy_id"] is not None
    # Owner copied from the source policy's originating opportunity (agent.one).
    assert opportunity["owner_username"].startswith("agent.one")

    # It was actually committed (rides `get_tenant_db`'s block-exit commit), session-
    # tagged, and carries the source policy.
    row = await _open_line_opportunity(
        database_engine, SUNSHINE, "dental_vision_hearing"
    )
    assert row is not None
    assert row.origin == "cross_sell"
    assert row.source_policy_id is not None
    assert row.demo_session_id is not None


async def test_tenant_admin_can_accept(
    seeded,  # noqa: F811 — fixture param, not a redefinition
    db_client,
    db_session,
    container_keys_session_factory,
    cleanup_committed_cross_sell,  # noqa: F811 — fixture used by name
):
    """A Tenant Admin (not the source policy's owner) may accept — the admin holder branch."""
    assert (
        await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.TENANT_ADMIN)
    ).status_code == 200
    household_id = await _baseline_household_id(
        db_session, SUNSHINE, "Ramirez Household"
    )

    response = await db_client.post(
        f"/api/households/{household_id}/cross-sell",
        json={"product_line": "dental_vision_hearing"},
    )

    assert response.status_code == 200
    assert response.json()["opportunity"]["origin"] == "cross_sell"


async def test_read_only_cannot_accept_is_403(
    seeded,  # noqa: F811 — fixture param, not a redefinition
    db_client,
    db_session,
    container_keys_session_factory,
):
    """Read-Only lacks `CREATE_EDIT_RECORDS` → 403 at the capability gate (no write)."""
    assert (
        await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.READ_ONLY)
    ).status_code == 200
    household_id = await _baseline_household_id(
        db_session, SUNSHINE, "Ramirez Household"
    )

    response = await db_client.post(
        f"/api/households/{household_id}/cross-sell",
        json={"product_line": "dental_vision_hearing"},
    )

    assert response.status_code == 403


async def test_accept_with_no_demo_session_is_409(
    seeded,  # noqa: F811 — fixture param, not a redefinition
    db_client,
    db_session,
    container_keys_session_factory,
):
    """A plain-logged-in Agent (no demo session) cannot tag a session opp → 409."""
    assert (await login_as(db_client, Role.AGENT)).status_code == 200
    assert DEMO_SESSION_COOKIE_NAME not in db_client.cookies
    household_id = await _baseline_household_id(
        db_session, SUNSHINE, "Ramirez Household"
    )

    response = await db_client.post(
        f"/api/households/{household_id}/cross-sell",
        json={"product_line": "dental_vision_hearing"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "no active demo session"}


async def test_unknown_product_line_is_409(
    seeded,  # noqa: F811 — fixture param, not a redefinition
    db_client,
    db_session,
    container_keys_session_factory,
):
    """A line the tenant does not sell → 409 (no create)."""
    assert (
        await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT)
    ).status_code == 200
    household_id = await _baseline_household_id(
        db_session, SUNSHINE, "Ramirez Household"
    )

    response = await db_client.post(
        f"/api/households/{household_id}/cross-sell",
        json={"product_line": "no_such_line"},
    )

    assert response.status_code == 409


async def test_already_covered_line_is_409(
    seeded,  # noqa: F811 — fixture param, not a redefinition
    db_client,
    db_session,
    container_keys_session_factory,
):
    """A line already covered by an active policy re-validates as covered → 409."""
    assert (
        await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT)
    ).status_code == 200
    household_id = await _baseline_household_id(
        db_session, SUNSHINE, "Ramirez Household"
    )

    # Ramirez already has an active `medicare_advantage` policy.
    response = await db_client.post(
        f"/api/households/{household_id}/cross-sell",
        json={"product_line": "medicare_advantage"},
    )

    assert response.status_code == 409


async def test_household_with_no_active_policy_is_409(
    seeded,  # noqa: F811 — fixture param, not a redefinition
    db_client,
    database_engine,
):
    """A converted household with no issued policy has no source to copy from → 409."""
    # Converted session-less → a baseline household with a contact + opportunity but no
    # policy; visible to the assumed session below.
    household_id = await convert_one_lead(db_client, database_engine)
    assert (
        await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT)
    ).status_code == 200

    response = await db_client.post(
        f"/api/households/{household_id}/cross-sell",
        json={"product_line": "dental_vision_hearing"},
    )

    assert response.status_code == 409


async def test_non_owner_agent_cannot_accept_is_403(
    seeded,  # noqa: F811 — fixture param, not a redefinition
    db_client,
    db_session,
    database_engine,
    container_keys_session_factory,
):
    """`agent.two` (not the source policy's owner, not an admin) is refused the holder → 403.

    Plain login as `agent.two` (no session) + a minted live demo session cookie, so the
    caller clears the session guard and reaches the holder check on Ramirez's policies,
    which `agent.one` owns.
    """
    assert (await _login_username(db_client, AGENT_TWO_USERNAME)).status_code == 200
    session_id = await mint_live_demo_session(database_engine)
    db_client.cookies.set(DEMO_SESSION_COOKIE_NAME, str(session_id))
    household_id = await _baseline_household_id(
        db_session, SUNSHINE, "Ramirez Household"
    )

    response = await db_client.post(
        f"/api/households/{household_id}/cross-sell",
        json={"product_line": "dental_vision_hearing"},
    )

    assert response.status_code == 403
