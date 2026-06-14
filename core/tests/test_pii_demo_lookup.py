"""Endpoint tests for the blind-index lookup route (Epic 11).

Drives `POST /api/pii-demo/lookup` over the real DB-backed client as the actual
seeded personas, proving exact-match duplicate detection **without decryption**
(Risk #3 at the API layer):

- **Email lookup (Phase 1):** a record created with one email is found by a
  mixed-case / whitespace variant of that email — proving the value is normalized
  and matched by blind-index equality, not decrypted — and returned masked under
  `{"matches": […]}`; a non-matching email returns `{"matches": []}` with a 200,
  not a 404.
- **Phone branch + exactly-one validation (Phase 2):** a phone lookup finds the
  matching record (masked); a body with neither field → 422; a body with both
  fields → 422.
- **Isolation + auth negatives (Phase 3):** a value that matches in one tenant
  returns `{"matches": []}` for another tenant (the equality query is scoped to
  the caller's own schema); an unauthenticated caller → 401; the tenantless
  Platform Admin → 400 (no tenant context).

The lookup path resolves per-tenant keys (for the blind index) through
`app.pii.keys.session_factory` — the same module-global the shared `db_client`
substrate fixture points at the container key store via
`container_keys_session_factory` — so these tests inherit a reachable key store
for free. These reuse `seeded` / `db_client` / `login_as` from
`test_endpoints_db.py` and `conftest.py`. `pytest.ini` sets
`asyncio_mode = auto`, so the async tests carry no `@pytest.mark.asyncio`
decorator.
"""

from app.models.user import Role

from tests.test_endpoints_db import login_as, seeded  # noqa: F401

# A record the lookup tests create to own their own match target, independent of
# the shared/session-scoped seeded rows. The phone is written in a punctuated,
# E.164-ish style so the normalized lookup value can differ in formatting.
LOOKUPABLE_RECORD_BODY = {
    "display_name": "Lookup Target",
    "email": "Lookup.Target@Example.com",
    "date_of_birth": "1950-03-15",
    "phone": "+1 (415) 555-1234",
}


async def _create_lookupable_record(client):
    """Create the lookup-target record as the logged-in caller; return its body."""
    response = await client.post("/api/pii-demo/", json=LOOKUPABLE_RECORD_BODY)
    assert response.status_code == 201
    return response.json()["record"]


# --- Phase 1: email lookup happy path (the Risk #3 proof) --------------------


async def test_email_lookup_matches_despite_case_and_whitespace(seeded, db_client):
    """A mixed-case / whitespace email variant finds the record by blind index.

    The record is stored with `Lookup.Target@Example.com`; looking up the same
    address with different case and surrounding whitespace must still match,
    proving the value is normalized and matched on the blind index without any
    decryption. The match is returned masked.
    """
    assert (await login_as(db_client, Role.AGENT)).status_code == 200
    created = await _create_lookupable_record(db_client)

    response = await db_client.post(
        "/api/pii-demo/lookup",
        json={"email": "  LOOKUP.TARGET@example.COM  "},
    )

    assert response.status_code == 200
    matches = response.json()["matches"]
    matched_ids = {match["id"] for match in matches}
    assert created["id"] in matched_ids
    # The match is the same masked shape the get endpoint returns; masking keeps
    # the first char of the local part and domain as stored (`Lookup.Target@...`).
    matched_record = next(match for match in matches if match["id"] == created["id"])
    assert matched_record == created
    assert matched_record["email"] == "L***@E***.com"


async def test_email_lookup_miss_returns_empty_list_not_404(seeded, db_client):
    """An email that matches nothing returns `{"matches": []}` with a 200."""
    assert (await login_as(db_client, Role.AGENT)).status_code == 200

    response = await db_client.post(
        "/api/pii-demo/lookup",
        json={"email": "nobody-matches-this@example.com"},
    )

    assert response.status_code == 200
    assert response.json() == {"matches": []}


# --- Phase 2: phone branch + exactly-one validation --------------------------


async def test_phone_lookup_matches_record(seeded, db_client):
    """A phone lookup finds the matching record by blind index, masked.

    The record is stored with `+1 (415) 555-1234`; looking up the same number in a
    plain-digits style normalizes to the same fingerprint and matches.
    """
    assert (await login_as(db_client, Role.AGENT)).status_code == 200
    created = await _create_lookupable_record(db_client)

    response = await db_client.post(
        "/api/pii-demo/lookup",
        json={"phone": "14155551234"},
    )

    assert response.status_code == 200
    matches = response.json()["matches"]
    matched_ids = {match["id"] for match in matches}
    assert created["id"] in matched_ids
    matched_record = next(match for match in matches if match["id"] == created["id"])
    assert matched_record["phone"] == "***-***-1234"


async def test_lookup_with_neither_field_is_422(seeded, db_client):
    """An empty body supplies neither field → 422 (nothing to look up)."""
    assert (await login_as(db_client, Role.AGENT)).status_code == 200

    response = await db_client.post("/api/pii-demo/lookup", json={})

    assert response.status_code == 422


async def test_lookup_with_both_fields_is_422(seeded, db_client):
    """A body with both fields is ambiguous → 422."""
    assert (await login_as(db_client, Role.AGENT)).status_code == 200

    response = await db_client.post(
        "/api/pii-demo/lookup",
        json={"email": "a@example.com", "phone": "14155551234"},
    )

    assert response.status_code == 422


# --- Phase 3: isolation + auth negatives -------------------------------------


async def test_lookup_does_not_cross_tenant_boundary(seeded, db_client):
    """A value created in one tenant returns `{"matches": []}` for another tenant.

    A record is created as the Sunshine Agent; looking up that exact email as the
    Florida Agent must find nothing, because the equality query is scoped to the
    caller's own schema (and the blind index uses a per-tenant key). The two
    seeded Agents belong to the two different demo tenants.
    """
    assert (
        await db_client.post(
            "/api/auth/login",
            json={
                "username": "agent.one@sunshine.example",
                "password": "demo-password-change-me",
            },
        )
    ).status_code == 200
    await _create_lookupable_record(db_client)

    assert (
        await db_client.post(
            "/api/auth/login",
            json={
                "username": "agent.one@florida.example",
                "password": "demo-password-change-me",
            },
        )
    ).status_code == 200

    response = await db_client.post(
        "/api/pii-demo/lookup",
        json={"email": LOOKUPABLE_RECORD_BODY["email"]},
    )

    assert response.status_code == 200
    assert response.json() == {"matches": []}


async def test_lookup_unauthenticated_is_401(seeded, db_client):
    """A fresh client with no session cookie cannot look up → 401."""
    response = await db_client.post(
        "/api/pii-demo/lookup",
        json={"email": "anyone@example.com"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}


async def test_lookup_tenantless_platform_admin_is_400(seeded, db_client):
    """The tenantless Platform Admin has no tenant context → 400.

    Lookup is authenticated-only (no capability gate), so the Platform Admin
    reaches `get_tenant_db`, which rejects a caller whose `tenant_id` is `None`
    with a 400 — the inherited no-tenant-context guard.
    """
    assert (await login_as(db_client, Role.PLATFORM_ADMIN)).status_code == 200

    response = await db_client.post(
        "/api/pii-demo/lookup",
        json={"email": "anyone@example.com"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "no tenant context"}
