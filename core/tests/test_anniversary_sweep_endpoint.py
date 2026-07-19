"""End-to-end endpoint proof for P2.4 Epic 8 — `POST /api/renewals/anniversary-sweep`.

The sibling of `test_aep_sweep_endpoint`: drives the Platform-Admin anniversary sweep
over the real DB-backed client (the shared `seeded` + `db_client` substrate). The sweep
runs `generate_renewals` for the `"anniversary"` rule inside a scoped tenant write
session and commits on block exit, so the renewal it writes persists — which is what
makes the idempotent re-run report the policy as `skipped`.

Unlike the AEP sweep (which bypasses the seasonal calendar), the anniversary sweep only
renews policies inside the rolling 60-day `anniversary_within` window. The sole seeded
Sunshine anniversary-line policy in window is the **back-dated `medicare_supplement`**
(P2.4 Epic 5 — its anniversary is ~30 days out), and it is `demo_session_id IS NULL`
(visible to every session's sweep). So a first sweep reports `{generated: 1, skipped: 0}`
and a re-run `{generated: 0, skipped: 1}`. The other Sunshine money-path lines don't
renew: `medicare_advantage` is an AEP line (a different rule) and `final_expense` is a
`none` (non-renewing) line — asserting the single `origin='renewal'` opportunity is on
`medicare_supplement` proves the `final_expense` line generated nothing. (Life lines are
Florida-only and non-renewing; their no-renewal is covered by the rules unit tests plus
the tenant-scoped candidate select, not this Sunshine-scoped endpoint test.)

The happy path assumes a Sunshine Agent first (minting the demo session with
`last_tenant_slug = sunshine` and instantiating its queue, which encrypts PII — hence
`container_keys_session_factory`) then role-switches to Platform Admin, reusing the same
demo session with `last_tenant_slug` intact.

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no
`@pytest.mark.asyncio` decorator. The `seeded`/`db_client`/`login_as` fixtures come from
`test_endpoints_db.py`, the `assume` helper + `DEMO_SESSION_COOKIE_NAME` from the demo
suite, and `cleanup_committed_renewals` from `conftest.py`.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.demo.session import DEMO_SESSION_COOKIE_NAME
from app.models.user import Role
from app.tenancy.registry import SUNSHINE

from .test_demo_assume_persona import assume
from .test_endpoints_db import (  # noqa: F401 — `seeded` fixture is used by name
    login_as,
    seeded,
)


async def _sole_committed_renewal_product_line(database_engine) -> str:
    """Return the `product_line` of the one committed Sunshine renewal opportunity.

    Reads through a fresh session (the sweep already committed), asserting there is
    exactly one `origin='renewal'` opportunity so the caller can trust the single line
    it names.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    async with session_factory() as session:
        product_lines = (
            await session.execute(
                text(
                    f"SELECT product_line FROM {SUNSHINE.schema_name}.opportunities "
                    "WHERE origin = 'renewal'"
                )
            )
        ).scalars().all()
    assert product_lines == ["medicare_supplement"]
    return product_lines[0]


# --- Happy path + idempotent re-run ------------------------------------------


async def test_anniversary_sweep_renews_the_back_dated_policy_then_re_run_skips(
    seeded,  # noqa: F811 — fixture param, not a redefinition
    db_client,
    database_engine,
    container_keys_session_factory,
    cleanup_committed_renewals,
):
    """A first sweep renews the back-dated supplement policy; a re-run reports it skipped.

    Also asserts the sole committed renewal is on `medicare_supplement`, proving the
    other Sunshine lines (`medicare_advantage` = AEP rule, `final_expense` = none rule)
    generated nothing.
    """
    assume_response = await assume(
        db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT
    )
    assert assume_response.status_code == 200

    admin_response = await assume(
        db_client, tenant_slug=SUNSHINE.slug, role=Role.PLATFORM_ADMIN
    )
    assert admin_response.status_code == 200
    assert DEMO_SESSION_COOKIE_NAME in db_client.cookies

    first = await db_client.post("/api/renewals/anniversary-sweep")
    assert first.status_code == 200
    assert first.json() == {"generated": 1, "skipped": 0}

    # The one renewal is on the anniversary line only — not the AEP or none-rule lines.
    assert await _sole_committed_renewal_product_line(database_engine) == (
        "medicare_supplement"
    )

    # The committed renewal now blocks a duplicate — the re-run is a pure skip.
    second = await db_client.post("/api/renewals/anniversary-sweep")
    assert second.status_code == 200
    assert second.json() == {"generated": 0, "skipped": 1}


# --- Rejection & boundary proofs ---------------------------------------------


@pytest.mark.parametrize("role", [Role.TENANT_ADMIN, Role.AGENT, Role.READ_ONLY])
async def test_non_platform_roles_are_rejected(
    seeded, db_client, role  # noqa: F811 — fixture param, not a redefinition
):
    """Every non-platform role → 403 — only Platform Admin can run a sweep."""
    assert (await login_as(db_client, role)).status_code == 200

    response = await db_client.post("/api/renewals/anniversary-sweep")

    assert response.status_code == 403
    assert response.json() == {"detail": "insufficient permissions"}


async def test_sweep_with_no_active_demo_session_is_409(
    seeded, db_client  # noqa: F811 — fixture param, not a redefinition
):
    """A Platform Admin with no live demo session → 409 'no active demo session'.

    Logs in directly (plain `/api/auth/login`, which never mints a demo session), so
    the caller is an authenticated Platform Admin but carries no `pf_demo_session`
    cookie — the sweep has no session to scope and refuses.
    """
    assert (await login_as(db_client, Role.PLATFORM_ADMIN)).status_code == 200
    assert DEMO_SESSION_COOKIE_NAME not in db_client.cookies

    response = await db_client.post("/api/renewals/anniversary-sweep")

    assert response.status_code == 409
    assert response.json() == {"detail": "no active demo session"}


async def test_sweep_with_no_tenant_selected_is_409(
    seeded, db_client, container_keys_session_factory  # noqa: F811
):
    """A demo session that never picked a tenant → 409 'no tenant selected'.

    Assuming Platform Admin as the *first* persona mints a demo session but, because
    the tenantless admin passes no tenant slug, leaves `last_tenant_slug` unset — so
    the sweep has a live session yet no tenant to scope to.
    """
    admin_response = await assume(
        db_client, tenant_slug=SUNSHINE.slug, role=Role.PLATFORM_ADMIN
    )
    assert admin_response.status_code == 200
    assert DEMO_SESSION_COOKIE_NAME in db_client.cookies

    response = await db_client.post("/api/renewals/anniversary-sweep")

    assert response.status_code == 409
    assert response.json() == {"detail": "no tenant selected"}
