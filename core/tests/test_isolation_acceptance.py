"""Isolation acceptance suite for P1.2 (Epic 8).

This is the phase's named acceptance proof: that a Tenant A user cannot read or
modify any Tenant B record, backed by a DB-layer proof that a per-tenant role is
*physically* denied another tenant's schema.

It is packaged **add-only** — it asserts the one genuinely missing proof plus a
thin named acceptance narrative, and deliberately does **not** duplicate the
assertions Epics 5–7 already own (the `SET LOCAL` no-leak/reset proof stays in
`test_tenant_scoping.py`; the per-field endpoint checks stay in
`test_tenant_settings_endpoint.py` / `test_platform_settings_endpoint.py`).

- **Phase 1 — DB-layer physical permission-denied proof (headline):** under a
  switched per-tenant role (`SET LOCAL ROLE tenant_<A>`), a `SELECT` / `UPDATE` /
  `INSERT` against `<B>.tenant_settings` is *raised* by Postgres as a
  permission-denied error, while the role's **own** schema still reads — proving
  the connection truly drops privileges under a switched role (closing the
  superuser-bypass concern, TDD §7), not merely that the privilege catalog says
  so. Mirrors the `database_engine` + `text()` substrate of
  `test_tenant_schemas.py` / `test_tenant_settings.py`, seeding via `seed()` the
  way `test_tenant_scoping.py` does.

- **Phase 2 — named app-layer A-vs-B acceptance test + carve-out boundary:**
  driving `GET /api/tenant/settings` as each tenant persona, every caller reads
  only its own row (a cross-leak fails loudly); and a non-platform persona hitting
  `GET /api/platform/tenant-settings` gets 403 — confirming the platform path is
  the only sanctioned cross-tenant read. Reuses the `seeded` / `db_client`
  substrate and helpers from `test_endpoints_db.py` and
  `test_tenant_settings_endpoint.py`.

`pytest.ini` sets `asyncio_mode = auto`, so the Phase 2 async tests carry no
`@pytest.mark.asyncio` decorator; the Phase 1 substrate tests do, matching the
other `database_engine` substrate modules.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.models.user import Role
from app.seed import demo_user_specs, seed
from app.tenancy.registry import TENANTS

from .test_endpoints_db import (  # noqa: F401 — `seeded` fixture is used by name
    login_as,
    seeded,
)
from .test_tenant_settings_endpoint import (
    expected_settings_for_slug,
    slugs_with_a_tenant_user,
)


# --- Phase 1: DB-layer physical permission-denied proof ----------------------


def _tenant_pairs():
    """Yield every ordered (acting, other) tenant pair from the registry.

    The acting tenant's role is switched on; the other tenant's schema is the one
    that must be physically out of reach.
    """
    for acting in TENANTS:
        for other in TENANTS:
            if other is not acting:
                yield acting, other


# Each denied statement aborts its own transaction, so every attempt runs in its
# own `engine.begin()` block: `SET LOCAL ROLE` resets when that transaction rolls
# back, exactly matching the production `SET LOCAL` pattern. Identifiers come only
# from the registry (never request input), interpolated verbatim — the same way
# the migrations build them.
def _denied_statements_against(other_schema: str) -> dict[str, str]:
    """Return the cross-tenant statements that must each be permission-denied.

    A minimal INSERT is enough: Postgres checks table privileges before it
    evaluates constraints, so the statement is denied before the (incomplete)
    row would ever be validated.
    """
    qualified_table = f"{other_schema}.tenant_settings"
    return {
        "SELECT": f"SELECT * FROM {qualified_table}",
        "UPDATE": (
            f"UPDATE {qualified_table} "
            "SET welcome_message = 'breach attempt'"
        ),
        "INSERT": (
            f"INSERT INTO {qualified_table} (tenant_id, brand_primary_color, "
            "welcome_message) VALUES (gen_random_uuid(), '#000000', 'breach')"
        ),
    }


@pytest.mark.asyncio
async def test_switched_tenant_role_is_denied_other_schema(database_engine):
    """Under `SET LOCAL ROLE tenant_<A>`, every write/read on <B> is denied.

    For each ordered tenant pair, switch to the acting tenant's role and attempt a
    SELECT / UPDATE / INSERT against the *other* tenant's `tenant_settings`. Each
    must raise a Postgres insufficient-privilege error (a SQLAlchemy
    `ProgrammingError` wrapping asyncpg's `InsufficientPrivilegeError`, surfacing
    as "permission denied"). This is the physical proof that the connection drops
    privileges under a switched role — not merely a privilege-catalog boolean.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    async with session_factory() as session:
        await seed(session)

    for acting, other in _tenant_pairs():
        for operation, statement in _denied_statements_against(
            other.schema_name
        ).items():
            # Each attempt gets its own transaction: the denial aborts it, and the
            # `SET LOCAL ROLE` resets as the block rolls back on the raised error.
            with pytest.raises(ProgrammingError) as denial:
                async with database_engine.begin() as connection:
                    await connection.execute(
                        text(f"SET LOCAL ROLE {acting.db_role}")
                    )
                    await connection.execute(text(statement))

            message = str(denial.value).lower()
            assert "permission denied" in message, (
                f"expected {acting.db_role} to be denied {operation} on "
                f"{other.schema_name}.tenant_settings, got: {message}"
            )


