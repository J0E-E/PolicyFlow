"""End-to-end endpoint proof for P2.4 Epic 6 — `POST /api/renewals/aep-sweep`.

Drives the Platform-Admin AEP sweep over the real DB-backed client (the same
`seeded` + `db_client` substrate the other endpoint tests use). The sweep runs
`generate_renewals` for the AEP rule inside a scoped tenant write session and
commits on block exit, so unlike the pure `test_renewal_generation` service tests
(which roll back an uncommitted `_scoped_session`) the renewal it writes persists —
which is exactly what makes the idempotent re-run report the policy as `skipped`.

The target is the **sole** seeded Sunshine `medicare_advantage` baseline policy
(`demo_session_id IS NULL`, visible to every session's sweep — P2.4 Epic 5), so a
first sweep reports `{generated: 1, skipped: 0}` and a re-run `{generated: 0,
skipped: 1}`. The happy path assumes a Sunshine Agent first (minting the demo
session with `last_tenant_slug = sunshine` and instantiating its queue, which
encrypts PII — hence `container_keys_session_factory`) then role-switches to
Platform Admin, which reuses the same demo session and leaves `last_tenant_slug`
intact.

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no
`@pytest.mark.asyncio` decorator. The `seeded`/`db_client`/`login_as` fixtures come
from `test_endpoints_db.py`, the `assume` helper + `DEMO_SESSION_COOKIE_NAME` from
the demo suite.
"""

import pytest

from app.demo.session import DEMO_SESSION_COOKIE_NAME
from app.models.user import Role
from app.tenancy.registry import SUNSHINE

from .test_demo_assume_persona import assume
from .test_endpoints_db import (  # noqa: F401 — `seeded` fixture is used by name
    login_as,
    seeded,
)

# `cleanup_committed_renewals` now lives in conftest.py (shared across the sweep suites).


# --- Phase 2: happy path + idempotent re-run ---------------------------------


async def test_aep_sweep_renews_the_seeded_ma_policy_then_re_run_skips(
    seeded,  # noqa: F811 — fixture param, not a redefinition
    db_client,
    container_keys_session_factory,
    cleanup_committed_renewals,
):
    """A first sweep renews the sole seeded MA policy; a re-run reports it skipped."""
    assume_response = await assume(
        db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT
    )
    assert assume_response.status_code == 200

    admin_response = await assume(
        db_client, tenant_slug=SUNSHINE.slug, role=Role.PLATFORM_ADMIN
    )
    assert admin_response.status_code == 200
    assert DEMO_SESSION_COOKIE_NAME in db_client.cookies

    first = await db_client.post("/api/renewals/aep-sweep")
    assert first.status_code == 200
    assert first.json() == {"generated": 1, "skipped": 0}

    # The committed renewal now blocks a duplicate — the re-run is a pure skip.
    second = await db_client.post("/api/renewals/aep-sweep")
    assert second.status_code == 200
    assert second.json() == {"generated": 0, "skipped": 1}


# --- Phase 2: rejection & boundary proofs ------------------------------------


@pytest.mark.parametrize("role", [Role.TENANT_ADMIN, Role.AGENT, Role.READ_ONLY])
async def test_non_platform_roles_are_rejected(
    seeded, db_client, role  # noqa: F811 — fixture param, not a redefinition
):
    """Every non-platform role → 403 — only Platform Admin can run a sweep."""
    assert (await login_as(db_client, role)).status_code == 200

    response = await db_client.post("/api/renewals/aep-sweep")

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

    response = await db_client.post("/api/renewals/aep-sweep")

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

    response = await db_client.post("/api/renewals/aep-sweep")

    assert response.status_code == 409
    assert response.json() == {"detail": "no tenant selected"}
