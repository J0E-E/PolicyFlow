"""DB-backed proof of the authenticated lead reads (Epic 11, P1.7).

Epic 7 stood up the agent `POST /api/leads` create slice; Epic 11 adds the two
authenticated, tenant-scoped, masked reads that the queue and detail UIs lean on:

- `GET /api/leads/{lead_id}` — one lead by id, masked. A missing id and a
  cross-tenant id both yield `404 "lead not found"` (schema scoping covers the
  cross-tenant case — another tenant's row is physically out of reach).
- `GET /api/leads` — the caller's tenant leads, masked, newest first
  (`created_at` DESC, tie-broken by `id`), capped at `LEAD_LIST_LIMIT`. The optional
  `unassigned=true` query param restricts to the unclaimed queue: unowned **and**
  still `New`. Tenant A's list never contains tenant B's leads.

These drive the real endpoints over the DB-backed client (the same `seeded` /
`db_client` / `database_engine` substrate the other endpoint tests use), logging in
as the seeded Sunshine and Florida Agents. Leads the create endpoint cannot itself
produce (a `New`/unowned queue lead, an unowned-but-`Rejected` lead, an owned
`Working` lead with a controlled `created_at`) are inserted directly into the
tenant schema through the **normal encryption path** (each PII field encrypted with
`encrypt_field`, each blind index over the normalized value) via the SELECT/INSERT-
capable superuser `database_engine` connection, schema-qualified — exactly the seed
and Epic 6 matcher-test insert pattern. The schema identifier comes **only** from the
registry (never user input); every value is a bound parameter.

The container database is **session-scoped and shared**, so other tests' (and the
seed's) leads accumulate in it. Every test here tags its own leads with a unique
marker (`first_name`) and filters the list response down to just its own rows before
asserting order / membership, so an accumulating shared table can never make these
flaky. `pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no
`@pytest.mark.asyncio` decorator. The `seeded` / `db_client` / `database_engine`
fixtures and the `login_as` helper are reused by name from `test_endpoints_db.py`
and `conftest.py`.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from app.config import settings
from app.leads.state import LeadStatus
from app.models.tenant import Tenant
from app.models.user import Role
from app.pii.crypto import normalize_email, normalize_phone
from app.pii.service import compute_blind_index, encrypt_field
from app.seed import demo_user_specs
from app.tenancy.registry import FLORIDA, SUNSHINE

from tests.test_endpoints_db import login_as, seeded  # noqa: F401

# A fixed base time so the explicit `created_at` values the ordering test sets are
# deterministic and unrelated to wall-clock or `now()`.
BASE_CREATED_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def login_payload_for(slug: str, role: Role) -> dict:
    """Return the login body for the seeded persona of `role` in tenant `slug`.

    `login_as` always logs in the *first* persona for a role (a Sunshine one for
    `Role.AGENT`), so the cross-tenant tests need a way to log in as a *specific*
    tenant's agent. This finds that persona's email/username from the seed spec by
    matching both role and tenant slug.
    """
    email = next(
        spec_email
        for spec_email, spec_role, spec_slug in demo_user_specs()
        if spec_role is role and spec_slug == slug
    )
    return {"username": email, "password": settings.seed_user_password}


async def login_agent_for_slug(client, slug: str):
    """Log in as tenant `slug`'s seeded Agent; return the login response."""
    return await client.post("/api/auth/login", json=login_payload_for(slug, Role.AGENT))


async def tenant_id_for_slug(database_engine, slug: str) -> uuid.UUID:
    """Return the seeded runtime tenant id for `slug` (its per-tenant keys' owner)."""
    async with database_engine.connect() as connection:
        return (
            await connection.execute(
                select(Tenant.id).where(Tenant.slug == slug)
            )
        ).scalar_one()