@pytest.mark.asyncio
async def test_switched_tenant_role_still_reads_own_schema(database_engine):
    """The same switched role reads its *own* schema — denial is isolation.

    Proves the per-tenant role is denied the other schema because of isolation, not
    because the role is broken: under `SET LOCAL ROLE tenant_<A>`, a SELECT on
    `<A>.tenant_settings` succeeds and returns that tenant's seeded row.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    async with session_factory() as session:
        await seed(session)

    for tenant in TENANTS:
        async with database_engine.begin() as connection:
            await connection.execute(text(f"SET LOCAL ROLE {tenant.db_role}"))
            own_row = (
                await connection.execute(
                    text(
                        "SELECT welcome_message "
                        f"FROM {tenant.schema_name}.tenant_settings"
                    )
                )
            ).one()
            assert own_row.welcome_message


# --- Phase 2: named app-layer A-vs-B acceptance test -------------------------


async def test_a_tenant_user_cannot_read_another_tenants_record(seeded, db_client):
    """ACCEPTANCE: a Tenant A user cannot read another tenant's record via any endpoint.

    Drives `GET /api/tenant/settings` as a persona from each tenant in turn (the
    endpoint takes no tenant parameter, so isolation comes entirely from
    `get_tenant_db`'s scoping). Each caller reads only its own row, and the
    tenants' `tenant_id`s and welcome messages are asserted distinct across
    tenants — a cross-leak between schemas would fail loudly here.
    """
    slugs = slugs_with_a_tenant_user()
    assert len(slugs) >= 2, "need at least two tenants to prove non-crossing"

    seen_tenant_ids: set[str] = set()
    seen_welcome_messages: set[str] = set()

    for slug in slugs:
        email = next(
            spec_email
            for spec_email, _role, spec_slug in demo_user_specs()
            if spec_slug == slug
        )
        login_response = await db_client.post(
            "/api/auth/login",
            json={"username": email, "password": settings.seed_user_password},
        )
        assert login_response.status_code == 200

        response = await db_client.get("/api/tenant/settings")
        assert response.status_code == 200
        tenant_settings = response.json()["settings"]

        # The caller reads its own tenant's row, never another's.
        assert (
            tenant_settings["welcome_message"]
            == expected_settings_for_slug(slug)["welcome_message"]
        )

        seen_tenant_ids.add(tenant_settings["tenant_id"])
        seen_welcome_messages.add(tenant_settings["welcome_message"])

        await db_client.post("/api/auth/logout")

    # Distinct identity and content per tenant: nothing crossed between schemas.
    assert len(seen_tenant_ids) == len(slugs)
    assert len(seen_welcome_messages) == len(slugs)


# --- Phase 2: carve-out boundary ---------------------------------------------


async def test_tenant_persona_cannot_use_platform_cross_tenant_path(seeded, db_client):
    """The platform carve-out is the only sanctioned cross-tenant read.

    A tenant persona hitting `GET /api/platform/tenant-settings` gets 403 —
    confirming a tenant user cannot reach the cross-tenant list and the platform
    path is reserved for the Platform Admin carve-out.
    """
    assert (await login_as(db_client, Role.TENANT_ADMIN)).status_code == 200

    response = await db_client.get("/api/platform/tenant-settings")

    assert response.status_code == 403
    assert response.json() == {"detail": "insufficient permissions"}
