"""DB-backed proof of the guarded lead PII reveal route (Epic 15, P1.7).

Epic 11 added the masked lead reads; Epic 15 adds the one place plaintext lead PII
crosses the API boundary: `POST /api/leads/{lead_id}/reveal`, mirroring `pii_demo`'s
reveal. It unmasks **one** encrypted field of one lead at a time — every encrypted
column is revealable (`email`, `phone`, `date_of_birth`, `street_address`); any other
name is a generic `422 "field is not revealable"` refused **before** the DB read.
Unlike `pii_demo`, a lead has **no** never-revealable deny-list, so those cases are
absent here. The one allow-listed field is decrypted, the `on_pii_revealed` audit seam
is awaited with `entity_type="lead"`, and `{"field": …, "value": …}` is returned.

These drive the real endpoint over the DB-backed client (the same `seeded` /
`db_client` substrate the other endpoint tests use), logging in as the seeded Sunshine
Agent — who holds both `CREATE_EDIT_RECORDS` (to create the lead) and `REVEAL_PII` (to
reveal it), so a create-then-reveal in one test works, exactly as the `pii_demo` reveal
tests do. The reveal decrypts PII, so it rides the existing seeded substrate, which
already wires `app.pii.keys.session_factory` to the container key store via
`container_keys_session_factory` — a reachable key store comes for free.

Coverage:

- **Happy paths:** reveal each of the four fields (`email`, `phone`, `date_of_birth`,
  `street_address`) → 200 with the real, unmasked value (not the masked display form).
- **Absent optional:** a lead created without `street_address` reveals it as
  `value: null` with a 200 (the uniform call site, matching the masked read's null
  rendering of absent optionals) — not a 404 or a 422.
- **Refusal:** an unknown field (`first_name`) → 422; an unknown field on an absent id
  → 422 (the field is checked before the DB read — the refusal is about the field, not
  the lead).
- **Not found:** a well-formed but absent id, and a cross-tenant id, both → 404.
- **RBAC:** a Read-Only caller → 403; the Platform Admin → 403; an unauthenticated
  caller → 401.
- **The seam is awaited:** a monkeypatched `AsyncMock` over the router-bound
  `on_pii_revealed` is asserted awaited once with the request session, the caller
  `Identity`, `entity_type="lead"`, `entity_id=<the created lead id>`, and
  `field_name="email"`.

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no
`@pytest.mark.asyncio` decorator. The `seeded` / `db_client` fixtures and the
`login_as` helper are reused by name from `test_endpoints_db.py` and `conftest.py`;
`insert_lead` / `login_agent_for_slug` / `tenant_id_for_slug` / `unique_marker` come
from `test_lead_reads.py`.
"""

import uuid
from unittest.mock import AsyncMock

from app.demo.session import DEMO_SESSION_COOKIE_NAME
from app.leads import router as leads_router
from app.models.user import Role
from app.tenancy.registry import FLORIDA, SUNSHINE

from tests.test_endpoints_db import login_as, seeded  # noqa: F401
from tests.test_lead_reads import (
    insert_lead,
    mint_live_demo_session,
    tenant_id_for_slug,
    unique_marker,
)


def unique_contact() -> tuple[str, str]:
    """Return an (email, phone) pair unique to one lead, collision-proof on both keys.

    The container DB is **session-scoped and shared**, so every lead these tests create
    must own contact details no other test's (or the seed's) lead fingerprints the same
    on — the duplicate matcher matches on the email **or** phone blind index. The phone
    is a distinct `+1999`-prefixed number whose 10 trailing digits come from a full
    uuid's integer (high entropy, all decimal so `normalize_phone` drops none), and the
    email carries a `reveal-`-prefixed full-hex token. This mirrors the collision-proof
    generator Epic 14's resolve-duplicate tests define for the same shared-container
    reason (project memory: the narrow `+1 (415) 555-{hex}` helpers false-flag once
    enough rows accumulate).
    """
    token = uuid.uuid4().hex
    phone_digits = f"{uuid.uuid4().int % 10**10:010d}"
    return (f"reveal-{token}@example.com", f"+1999{phone_digits}")


