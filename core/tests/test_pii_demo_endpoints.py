"""End-to-end endpoint tests for the masked write/read demonstrator (Epic 10).

Drives the `pii_demo` router over the real DB-backed client as the actual seeded
personas, proving the "encrypt on write, mask on read" contract end-to-end:

- **Create / get (Phase 1):** an Agent creates a record → 201 with a masked
  `email`, masked `mock_medicare_id`, the constant `****-**-**` date of birth,
  and a **plaintext** `age_band`; getting that id returns the same; an absent id
  is a 404.
- **List (Phase 2):** two created records both come back masked from the list.
- **Isolation + RBAC (Phase 3):** a Sunshine record is invisible to Florida
  (list excludes it, get → 404); create as Read-Only → 403, unauthenticated →
  401, and the tenantless Platform Admin → 403 on create (lacks the capability)
  but → 400 on the authenticated-only list (the inherited no-tenant-context
  guard the create path's capability gate never reaches).
- **Seeded rows (Phase 4):** a seeded demo row lists masked over HTTP.

The write/read path resolves per-tenant keys through `app.pii.keys.session_factory`
— a module-global session **separate** from the request's `get_db`. The shared
`db_session` / `db_client` substrate fixtures (in `conftest.py`) already point
that global at the container key store via `container_keys_session_factory`, so
these tests inherit a reachable key store for free; without it the key load would
hit the unreachable eager default engine.

These reuse `seeded` / `db_client` / `login_as` from `test_endpoints_db.py` and
`conftest.py`. `pytest.ini` sets `asyncio_mode = auto`, so the async tests carry
no `@pytest.mark.asyncio` decorator.
"""

from app.models.user import Role

from tests.test_endpoints_db import login_as, seeded  # noqa: F401

# The create body the happy-path tests reuse. `mock_medicare_id` ends in `1234`
# and `phone` ends in `1234` so the last-4 maskers have a known tail to assert.
SAMPLE_RECORD_BODY = {
    "display_name": "Jane Demo",
    "email": "jane.demo@example.com",
    "date_of_birth": "1950-03-15",
    "phone": "+1 (415) 555-1234",
    "mock_medicare_id": "123-45-1234",
}


async def _create_sample_record(client, body=SAMPLE_RECORD_BODY):
    """POST one record and return the response (trailing slash avoids a redirect)."""
    return await client.post("/api/pii-demo/", json=body)


# --- Phase 1: create + get (the happy path) ----------------------------------


async def test_create_returns_masked_record_for_agent(
    seeded, db_client
):
    """An Agent creates a record → 201 with masked fields and a plaintext age band."""
    assert (await login_as(db_client, Role.AGENT)).status_code == 200

    response = await _create_sample_record(db_client)

    assert response.status_code == 201
    record = response.json()["record"]
    assert set(record) == {
        "id",
        "display_name",
        "email",
        "phone",
        "date_of_birth",
        "age_band",
        "mock_medicare_id",
        "created_at",
    }
    # display_name and age_band are plaintext; everything else is masked.
    assert record["display_name"] == "Jane Demo"
    assert record["email"] == "j***@e***.com"
    assert record["phone"] == "***-***-1234"
    assert record["mock_medicare_id"] == "***-**-1234"
    assert record["date_of_birth"] == "****-**-**"
    assert record["age_band"] == "65+"


async def test_create_without_optional_fields_renders_them_null(
    seeded, db_client
):
    """Omitting `phone` / `mock_medicare_id` renders them as null, not a masked string."""
    assert (await login_as(db_client, Role.AGENT)).status_code == 200

    response = await _create_sample_record(
        db_client,
        body={
            "display_name": "No Optionals",
            "email": "minimal@example.com",
            "date_of_birth": "2000-01-01",
        },
    )

    assert response.status_code == 201
    record = response.json()["record"]
    assert record["phone"] is None
    assert record["mock_medicare_id"] is None
    # Date of birth was supplied, so it masks to the constant (never null here).
    assert record["date_of_birth"] == "****-**-**"
    assert record["age_band"] == "18-34"


async def test_get_returns_the_same_masked_record(
    seeded, db_client
):
    """Getting a just-created id returns the identical masked body."""
    assert (await login_as(db_client, Role.AGENT)).status_code == 200
    created = (await _create_sample_record(db_client)).json()["record"]

    response = await db_client.get(f"/api/pii-demo/{created['id']}")

    assert response.status_code == 200
    assert response.json()["record"] == created


async def test_get_absent_id_is_404(
    seeded, db_client
):
    """A well-formed but absent record id → 404 in this tenant."""
    assert (await login_as(db_client, Role.AGENT)).status_code == 200

    response = await db_client.get(
        "/api/pii-demo/00000000-0000-0000-0000-000000000000"
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "record not found"}


# --- Phase 2: list -----------------------------------------------------------


