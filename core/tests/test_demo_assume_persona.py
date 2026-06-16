"""DB-backed proof of the passwordless assume-persona endpoint (Epic 2, P1.6).

Drives `POST /api/demo/assume-persona` over the real DB-backed client — the same
`seeded` + `db_client` + `container_audit_session_factory` substrate the auth
endpoint tests use — logging in as the actual seeded personas without ever sending
a password. The cases prove the contract end-to-end:

- **Correct persona per role:** Agent resolves to the lowest-username seeded Agent
  (`agent.one`), Admin / Read-Only resolve to their single seeded persona, and
  Platform Admin resolves to the global tenantless admin regardless of slug.
- **Capabilities match the role:** the response body's capabilities equal the
  assumed role's RBAC matrix.
- **Session is minted:** a `pf_session` cookie is set and `/api/auth/me` then
  resolves to the assumed persona.
- **Errors:** an unknown tenant for a tenant-scoped role → 404; a bad role value →
  422 (FastAPI request validation over the typed `Role`); the slug is ignored for
  Platform Admin, so an unknown slug there does **not** 404.
- **Role-switch re-mint:** assuming a second persona revokes the prior session (the
  old token no longer resolves), and the logout is audited under the old tenant
  while the login is audited under the new one.
- **Flag off:** with `demo_login_enabled` off the endpoint returns 403 and mints no
  session.

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no
`@pytest.mark.asyncio` decorator. The `seeded` fixture and `tenant_slug_for_role`
helper are reused by name from `test_endpoints_db.py`.
"""

import uuid

from sqlalchemy import text

from app.audit.records import EventType, Outcome
from app.auth.rbac import CAPABILITIES
from app.models.user import Role
from app.tenancy.registry import FLORIDA, SUNSHINE

from .test_endpoints_db import (  # noqa: F401 — `seeded` fixture is used by name
    seeded,
    tenant_slug_for_role,
)


def expected_capabilities(role: Role) -> list[str]:
    """Return the flat, sorted capability strings the RBAC matrix grants `role`."""
    return sorted(capability.value for capability in CAPABILITIES[role])


async def assume(client, *, tenant_slug: str | None, role: Role):
    """Call `POST /api/demo/assume-persona` for a `{tenant_slug, role}` pair."""
    body = {"role": role.value}
    if tenant_slug is not None:
        body["tenant_slug"] = tenant_slug
    return await client.post("/api/demo/assume-persona", json=body)


# --- Phase 2: correct persona per role --------------------------------------


async def test_assume_agent_resolves_lowest_username_agent(seeded, db_client):
    """Assuming Agent resolves the lowest-username seeded Agent (`agent.one`).

    Sunshine seeds two Agents (`agent.one`, `agent.two`); the deterministic
    lowest-username tie-break must land on `agent.one`.
    """
    response = await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT)

    assert response.status_code == 200
    user = response.json()["user"]
    assert user["role"] == Role.AGENT.value
    assert user["username"] == f"agent.one@{SUNSHINE.email_domain}"
    assert user["tenant_id"] is not None
    assert "pf_session" in db_client.cookies


async def test_assume_tenant_admin_resolves_the_seeded_admin(seeded, db_client):
    """Assuming Tenant Admin resolves that tenant's single seeded admin persona."""
    response = await assume(
        db_client, tenant_slug=SUNSHINE.slug, role=Role.TENANT_ADMIN
    )

    assert response.status_code == 200
    user = response.json()["user"]
    assert user["role"] == Role.TENANT_ADMIN.value
    assert user["username"] == f"admin@{SUNSHINE.email_domain}"


async def test_assume_read_only_resolves_the_seeded_read_only(seeded, db_client):
    """Assuming Read-Only resolves that tenant's single seeded read-only persona."""
    response = await assume(
        db_client, tenant_slug=FLORIDA.slug, role=Role.READ_ONLY
    )

    assert response.status_code == 200
    user = response.json()["user"]
    assert user["role"] == Role.READ_ONLY.value
    assert user["username"] == f"readonly@{FLORIDA.email_domain}"


async def test_assume_platform_admin_resolves_global_tenantless_admin(
    seeded, db_client
):
    """Assuming Platform Admin resolves the global tenantless admin (no tenant)."""
    response = await assume(
        db_client, tenant_slug=SUNSHINE.slug, role=Role.PLATFORM_ADMIN
    )

    assert response.status_code == 200
    user = response.json()["user"]
    assert user["role"] == Role.PLATFORM_ADMIN.value
    assert user["tenant_id"] is None


async def test_assume_platform_admin_ignores_unknown_slug(seeded, db_client):
    """Platform Admin ignores the slug, so an unknown one does not 404."""
    response = await assume(
        db_client, tenant_slug="no-such-tenant", role=Role.PLATFORM_ADMIN
    )

    assert response.status_code == 200
    assert response.json()["user"]["role"] == Role.PLATFORM_ADMIN.value


# --- Phase 2: capabilities match the role -----------------------------------


async def test_assumed_capabilities_match_the_role(seeded, db_client):
    """The response capabilities equal the assumed role's RBAC matrix."""
    response = await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT)

    assert response.status_code == 200
    assert response.json()["capabilities"] == expected_capabilities(Role.AGENT)


async def test_assumed_session_resolves_via_me(seeded, db_client):
    """After assuming a persona, `/api/auth/me` resolves to that same persona."""
    assume_response = await assume(
        db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT
    )
    assert assume_response.status_code == 200

    me_response = await db_client.get("/api/auth/me")

    assert me_response.status_code == 200
    assert (
        me_response.json()["user"]["id"]
        == assume_response.json()["user"]["id"]
    )