def unique_marker() -> str:
    """Return a short token unique to one test, used to tag and find its own leads.

    The container DB is shared, so each test stamps its leads with this marker (in
    `first_name`) and filters the list response down to just its own rows — no other
    test's (or the seed's) leads can carry the same marker.
    """
    return uuid.uuid4().hex[:12]


async def insert_lead(
    database_engine,
    schema_name: str,
    tenant_id: uuid.UUID,
    *,
    first_name: str,
    email: str,
    phone: str,
    status: LeadStatus = LeadStatus.NEW,
    owner_user_id: uuid.UUID | None = None,
    owner_username: str | None = None,
    product_lines_of_interest: list[str] | None = None,
    created_at: datetime = BASE_CREATED_AT,
) -> uuid.UUID:
    """Insert one lead into `<schema_name>.leads` via the normal encryption path.

    The controllable setup seam: it sets `status`, `owner_user_id`, and `created_at`
    directly — combinations the create endpoint cannot produce (a `New`/unowned queue
    lead, an unowned `Rejected` lead, an explicitly-timestamped row for deterministic
    ordering). The PII fields are encrypted with `encrypt_field` and each blind index
    is computed over the normalized value, exactly the seed / Epic 6 insert path, so a
    masked read decrypts it cleanly. The schema name comes only from the registry;
    every value is a bound parameter. Returns the new lead's id.
    """
    lead_id = uuid.uuid4()
    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                f"INSERT INTO {schema_name}.leads "
                "(id, first_name, last_name, email_encrypted, email_blind_index, "
                "phone_encrypted, phone_blind_index, date_of_birth_encrypted, "
                "age_band, zip_code, product_lines_of_interest, lead_source, status, "
                "owner_user_id, owner_username, correlation_id, created_at, "
                "updated_at) "
                "VALUES (:id, :first_name, :last_name, :email_encrypted, "
                ":email_blind_index, :phone_encrypted, :phone_blind_index, "
                ":date_of_birth_encrypted, :age_band, :zip_code, "
                ":product_lines_of_interest, :lead_source, :status, :owner_user_id, "
                ":owner_username, :correlation_id, :created_at, :updated_at)"
            ),
            {
                "id": lead_id,
                "first_name": first_name,
                "last_name": "Reader",
                "email_encrypted": await encrypt_field(tenant_id, email),
                "email_blind_index": await compute_blind_index(
                    tenant_id, normalize_email(email)
                ),
                "phone_encrypted": await encrypt_field(tenant_id, phone),
                "phone_blind_index": await compute_blind_index(
                    tenant_id, normalize_phone(phone)
                ),
                "date_of_birth_encrypted": await encrypt_field(
                    tenant_id, "1960-03-15"
                ),
                "age_band": "50-64",
                "zip_code": "33101",
                "product_lines_of_interest": product_lines_of_interest or [],
                "lead_source": "agent_entered",
                "status": status.value,
                "owner_user_id": owner_user_id,
                "owner_username": owner_username,
                "correlation_id": uuid.uuid4(),
                "created_at": created_at,
                "updated_at": created_at,
            },
        )
    return lead_id


def unique_contact() -> tuple[str, str]:
    """Return a (email, phone) pair unique to one test, avoiding cross-test matches.

    The container DB is shared, so each inserted lead owns unique contact details so
    the create endpoint's duplicate matcher never flags an unrelated test's row.
    """
    token = uuid.uuid4().hex[:12]
    return (f"read-{token}@example.com", f"+1 (415) 555-{token[:4]}")


# --- Phase 1: detail read ----------------------------------------------------