# The plaintext field values a successful reveal must return — unmasked — so each
# assertion can compare against the known input rather than a masked display string.
# `email` and `phone` are filled per-test from `unique_contact()`; these are the fixed
# fields shared across the happy-path bodies.
SAMPLE_DATE_OF_BIRTH = "1950-03-15"
SAMPLE_STREET_ADDRESS = "100 Demo Street"


def lead_body(email: str, phone: str, **overrides) -> dict:
    """Return a full Sunshine create body for the given contact, plus any overrides.

    The product-line keys are real Sunshine keys (the seeded Agent's tenant), so the
    router's per-tenant key-membership check passes. `date_of_birth` lands in the `65+`
    band and `street_address` is present by default; a test that needs the absent-blob
    case overrides `street_address=None`.
    """
    body = {
        "first_name": "Reveal",
        "last_name": "Target",
        "email": email,
        "phone": phone,
        "date_of_birth": SAMPLE_DATE_OF_BIRTH,
        "zip_code": "33101",
        "product_lines_of_interest": ["medicare_advantage"],
        "street_address": SAMPLE_STREET_ADDRESS,
    }
    body.update(overrides)
    return body


async def _create_lead(client, **overrides) -> dict:
    """Create one lead as the logged-in caller; return its masked body.

    Each call uses a fresh `unique_contact()` so the shared container's accumulated
    rows never make the duplicate matcher flag this lead.
    """
    email, phone = unique_contact()
    response = await client.post("/api/leads", json=lead_body(email, phone, **overrides))
    assert response.status_code == 201
    return response.json()["lead"], email, phone


# --- Phase 1: reveal each revealable field (the happy paths) ------------------


async def test_reveal_email_returns_unmasked_value_for_agent(seeded, db_client):
    """An Agent revealing `email` → 200 with the real, unmasked address.

    The created lead's `email` comes back masked (`r***@e***.com`); revealing it must
    return the stored plaintext, proving the field is decrypted and the unmasked value
    crosses the boundary on this path.
    """
    assert (await login_as(db_client, Role.AGENT)).status_code == 200
    created, email, _phone = await _create_lead(db_client)

    response = await db_client.post(
        f"/api/leads/{created['id']}/reveal",
        json={"field": "email"},
    )

    assert response.status_code == 200
    assert response.json() == {"field": "email", "value": email}


async def test_reveal_phone_returns_unmasked_value(seeded, db_client):
    """Revealing `phone` returns the stored plaintext number, unmasked."""
    assert (await login_as(db_client, Role.AGENT)).status_code == 200
    created, _email, phone = await _create_lead(db_client)

    response = await db_client.post(
        f"/api/leads/{created['id']}/reveal",
        json={"field": "phone"},
    )

    assert response.status_code == 200
    assert response.json() == {"field": "phone", "value": phone}