# --- Phase 2: error contract ------------------------------------------------


async def test_unknown_tenant_is_404_for_tenant_scoped_role(seeded, db_client):
    """A tenant-scoped role with an unknown slug → 404 and no session minted."""
    response = await assume(
        db_client, tenant_slug="no-such-tenant", role=Role.AGENT
    )

    assert response.status_code == 404
    assert "pf_session" not in db_client.cookies


async def test_bad_role_is_422(seeded, db_client):
    """A role value outside the `Role` enum → 422 from request validation."""
    response = await db_client.post(
        "/api/demo/assume-persona",
        json={"tenant_slug": SUNSHINE.slug, "role": "emperor"},
    )

    assert response.status_code == 422


# --- Phase 3: role-switch re-mint -------------------------------------------


async def test_role_switch_revokes_prior_session(seeded, db_client):
    """Switching personas revokes the prior session: the old token stops resolving.

    Assume an Agent (capturing its session cookie), then assume a Platform Admin on
    the same client. Replaying the original Agent cookie against `/me` must now 401
    — its session was revoked during the switch — while the live client resolves to
    the new Platform Admin persona.
    """
    first_response = await assume(
        db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT
    )
    assert first_response.status_code == 200
    old_token = db_client.cookies["pf_session"]

    second_response = await assume(
        db_client, tenant_slug=SUNSHINE.slug, role=Role.PLATFORM_ADMIN
    )
    assert second_response.status_code == 200

    # The live client now carries the new session and resolves to the new persona.
    me_response = await db_client.get("/api/auth/me")
    assert me_response.status_code == 200
    assert me_response.json()["user"]["role"] == Role.PLATFORM_ADMIN.value

    # Replaying the original Agent token resolves to nothing — it was revoked.
    # Replace the client's cookie jar with only the old token so the live (new)
    # session cookie cannot mask the result.
    db_client.cookies.clear()
    db_client.cookies.set("pf_session", old_token)
    replay_response = await db_client.get("/api/auth/me")
    assert replay_response.status_code == 401


async def test_role_switch_audits_logout_old_login_new(
    seeded, db_client, container_audit_session_factory
):
    """A role switch audits logout under the old tenant and login under the new.

    Assume a Sunshine Agent, then switch to a Platform Admin. The switch must write
    an `auth.logout`/`success` row attributed to the Agent in Sunshine's tenant
    store, and an `auth.login`/`success` row for the Platform Admin in the platform
    store. Per-actor before/after deltas keep each assertion attributable against
    the never-reset container DB.
    """
    sunshine_table = f"{SUNSHINE.schema_name}.audit_records"

    first_response = await assume(
        db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT
    )
    assert first_response.status_code == 200
    agent_user_id = uuid.UUID(first_response.json()["user"]["id"])

    agent_logouts_before = await _count_event_rows_for_actor(
        container_audit_session_factory,
        sunshine_table,
        agent_user_id,
        EventType.AUTH_LOGOUT,
    )

    second_response = await assume(
        db_client, tenant_slug=SUNSHINE.slug, role=Role.PLATFORM_ADMIN
    )
    assert second_response.status_code == 200
    admin_user_id = uuid.UUID(second_response.json()["user"]["id"])

    # The Agent's logout was audited in Sunshine's tenant store.
    agent_logouts_after = await _count_event_rows_for_actor(
        container_audit_session_factory,
        sunshine_table,
        agent_user_id,
        EventType.AUTH_LOGOUT,
    )
    assert agent_logouts_after == agent_logouts_before + 1

    # The Platform Admin's login was audited in the tenantless platform store.
    admin_logins = await _read_event_rows_for_actor(
        container_audit_session_factory,
        "platform.audit_records",
        admin_user_id,
        EventType.AUTH_LOGIN,
    )
    assert admin_logins
    written = admin_logins[0]
    assert written.actor_role == Role.PLATFORM_ADMIN
    assert written.outcome == Outcome.SUCCESS
    assert written.tenant_id is None


# --- Phase 4: flag off ------------------------------------------------------


async def test_disabled_flag_returns_403_and_mints_no_session(
    seeded, db_client, monkeypatch
):
    """With `demo_login_enabled` off, the endpoint returns 403 and mints no session."""
    from app.config import settings

    monkeypatch.setattr(settings, "demo_login_enabled", False)

    response = await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT)

    assert response.status_code == 403
    assert response.json() == {"detail": "demo login is disabled"}
    assert "pf_session" not in db_client.cookies


# --- read-back helpers (mirror test_auth_audit.py) --------------------------


async def _read_event_rows_for_actor(
    session_factory, qualified_table, actor_user_id, event_type
):
    """Return one audit table's rows of one event type for one actor, newest-first."""
    async with session_factory() as session:
        rows = await session.execute(
            text(
                "SELECT tenant_id, actor_user_id, actor_role, event_type, "
                "outcome FROM "
                f"{qualified_table} WHERE actor_user_id = :actor_user_id "
                "AND event_type = :event_type ORDER BY occurred_at DESC"
            ),
            {"actor_user_id": actor_user_id, "event_type": str(event_type)},
        )
        return rows.all()


async def _count_event_rows_for_actor(
    session_factory, qualified_table, actor_user_id, event_type
):
    """Count one actor's rows of one event type in an audit store (for deltas)."""
    rows = await _read_event_rows_for_actor(
        session_factory, qualified_table, actor_user_id, event_type
    )
    return len(rows)
