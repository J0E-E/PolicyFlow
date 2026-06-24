"""End-to-end endpoint proof for Epic 11 — `POST /api/demo/session/reset`.

Drives the visitor's Platform-Admin self-service reset over the real DB-backed
client (the same `seeded` + `db_client` substrate the other endpoint tests use).
The reset purges the caller's **own** demo-session overlay (leads across every
tenant schema + its seed-ledger markers) while **keeping** the `demo_sessions`
row, the `pf_demo_session` cookie, and the expiry — so the visit continues.

The endpoint runs the Epic 9 purge engine, which opens its **own** session as the
`demo_purge` role through the module-global `app.demo.purge.session_factory`. So
this file points that global at the container database with the
`container_purge_session_factory` fixture (the Epic 9 idiom), and — because the
happy path seeds a session's queue via `assume-persona` (which encrypts PII) — also
takes `container_keys_session_factory`.

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no
`@pytest.mark.asyncio` decorator. The `seeded`/`db_client` fixtures and `login_as`
are reused from `test_endpoints_db.py`, and the `assume` helper +
`DEMO_SESSION_COOKIE_NAME` from the Epic-1 demo suite.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.demo import purge as purge_module
from app.demo.session import DEMO_SESSION_COOKIE_NAME
from app.models.user import Role
from app.tenancy.registry import FLORIDA, SUNSHINE

from .test_demo_assume_persona import assume
from .test_endpoints_db import (  # noqa: F401 — `seeded` fixture is used by name
    login_as,
    seeded,
)


@pytest.fixture
def container_purge_session_factory(database_engine, monkeypatch):
    """Point `app.demo.purge.session_factory` at the migrated container database.

    The reset endpoint runs the purge engine, which opens its **own** session
    through the module-global `app.demo.purge.session_factory` as the `demo_purge`
    role — separate from the request's `get_db`. The DB substrate must point that
    global at the container database, otherwise the purge would hit the unreachable
    eager default engine. A mirror of `container_purge_session_factory` in
    `test_demo_purge.py`; `monkeypatch` restores the real factory after each test.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    monkeypatch.setattr(purge_module, "session_factory", session_factory)
    return session_factory


async def _count_leads_for_session(
    db_session, schema_name: str, demo_session_id: uuid.UUID
) -> int:
    """Count `<schema>.leads` rows tagged with `demo_session_id`."""
    return (
        await db_session.execute(
            text(
                f"SELECT COUNT(*) FROM {schema_name}.leads "
                "WHERE demo_session_id = :demo_session_id"
            ),
            {"demo_session_id": demo_session_id},
        )
    ).scalar_one()


async def _demo_session_row_exists(db_session, demo_session_id: uuid.UUID) -> bool:
    """Return whether the `platform.demo_sessions` row still exists."""
    found = (
        await db_session.execute(
            text("SELECT 1 FROM platform.demo_sessions WHERE id = :id"),
            {"id": demo_session_id},
        )
    ).first()
    return found is not None


# --- Phase 1: happy path -----------------------------------------------------


async def test_reset_wipes_the_callers_leads_but_keeps_the_session_row(
    seeded,  # noqa: F811 — fixture param, not a redefinition
    db_client,
    db_session,
    container_keys_session_factory,
    container_purge_session_factory,
):
    """A Platform Admin reset removes the caller's session overlay; the row survives.

    Assumes a Sunshine Agent persona first — minting the demo session, setting the
    `pf_demo_session` cookie, and instantiating that session's claimable queue
    (Epic 7). Then role-switches to Platform Admin (which reuses the same demo
    session, leaving the cookie untouched) and calls the reset. The session's leads
    are gone, but its `demo_sessions` row remains alive for the continuing visit.
    """
    assume_response = await assume(
        db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT
    )
    assert assume_response.status_code == 200
    demo_session_id = uuid.UUID(db_client.cookies[DEMO_SESSION_COOKIE_NAME])

    # The assumed persona's queue was instantiated — overlay leads exist to wipe.
    assert (
        await _count_leads_for_session(
            db_session, SUNSHINE.schema_name, demo_session_id
        )
        > 0
    )

    # Role-switch to Platform Admin (reuses the same demo session + cookie; the
    # admin ignores the slug, and the demo-session reuse leaves the cookie alone).
    admin_response = await assume(
        db_client, tenant_slug=SUNSHINE.slug, role=Role.PLATFORM_ADMIN
    )
    assert admin_response.status_code == 200
    assert uuid.UUID(db_client.cookies[DEMO_SESSION_COOKIE_NAME]) == demo_session_id

    response = await db_client.post("/api/demo/session/reset")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"leads_deleted", "ledger_deleted"}
    assert body["leads_deleted"] > 0
    assert body["ledger_deleted"] > 0

    # The caller's overlay is gone across both tenant schemas.
    for tenant in (SUNSHINE, FLORIDA):
        assert (
            await _count_leads_for_session(
                db_session, tenant.schema_name, demo_session_id
            )
            == 0
        )

    # The session row + cookie survive — the visit (and countdown) continues.
    assert await _demo_session_row_exists(db_session, demo_session_id) is True
    assert DEMO_SESSION_COOKIE_NAME in db_client.cookies


# --- Phase 1: rejection & boundary proofs ------------------------------------


@pytest.mark.parametrize(
    "role",
    [Role.TENANT_ADMIN, Role.AGENT, Role.READ_ONLY],
)
async def test_non_platform_roles_are_rejected(
    seeded, db_client, role  # noqa: F811 — fixture param, not a redefinition
):
    """Every non-platform role → 403 — only Platform Admin can reset a session."""
    assert (await login_as(db_client, role)).status_code == 200

    response = await db_client.post("/api/demo/session/reset")

    assert response.status_code == 403
    assert response.json() == {"detail": "insufficient permissions"}


async def test_reset_unauthenticated_is_401(
    seeded, db_client  # noqa: F811 — fixture param, not a redefinition
):
    """A client with no session cookie → 401, from require_authenticated."""
    response = await db_client.post("/api/demo/session/reset")

    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}


async def test_reset_with_no_active_demo_session_is_409(
    seeded, db_client  # noqa: F811 — fixture param, not a redefinition
):
    """A Platform Admin with no live demo session → 409 'no active demo session'.

    Logs in directly (plain `/api/auth/login`, which never mints a demo session), so
    the caller is an authenticated Platform Admin but carries no `pf_demo_session`
    cookie — the reset has nothing to wipe and refuses with 409.
    """
    assert (await login_as(db_client, Role.PLATFORM_ADMIN)).status_code == 200
    assert DEMO_SESSION_COOKIE_NAME not in db_client.cookies

    response = await db_client.post("/api/demo/session/reset")

    assert response.status_code == 409
    assert response.json() == {"detail": "no active demo session"}
