"""Endpoint tests for the guarded reveal route (Epic 12).

Drives `POST /api/pii-demo/{record_id}/reveal` over the real DB-backed client as
the actual seeded personas, proving the audited click-to-reveal contract — the
only place plaintext PII crosses the API boundary:

- **Reveal a revealable field (Phase 1):** an Agent reveals `email` → 200 with the
  real, unmasked value (not the `j***@e***.com` masked form); an absent record id
  → 404.
- **Refusals, RBAC, and the remaining fields (Phase 2):** `phone` and
  `date_of_birth` reveal happy paths (unmasked); `mock_medicare_id` → 422 with the
  distinct never-revealable message; an unknown field (`display_name`) → 422 with
  the generic not-revealable message; a Read-Only caller → 403; the Platform Admin
  → 403; an unauthenticated caller → 401; and the reveal seam is awaited — a
  monkeypatched `AsyncMock` over the router-bound `on_pii_revealed` is asserted
  awaited once with `entity_type="pii_demo"`, `entity_id=<created id>`,
  `field_name="email"`.

Like the Epic 10/11 endpoint tests, the reveal path resolves per-tenant keys (to
decrypt the field) through `app.pii.keys.session_factory` — the module-global the
shared `db_client` substrate fixture points at the container key store via
`container_keys_session_factory` — so these tests inherit a reachable key store
for free. These reuse `seeded` / `db_client` / `login_as` from
`test_endpoints_db.py` and `conftest.py`, the same imports Epic 10/11 use.
`pytest.ini` sets `asyncio_mode = auto`, so the async tests carry no
`@pytest.mark.asyncio` decorator.
"""

import uuid
from unittest.mock import AsyncMock

from app.models.user import Role
from app.pii_demo import router as pii_demo_router

from tests.test_endpoints_db import login_as, seeded  # noqa: F401

# The create body the reveal tests reuse. The plaintext values here are exactly
# what a successful reveal must return — unmasked — so the assertions can compare
# against the known input rather than a masked display string.
SAMPLE_RECORD_BODY = {
    "display_name": "Reveal Target",
    "email": "reveal.target@example.com",
    "date_of_birth": "1950-03-15",
    "phone": "+1 (415) 555-1234",
    "mock_medicare_id": "123-45-1234",
}


async def _create_sample_record(client, body=SAMPLE_RECORD_BODY):
    """Create one record as the logged-in caller; return its masked body."""
    response = await client.post("/api/pii-demo/", json=body)
    assert response.status_code == 201
    return response.json()["record"]


# --- Phase 1: reveal a revealable field (the happy path) ---------------------