async def test_detail_returns_masked_lead(seeded, db_client):
    """`GET /api/leads/{id}` returns the single masked read shape for the caller's lead.

    A Sunshine Agent creates a lead, then reads it back by id: the detail body is the
    same masked shape the create returns — plaintext names / `age_band` / `zip_code` /
    product-line keys / `lead_source` / `status`, a masked `email` / `phone`, the
    constant `****-**-**` date of birth, `***` for the present street address — and the
    internal trace / matching columns never appear.
    """
    assert (await login_as(db_client, Role.AGENT)).status_code == 200

    email, phone = unique_contact()
    create_response = await db_client.post(
        "/api/leads",
        json={
            "first_name": "Detail",
            "last_name": "Demo",
            "email": email,
            "phone": phone,
            "date_of_birth": "1950-03-15",
            "zip_code": "33101",
            "product_lines_of_interest": ["medicare_advantage"],
            "street_address": "100 Demo Street",
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()["lead"]

    response = await db_client.get(f"/api/leads/{created['id']}")

    assert response.status_code == 200
    lead = response.json()["lead"]
    # The detail body is the create body verbatim — one shared masked builder.
    assert lead == created
    assert lead["first_name"] == "Detail"
    assert lead["email"].endswith("@e***.com")
    assert lead["phone"].startswith("***-***-")
    assert lead["date_of_birth"] == "****-**-**"
    assert lead["street_address"] == "***"
    assert lead["status"] == "Working"
    # The masked read never leaks the internal trace / matching columns.
    assert "correlation_id" not in lead
    assert "email_blind_index" not in lead
    assert "demo_session_id" not in lead


async def test_detail_missing_id_is_404(seeded, db_client):
    """A lead id that exists nowhere → 404 `"lead not found"`."""
    assert (await login_as(db_client, Role.AGENT)).status_code == 200

    response = await db_client.get(f"/api/leads/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "lead not found"}


async def test_detail_cross_tenant_id_is_404(seeded, db_client, database_engine):
    """A lead id belonging to *another* tenant → 404, indistinguishable from missing.

    A lead is inserted into Florida's schema; a logged-in Sunshine Agent requesting it
    by id gets a 404 — `get_tenant_db` scopes the lookup to Sunshine's schema, so
    Florida's row is physically out of reach and a caller can neither read nor probe
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
    response = await db_client.get(f"/api/leads/{florida_lead_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": "lead not found"}


# --- Phase 2: list read ------------------------------------------------------


async def test_list_returns_tenant_leads_masked_newest_first(
    seeded, db_client, database_engine
):
    """`GET /api/leads` returns the caller's leads masked, newest first.

    Three leads are inserted with strictly increasing `created_at` and a shared unique
    marker. The list is filtered down to just those three and asserted to come back in
    newest-first order (`created_at` DESC), each in the masked read shape (a masked
    `email`, the constant masked date of birth) — never raw PII.
    """
    sunshine_tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    marker = unique_marker()

    inserted_ids_oldest_first = []
    for offset_days in range(3):
        email, phone = unique_contact()
        inserted_ids_oldest_first.append(
            await insert_lead(
                database_engine,
                SUNSHINE.schema_name,
                sunshine_tenant_id,
                first_name=marker,
                email=email,
                phone=phone,
                created_at=BASE_CREATED_AT + timedelta(days=offset_days),
            )
        )

    assert (await login_as(db_client, Role.AGENT)).status_code == 200
    response = await db_client.get("/api/leads")
    assert response.status_code == 200

    leads = response.json()["leads"]
    mine = [lead for lead in leads if lead["first_name"] == marker]
    assert len(mine) == 3

    # Newest first: the reverse of insertion order (the last-inserted is first).
    assert [lead["id"] for lead in mine] == [
        str(lead_id) for lead_id in reversed(inserted_ids_oldest_first)
    ]
    # Each row is the masked read shape — never raw PII.
    for lead in mine:
        assert lead["email"].endswith(".com") and "***" in lead["email"]
        assert lead["date_of_birth"] == "****-**-**"


async def test_unassigned_filter_returns_only_unowned_new_leads(
    seeded, db_client, database_engine
):
    """`unassigned=true` returns only unowned **and** `New` leads (proving the AND).

    Three leads share one marker: a queue lead (unowned, `New`), an owned `Working`
    lead, and an unowned `Rejected` lead. The unfiltered list shows all three; the
    `unassigned=true` list shows only the queue lead — the owned-`Working` lead is
    excluded by the owner clause and the unowned-`Rejected` lead by the status clause,
    so each clause of the AND is independently proven.
    """
    sunshine_tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    marker = unique_marker()

    queue_email, queue_phone = unique_contact()
    queue_lead_id = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        sunshine_tenant_id,
        first_name=marker,
        email=queue_email,
        phone=queue_phone,
        status=LeadStatus.NEW,
        owner_user_id=None,
    )

    owned_email, owned_phone = unique_contact()
    owned_working_lead_id = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        sunshine_tenant_id,
        first_name=marker,
        email=owned_email,
        phone=owned_phone,
        status=LeadStatus.WORKING,
        owner_user_id=uuid.uuid4(),
        owner_username="someone@sunshine.example",
    )

    rejected_email, rejected_phone = unique_contact()
    unowned_rejected_lead_id = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        sunshine_tenant_id,
        first_name=marker,
        email=rejected_email,
        phone=rejected_phone,
        status=LeadStatus.REJECTED,
        owner_user_id=None,
    )

    assert (await login_as(db_client, Role.AGENT)).status_code == 200

    # Default (no filter): all three of this test's leads are present.
    all_response = await db_client.get("/api/leads")
    assert all_response.status_code == 200
    all_mine = {
        lead["id"]
        for lead in all_response.json()["leads"]
        if lead["first_name"] == marker
    }
    assert all_mine == {
        str(queue_lead_id),
        str(owned_working_lead_id),
        str(unowned_rejected_lead_id),
    }

    # unassigned=true: only the unowned-`New` queue lead survives the AND.
    queue_response = await db_client.get("/api/leads", params={"unassigned": "true"})
    assert queue_response.status_code == 200
    queue_mine = {
        lead["id"]
        for lead in queue_response.json()["leads"]
        if lead["first_name"] == marker
    }
    assert queue_mine == {str(queue_lead_id)}


async def test_list_excludes_other_tenant_leads(
    seeded, db_client, database_engine
):
    """Tenant A's list never contains tenant B's leads (schema isolation).

    A Sunshine lead and a Florida lead share one marker. A Sunshine Agent's list shows
    the Sunshine lead and not the Florida one; logging in as a Florida Agent and
    listing shows the Florida lead and not the Sunshine one — neither tenant's reads
    can reach the other's schema.
    """
    sunshine_tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    florida_tenant_id = await tenant_id_for_slug(database_engine, FLORIDA.slug)
    marker = unique_marker()

    sunshine_email, sunshine_phone = unique_contact()
    sunshine_lead_id = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        sunshine_tenant_id,
        first_name=marker,
        email=sunshine_email,
        phone=sunshine_phone,
    )

    florida_email, florida_phone = unique_contact()
    florida_lead_id = await insert_lead(
        database_engine,
        FLORIDA.schema_name,
        florida_tenant_id,
        first_name=marker,
        email=florida_email,
        phone=florida_phone,
    )

    # Sunshine Agent: sees the Sunshine lead, never the Florida one.
    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    sunshine_response = await db_client.get("/api/leads")
    assert sunshine_response.status_code == 200
    sunshine_ids = {lead["id"] for lead in sunshine_response.json()["leads"]}
    assert str(sunshine_lead_id) in sunshine_ids
    assert str(florida_lead_id) not in sunshine_ids

    # Florida Agent: sees the Florida lead, never the Sunshine one.
    await db_client.post("/api/auth/logout")
    assert (await login_agent_for_slug(db_client, FLORIDA.slug)).status_code == 200
    florida_response = await db_client.get("/api/leads")
    assert florida_response.status_code == 200
    florida_ids = {lead["id"] for lead in florida_response.json()["leads"]}
    assert str(florida_lead_id) in florida_ids
    assert str(sunshine_lead_id) not in florida_ids