async def test_list_returns_created_records_masked(
    seeded, db_client
):
    """Two created records both appear in the list, masked."""
    assert (await login_as(db_client, Role.AGENT)).status_code == 200
    first = (await _create_sample_record(db_client)).json()["record"]
    second = (
        await _create_sample_record(
            db_client,
            body={
                "display_name": "Second Person",
                "email": "second@example.org",
                "date_of_birth": "1990-06-01",
            },
        )
    ).json()["record"]

    response = await db_client.get("/api/pii-demo/")

    assert response.status_code == 200
    records = response.json()["records"]
    returned_ids = {record["id"] for record in records}
    assert {first["id"], second["id"]} <= returned_ids
    # The listed bodies are the same masked shape the get endpoint returns.
    listed_first = next(r for r in records if r["id"] == first["id"])
    assert listed_first == first


# --- Phase 3: cross-tenant isolation + negative paths ------------------------


async def test_record_is_invisible_to_another_tenant(
    seeded, db_client
):
    """A record created in one tenant is not listable or gettable by another tenant.

    The Sunshine and Florida Agents are seeded into different tenants. A record an
    Agent creates is created in that Agent's tenant schema; logging in as the
    other tenant's Agent must neither list it nor be able to get it by id.
    """
    # The two seeded Agents belong to the two different demo tenants.
    sunshine_agent_email = "agent.one@sunshine.example"
    florida_agent_email = "agent.one@florida.example"

    # Create as the Sunshine Agent.
    assert (
        await db_client.post(
            "/api/auth/login",
            json={
                "username": sunshine_agent_email,
                "password": "demo-password-change-me",
            },
        )
    ).status_code == 200
    created = (await _create_sample_record(db_client)).json()["record"]

    # Switch to the Florida Agent.
    assert (
        await db_client.post(
            "/api/auth/login",
            json={
                "username": florida_agent_email,
                "password": "demo-password-change-me",
            },
        )
    ).status_code == 200

    list_response = await db_client.get("/api/pii-demo/")
    assert list_response.status_code == 200
    florida_ids = {record["id"] for record in list_response.json()["records"]}
    assert created["id"] not in florida_ids

    get_response = await db_client.get(f"/api/pii-demo/{created['id']}")
    assert get_response.status_code == 404


async def test_create_forbidden_for_read_only(
    seeded, db_client
):
    """A Read-Only user lacks CREATE_EDIT_RECORDS → 403."""
    assert (await login_as(db_client, Role.READ_ONLY)).status_code == 200

    response = await _create_sample_record(db_client)

    assert response.status_code == 403
    assert response.json() == {"detail": "insufficient permissions"}


async def test_create_unauthenticated_is_401(
    seeded, db_client
):
    """A fresh client with no session cookie cannot create → 401."""
    response = await _create_sample_record(db_client)

    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}


async def test_create_forbidden_for_platform_admin(
    seeded, db_client
):
    """The tenantless Platform Admin cannot create → 403 (lacks the capability).

    Create is gated by `require_capability(CREATE_EDIT_RECORDS)`, which the
    Platform Admin role does not hold, so the capability gate rejects them with a
    403 **before** `get_tenant_db` is ever reached. The tenantless 400 path is
    proven on the authenticated-only list endpoint below, where the Platform Admin
    does reach `get_tenant_db`.
    """
    assert (await login_as(db_client, Role.PLATFORM_ADMIN)).status_code == 200

    response = await _create_sample_record(db_client)

    assert response.status_code == 403
    assert response.json() == {"detail": "insufficient permissions"}


async def test_list_tenantless_platform_admin_is_400(
    seeded, db_client
):
    """The tenantless Platform Admin listing records has no tenant context → 400.

    List is authenticated-only (no capability gate), so the Platform Admin reaches
    `get_tenant_db`, which rejects a caller whose `tenant_id` is `None` with a 400.
    This is the inherited tenantless guard the create path never reaches.
    """
    assert (await login_as(db_client, Role.PLATFORM_ADMIN)).status_code == 200

    response = await db_client.get("/api/pii-demo/")

    assert response.status_code == 400
    assert response.json() == {"detail": "no tenant context"}


# --- Phase 4: a seeded demo row lists masked over HTTP -----------------------


async def test_seeded_rows_list_masked_over_http(
    seeded, db_client
):
    """The seeded Sunshine demo rows list masked, including one with a Medicare id.

    The seed inserts 2 demo rows per tenant. The Sunshine Agent listing their
    tenant should see at least those 2, each with a masked (or null) email and at
    least one row carrying a masked `mock_medicare_id`.
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

    response = await db_client.get("/api/pii-demo/")

    assert response.status_code == 200
    records = response.json()["records"]
    assert len(records) >= 2
    # Every listed email is masked (contains the masking marker, not a raw '@').
    for record in records:
        assert "***" in record["email"]
    # At least one seeded Sunshine row carries a masked Medicare id.
    assert any(record["mock_medicare_id"] is not None for record in records)