async def test_reveal_email_returns_unmasked_value_for_agent(seeded, db_client):
    """An Agent revealing `email` → 200 with the real, unmasked address.

    The created record's `email` comes back masked (`r***@e***.com`); revealing it
    must return the stored plaintext (`reveal.target@example.com`), proving the
    field is decrypted and the unmasked value crosses the boundary on this path.
    """
    assert (await login_as(db_client, Role.AGENT)).status_code == 200
    created = await _create_sample_record(db_client)

    response = await db_client.post(
        f"/api/pii-demo/{created['id']}/reveal",
        json={"field": "email"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "field": "email",
        "value": "reveal.target@example.com",
    }


async def test_reveal_absent_id_is_404(seeded, db_client):
    """A revealable field on a well-formed but absent record id → 404."""
    assert (await login_as(db_client, Role.AGENT)).status_code == 200

    response = await db_client.post(
        "/api/pii-demo/00000000-0000-0000-0000-000000000000/reveal",
        json={"field": "email"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "record not found"}


# --- Phase 2: refusals, RBAC, and the remaining fields -----------------------


async def test_reveal_phone_returns_unmasked_value(seeded, db_client):
    """Revealing `phone` returns the stored plaintext number, unmasked."""
    assert (await login_as(db_client, Role.AGENT)).status_code == 200
    created = await _create_sample_record(db_client)

    response = await db_client.post(
        f"/api/pii-demo/{created['id']}/reveal",
        json={"field": "phone"},
    )

    assert response.status_code == 200
    assert response.json() == {"field": "phone", "value": "+1 (415) 555-1234"}


async def test_reveal_date_of_birth_returns_unmasked_value(seeded, db_client):
    """Revealing `date_of_birth` returns the stored ISO date, unmasked.

    The masked read renders date of birth as the constant `****-**-**`; the reveal
    path returns the actual stored ISO string (the value encrypted on create).
    """
    assert (await login_as(db_client, Role.AGENT)).status_code == 200
    created = await _create_sample_record(db_client)

    response = await db_client.post(
        f"/api/pii-demo/{created['id']}/reveal",
        json={"field": "date_of_birth"},
    )

    assert response.status_code == 200
    assert response.json() == {"field": "date_of_birth", "value": "1950-03-15"}


async def test_reveal_null_optional_field_returns_null(seeded, db_client):
    """Revealing an absent optional field (`phone`) returns `value: null`, 200.

    A record created without a phone has no `phone_encrypted` blob; revealing
    `phone` returns `{field, value: null}` with a 200 (the uniform call site,
    matching the masked read's null rendering of absent optionals) — not a 404 or
    a 422.
    """
    assert (await login_as(db_client, Role.AGENT)).status_code == 200
    created = await _create_sample_record(
        db_client,
        body={
            "display_name": "No Phone",
            "email": "no.phone@example.com",
            "date_of_birth": "2000-01-01",
        },
    )

    response = await db_client.post(
        f"/api/pii-demo/{created['id']}/reveal",
        json={"field": "phone"},
    )

    assert response.status_code == 200
    assert response.json() == {"field": "phone", "value": None}


async def test_reveal_mock_medicare_id_is_never_revealable_422(seeded, db_client):
    """Revealing `mock_medicare_id` → 422 with the distinct never-revealable message."""
    assert (await login_as(db_client, Role.AGENT)).status_code == 200
    created = await _create_sample_record(db_client)

    response = await db_client.post(
        f"/api/pii-demo/{created['id']}/reveal",
        json={"field": "mock_medicare_id"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "field is never revealable"}


async def test_reveal_unknown_field_is_not_revealable_422(seeded, db_client):
    """Revealing an unknown field (`display_name`) → 422 with the generic message."""
    assert (await login_as(db_client, Role.AGENT)).status_code == 200
    created = await _create_sample_record(db_client)

    response = await db_client.post(
        f"/api/pii-demo/{created['id']}/reveal",
        json={"field": "display_name"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "field is not revealable"}


async def test_reveal_never_revealable_field_is_422_even_for_absent_id(
    seeded, db_client
):
    """The field is validated before the DB read: `mock_medicare_id` → 422 for an
    absent id (the refusal is about the field, not the record)."""
    assert (await login_as(db_client, Role.AGENT)).status_code == 200

    response = await db_client.post(
        "/api/pii-demo/00000000-0000-0000-0000-000000000000/reveal",
        json={"field": "mock_medicare_id"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "field is never revealable"}


async def test_reveal_forbidden_for_read_only(seeded, db_client):
    """A Read-Only user lacks REVEAL_PII → 403."""
    assert (await login_as(db_client, Role.READ_ONLY)).status_code == 200

    response = await db_client.post(
        f"/api/pii-demo/{uuid.uuid4()}/reveal",
        json={"field": "email"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "insufficient permissions"}


async def test_reveal_forbidden_for_platform_admin(seeded, db_client):
    """The tenantless Platform Admin lacks REVEAL_PII → 403 (the capability gate
    fires before `get_tenant_db`, so this is a 403, not the tenantless 400)."""
    assert (await login_as(db_client, Role.PLATFORM_ADMIN)).status_code == 200

    response = await db_client.post(
        f"/api/pii-demo/{uuid.uuid4()}/reveal",
        json={"field": "email"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "insufficient permissions"}


async def test_reveal_unauthenticated_is_401(seeded, db_client):
    """A fresh client with no session cookie cannot reveal → 401."""
    response = await db_client.post(
        f"/api/pii-demo/{uuid.uuid4()}/reveal",
        json={"field": "email"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}


async def test_reveal_awaits_the_seam_with_the_expected_arguments(
    seeded, db_client, monkeypatch
):
    """A successful reveal awaits `on_pii_revealed` once with the right arguments.

    Monkeypatches the router-bound `on_pii_revealed` with an `AsyncMock` so the
    seam stays a no-op but records its call. A successful `email` reveal must await
    it exactly once with `entity_type="pii_demo"`, `entity_id=<the created id>`,
    `field_name="email"`, and the caller's `Identity` — proving P1.4 (audit) and
    P1.5 (event) will land on a real, correctly-shaped call site.
    """
    assert (await login_as(db_client, Role.AGENT)).status_code == 200
    created = await _create_sample_record(db_client)

    seam_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(pii_demo_router, "on_pii_revealed", seam_mock)

    response = await db_client.post(
        f"/api/pii-demo/{created['id']}/reveal",
        json={"field": "email"},
    )

    assert response.status_code == 200
    seam_mock.assert_awaited_once()
    call_arguments = seam_mock.await_args
    # Identity is the first positional argument; the rest are entity_type,
    # entity_id, field_name (positional in the handler's call).
    _identity, entity_type, entity_id, field_name = call_arguments.args
    assert entity_type == "pii_demo"
    assert entity_id == uuid.UUID(created["id"])
    assert field_name == "email"