async def test_reveal_date_of_birth_returns_unmasked_value(seeded, db_client):
    """Revealing `date_of_birth` returns the stored ISO date, unmasked.

    The masked read renders date of birth as the constant `****-**-**`; the reveal path
    returns the actual stored ISO string (the value encrypted on create).
    """
    assert (await login_as(db_client, Role.AGENT)).status_code == 200
    created, _email, _phone = await _create_lead(db_client)

    response = await db_client.post(
        f"/api/leads/{created['id']}/reveal",
        json={"field": "date_of_birth"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "field": "date_of_birth",
        "value": SAMPLE_DATE_OF_BIRTH,
    }


async def test_reveal_street_address_returns_unmasked_value(seeded, db_client):
    """Revealing `street_address` returns the stored plaintext, unmasked.

    The masked read renders a present street address as the constant `***`; the reveal
    path returns the actual stored value (the value encrypted on create).
    """
    assert (await login_as(db_client, Role.AGENT)).status_code == 200
    created, _email, _phone = await _create_lead(db_client)

    response = await db_client.post(
        f"/api/leads/{created['id']}/reveal",
        json={"field": "street_address"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "field": "street_address",
        "value": SAMPLE_STREET_ADDRESS,
    }


async def test_reveal_absent_street_address_returns_null(seeded, db_client):
    """Revealing an absent optional field (`street_address`) returns `value: null`, 200.

    A lead created without a street address has no `street_address_encrypted` blob;
    revealing it returns `{field, value: null}` with a 200 (the uniform call site,
    matching the masked read's null rendering of absent optionals) — not a 404 or a 422.
    """
    assert (await login_as(db_client, Role.AGENT)).status_code == 200
    created, _email, _phone = await _create_lead(db_client, street_address=None)

    response = await db_client.post(
        f"/api/leads/{created['id']}/reveal",
        json={"field": "street_address"},
    )

    assert response.status_code == 200
    assert response.json() == {"field": "street_address", "value": None}


# --- Phase 2: refusals and not-found -----------------------------------------


async def test_reveal_unknown_field_is_not_revealable_422(seeded, db_client):
    """Revealing an unknown field (`first_name`) → 422 with the generic message."""
    assert (await login_as(db_client, Role.AGENT)).status_code == 200
    created, _email, _phone = await _create_lead(db_client)

    response = await db_client.post(
        f"/api/leads/{created['id']}/reveal",
        json={"field": "first_name"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "field is not revealable"}


async def test_reveal_unknown_field_is_422_even_for_absent_id(seeded, db_client):
    """The field is validated before the DB read: an unknown field → 422 for an absent
    id (the refusal is about the field, not the lead), mirroring `pii_demo`."""
    assert (await login_as(db_client, Role.AGENT)).status_code == 200

    response = await db_client.post(
        "/api/leads/00000000-0000-0000-0000-000000000000/reveal",
        json={"field": "first_name"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "field is not revealable"}


async def test_reveal_absent_id_is_404(seeded, db_client):
    """A revealable field on a well-formed but absent lead id → 404."""
    assert (await login_as(db_client, Role.AGENT)).status_code == 200

    response = await db_client.post(
        "/api/leads/00000000-0000-0000-0000-000000000000/reveal",
        json={"field": "email"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "lead not found"}


async def test_reveal_cross_tenant_id_is_404(seeded, db_client, database_engine):
    """A lead id belonging to *another* tenant → 404, indistinguishable from missing.

    A lead is inserted into Florida's schema; a logged-in Sunshine Agent revealing it
    by id gets a 404 — `get_tenant_db` scopes the lookup to Sunshine's schema, so
    Florida's row is physically out of reach and a caller can neither reveal nor probe
    for another tenant's leads.
    """
    florida_tenant_id = await tenant_id_for_slug(database_engine, FLORIDA.slug)
    email, phone = unique_contact()
    florida_lead_id = await insert_lead(
        database_engine,
        FLORIDA.schema_name,
        florida_tenant_id,
        first_name=unique_marker(),
        email=email,
        phone=phone,
    )

    assert (await login_as(db_client, Role.AGENT)).status_code == 200  # Sunshine
    response = await db_client.post(
        f"/api/leads/{florida_lead_id}/reveal",
        json={"field": "email"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "lead not found"}


# --- Phase 3: RBAC -----------------------------------------------------------


async def test_reveal_forbidden_for_read_only(seeded, db_client):
    """A Read-Only user lacks `REVEAL_PII` → 403."""
    assert (await login_as(db_client, Role.READ_ONLY)).status_code == 200

    response = await db_client.post(
        f"/api/leads/{uuid.uuid4()}/reveal",
        json={"field": "email"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "insufficient permissions"}


async def test_reveal_forbidden_for_platform_admin(seeded, db_client):
    """The tenantless Platform Admin lacks `REVEAL_PII` → 403 (the capability gate fires
    before `get_tenant_db`, so this is a 403, not the tenantless 400)."""
    assert (await login_as(db_client, Role.PLATFORM_ADMIN)).status_code == 200

    response = await db_client.post(
        f"/api/leads/{uuid.uuid4()}/reveal",
        json={"field": "email"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "insufficient permissions"}


async def test_reveal_unauthenticated_is_401(seeded, db_client):
    """A fresh client with no session cookie cannot reveal → 401."""
    response = await db_client.post(
        f"/api/leads/{uuid.uuid4()}/reveal",
        json={"field": "email"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}


# --- Phase 4: the reveal seam ------------------------------------------------


async def test_reveal_awaits_the_seam_with_the_expected_arguments(
    seeded, db_client, monkeypatch
):
    """A successful reveal awaits `on_pii_revealed` once with the right arguments.

    Monkeypatches the router-bound `on_pii_revealed` with an `AsyncMock` so the seam
    stays a no-op but records its call. A successful `email` reveal must await it
    exactly once with `entity_type="lead"`, `entity_id=<the created lead id>`,
    `field_name="email"`, and the caller's `Identity` — proving the audit + event seam
    lands on a real, correctly-shaped call site.
    """
    assert (await login_as(db_client, Role.AGENT)).status_code == 200
    created, _email, _phone = await _create_lead(db_client)

    seam_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(leads_router, "on_pii_revealed", seam_mock)

    response = await db_client.post(
        f"/api/leads/{created['id']}/reveal",
        json={"field": "email"},
    )

    assert response.status_code == 200
    seam_mock.assert_awaited_once()
    call_arguments = seam_mock.await_args
    # The request session is the first positional argument (threaded in for the
    # transactional outbox enqueue); Identity is second; the rest are entity_type,
    # entity_id, field_name (all positional in the handler's call).
    _db, _identity, entity_type, entity_id, field_name = call_arguments.args
    assert entity_type == "lead"
    assert entity_id == uuid.UUID(created["id"])
    assert field_name == "email"


# --- Phase 5: demo-session read isolation (Epic 5) ---------------------------


async def test_reveal_seed_row_succeeds(seeded, db_client, database_engine):
    """Revealing a shared seed row (`demo_session_id IS NULL`) succeeds → 200.

    Unlike the mutating actions, reveal carries **no** seed `409` — revealing shared
    seed PII is fine. A Sunshine Agent carrying a live session cookie reveals a seed
    row's email and gets the stored plaintext back.
    """
    sunshine_tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    session_id = await mint_live_demo_session(database_engine)
    email, phone = unique_contact()
    seed_lead_id = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        sunshine_tenant_id,
        first_name=unique_marker(),
        email=email,
        phone=phone,
        demo_session_id=None,
    )

    assert (await login_as(db_client, Role.AGENT)).status_code == 200  # Sunshine
    db_client.cookies.set(DEMO_SESSION_COOKIE_NAME, str(session_id))
    response = await db_client.post(
        f"/api/leads/{seed_lead_id}/reveal", json={"field": "email"}
    )

    assert response.status_code == 200
    assert response.json() == {"field": "email", "value": email}


async def test_reveal_foreign_session_row_is_404(seeded, db_client, database_engine):
    """Revealing another session's row → 404, closing the cross-session PII-read gap.

    A row owned by session B is invisible to a caller carrying session A's cookie: the
    foreign-session guard maps it to a `404 "lead not found"`, so one visitor can neither
    reveal nor probe for another's PII (the isolation contract then holds without an
    asterisk, even though foreign ids are never API-exposed).
    """
    sunshine_tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    session_a = await mint_live_demo_session(database_engine)
    session_b = await mint_live_demo_session(database_engine)
    email, phone = unique_contact()
    foreign_lead_id = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        sunshine_tenant_id,
        first_name=unique_marker(),
        email=email,
        phone=phone,
        demo_session_id=session_b,
    )

    assert (await login_as(db_client, Role.AGENT)).status_code == 200  # Sunshine
    db_client.cookies.set(DEMO_SESSION_COOKIE_NAME, str(session_a))
    response = await db_client.post(
        f"/api/leads/{foreign_lead_id}/reveal", json={"field": "email"}
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "lead not found"}
