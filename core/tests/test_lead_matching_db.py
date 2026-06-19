"""DB-backed proof for the duplicate matcher (`app.leads.matching`) — Epic 6.

These run against the real Postgres booted in Docker (the same `database_engine`
substrate as the other DB tests), and they are the acceptance proof for the
matcher: real leads inserted through the **normal encryption path** (each PII field
encrypted with `encrypt_field`, each blind index computed over the normalized value
with `compute_blind_index`), then `find_duplicate_lead` run against them, asserting
every locked semantic end-to-end:

- **OR** — an email-only match and a phone-only match each flag.
- **Oldest wins** — two matching priors return the earlier-`created_at` one.
- **Self-exclusion** — passing the new lead's id as `exclude_lead_id` omits that row.
- **Rejected excluded** — a `Rejected` prior is never the match.
- **Tenant isolation** — tenant A's value never matches when the query runs in
  tenant B's schema.
- **No decryption** — `decrypt_field` is patched to fail if ever called; the match
  still succeeds, proving the whole path matches on the blind index alone.

The leads are inserted with raw, schema-qualified `INSERT`s exactly like the seed's
`pii_demo` insert (the schema identifier comes **only** from the registry, never
user input; every value is a bound parameter). The matcher itself reads through the
schema-less `Lead` model, which resolves against the active `search_path`, so each
test points the session's `search_path` at the tenant under test before calling it
— the same scoping the per-request dependency does in production.

The container database is **session-scoped and shared**, so each test inserts leads
carrying its own unique, randomly-suffixed email/phone, so a test's match targets
can never collide with another test's (or the seed's) rows. `pytest.ini` sets
`asyncio_mode = auto`, so the async tests carry no `@pytest.mark.asyncio` decorator.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from app.leads.matching import find_duplicate_lead
from app.leads.state import LeadStatus
from app.models.tenant import Tenant
from app.pii import service as pii_service_module
from app.pii.crypto import normalize_email, normalize_phone
from app.pii.service import compute_blind_index, encrypt_field
from app.tenancy.registry import FLORIDA, SUNSHINE

from tests.test_endpoints_db import seeded  # noqa: F401

# A fixed base time so the explicit `created_at` values the oldest-wins test sets
# are deterministic and unrelated to wall-clock or `now()`.
BASE_CREATED_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


async def _tenant_id_for_slug(db_session, slug: str) -> uuid.UUID:
    """Return the seeded runtime tenant id for `slug` (its per-tenant keys' owner)."""
    return (
        await db_session.execute(select(Tenant.id).where(Tenant.slug == slug))
    ).scalar_one()


async def _insert_lead(
    db_session,
    schema_name: str,
    tenant_id: uuid.UUID,
    *,
    email: str,
    phone: str,
    status: LeadStatus = LeadStatus.NEW,
    created_at: datetime = BASE_CREATED_AT,
) -> uuid.UUID:
    """Insert one lead into `<schema_name>.leads` via the normal encryption path.

    Encrypts the email/phone with `encrypt_field` and computes each blind index
    over the normalized value with `compute_blind_index` — exactly the seed's
    insert path — so the row matches on the same fingerprint the matcher computes.
    The schema name comes only from the registry; every value is a bound parameter.
    Returns the new lead's id so a test can pass it as `exclude_lead_id`.
    """
    lead_id = uuid.uuid4()
    await db_session.execute(
        text(
            f"INSERT INTO {schema_name}.leads "
            "(id, first_name, last_name, email_encrypted, email_blind_index, "
            "phone_encrypted, phone_blind_index, date_of_birth_encrypted, "
            "age_band, zip_code, product_lines_of_interest, lead_source, status, "
            "correlation_id, created_at, updated_at) "
            "VALUES (:id, :first_name, :last_name, :email_encrypted, "
            ":email_blind_index, :phone_encrypted, :phone_blind_index, "
            ":date_of_birth_encrypted, :age_band, :zip_code, "
            ":product_lines_of_interest, :lead_source, :status, :correlation_id, "
            ":created_at, :updated_at)"
        ),
        {
            "id": lead_id,
            "first_name": "Jane",
            "last_name": "Doe",
            "email_encrypted": await encrypt_field(tenant_id, email),
            "email_blind_index": await compute_blind_index(
                tenant_id, normalize_email(email)
            ),
            "phone_encrypted": await encrypt_field(tenant_id, phone),
            "phone_blind_index": await compute_blind_index(
                tenant_id, normalize_phone(phone)
            ),
            "date_of_birth_encrypted": await encrypt_field(tenant_id, "1960-03-15"),
            "age_band": "50-64",
            "zip_code": "33101",
            "product_lines_of_interest": [],
            "lead_source": "agent_entered",
            "status": status.value,
            "correlation_id": uuid.uuid4(),
            "created_at": created_at,
            "updated_at": created_at,
        },
    )
    return lead_id


async def _scope_session_to_schema(db_session, schema_name: str) -> None:
    """Point the session's `search_path` at `schema_name` so `Lead` resolves there.

    The schema-less `Lead` model the matcher queries resolves against the active
    `search_path`, so a test must set it before calling `find_duplicate_lead` — the
    same scoping the per-request dependency does in production. The schema name comes
    only from the registry.
    """
    await db_session.execute(text(f"SET search_path TO {schema_name}"))


def _unique_contact() -> tuple[str, str]:
    """Return a (email, phone) pair unique to one test, to avoid cross-test matches.

    The container database is shared across the session, so each test owns its match
    targets by suffixing both fields with a random token — no other test's (or the
    seed's) leads can fingerprint the same.
    """
    token = uuid.uuid4().hex[:12]
    return (f"match-{token}@example.com", f"1555{token[:7]}")


# --- (a) OR — email-only and phone-only each match ---------------------------


async def test_email_only_match_flags(seeded, db_session):
    """A prior lead sharing only the email is found (the OR's email arm)."""
    tenant_id = await _tenant_id_for_slug(db_session, SUNSHINE.slug)
    email, phone = _unique_contact()
    _, other_phone = _unique_contact()
    prior_id = await _insert_lead(
        db_session, SUNSHINE.schema_name, tenant_id, email=email, phone=phone
    )
    await _scope_session_to_schema(db_session, SUNSHINE.schema_name)

    # Same email, a different (non-matching) phone — only the email arm can match.
    match = await find_duplicate_lead(db_session, tenant_id, email, other_phone)

    assert match is not None
    assert match.id == prior_id


async def test_phone_only_match_flags(seeded, db_session):
    """A prior lead sharing only the phone is found (the OR's phone arm)."""
    tenant_id = await _tenant_id_for_slug(db_session, SUNSHINE.slug)
    email, phone = _unique_contact()
    other_email, _ = _unique_contact()
    prior_id = await _insert_lead(
        db_session, SUNSHINE.schema_name, tenant_id, email=email, phone=phone
    )
    await _scope_session_to_schema(db_session, SUNSHINE.schema_name)

    # A different (non-matching) email, same phone — only the phone arm can match.
    match = await find_duplicate_lead(db_session, tenant_id, other_email, phone)

    assert match is not None
    assert match.id == prior_id


# --- (b) Oldest wins ---------------------------------------------------------


async def test_oldest_match_wins(seeded, db_session):
    """When two priors match, the earlier-`created_at` one is returned."""
    tenant_id = await _tenant_id_for_slug(db_session, SUNSHINE.slug)
    email, phone = _unique_contact()
    older_id = await _insert_lead(
        db_session,
        SUNSHINE.schema_name,
        tenant_id,
        email=email,
        phone=phone,
        created_at=BASE_CREATED_AT,
    )
    await _insert_lead(
        db_session,
        SUNSHINE.schema_name,
        tenant_id,
        email=email,
        phone=phone,
        created_at=BASE_CREATED_AT + timedelta(days=1),
    )
    await _scope_session_to_schema(db_session, SUNSHINE.schema_name)

    match = await find_duplicate_lead(db_session, tenant_id, email, phone)

    assert match is not None
    assert match.id == older_id


# --- (c) Self-exclusion ------------------------------------------------------


async def test_exclude_lead_id_omits_that_row(seeded, db_session):
    """Passing a lead's own id as `exclude_lead_id` keeps it from matching itself."""
    tenant_id = await _tenant_id_for_slug(db_session, SUNSHINE.slug)
    email, phone = _unique_contact()
    only_id = await _insert_lead(
        db_session, SUNSHINE.schema_name, tenant_id, email=email, phone=phone
    )
    await _scope_session_to_schema(db_session, SUNSHINE.schema_name)

    # Without exclusion the sole matching row is returned; excluding it returns None.
    assert (
        await find_duplicate_lead(db_session, tenant_id, email, phone)
    ).id == only_id
    assert (
        await find_duplicate_lead(
            db_session, tenant_id, email, phone, exclude_lead_id=only_id
        )
        is None
    )


# --- (d) Rejected excluded ---------------------------------------------------


async def test_rejected_prior_is_not_matched(seeded, db_session):
    """A `Rejected` prior is excluded as a match target (dead leads are skipped)."""
    tenant_id = await _tenant_id_for_slug(db_session, SUNSHINE.slug)
    email, phone = _unique_contact()
    await _insert_lead(
        db_session,
        SUNSHINE.schema_name,
        tenant_id,
        email=email,
        phone=phone,
        status=LeadStatus.REJECTED,
    )
    await _scope_session_to_schema(db_session, SUNSHINE.schema_name)

    match = await find_duplicate_lead(db_session, tenant_id, email, phone)

    assert match is None


async def test_non_rejected_statuses_stay_eligible(seeded, db_session):
    """`New` / `Working` / `Qualified` priors all stay eligible match targets."""
    tenant_id = await _tenant_id_for_slug(db_session, SUNSHINE.slug)
    for eligible_status in (
        LeadStatus.NEW,
        LeadStatus.WORKING,
        LeadStatus.QUALIFIED,
    ):
        email, phone = _unique_contact()
        prior_id = await _insert_lead(
            db_session,
            SUNSHINE.schema_name,
            tenant_id,
            email=email,
            phone=phone,
            status=eligible_status,
        )
        await _scope_session_to_schema(db_session, SUNSHINE.schema_name)

        match = await find_duplicate_lead(db_session, tenant_id, email, phone)

        assert match is not None, eligible_status
        assert match.id == prior_id


# --- (e) Tenant isolation ----------------------------------------------------


async def test_value_does_not_match_across_tenant_schema(seeded, db_session):
    """A value inserted in tenant A never matches when the query runs in tenant B.

    The lead is inserted into Sunshine's schema (with Sunshine's per-tenant key);
    running the matcher scoped to Florida's schema must find nothing, because the
    equality query is bound to the active `search_path` and the blind index uses a
    per-tenant key — so the value is both physically out of reach and fingerprints
    differently under Florida's key.
    """
    sunshine_id = await _tenant_id_for_slug(db_session, SUNSHINE.slug)
    florida_id = await _tenant_id_for_slug(db_session, FLORIDA.slug)
    email, phone = _unique_contact()
    await _insert_lead(
        db_session, SUNSHINE.schema_name, sunshine_id, email=email, phone=phone
    )
    await _scope_session_to_schema(db_session, FLORIDA.schema_name)

    match = await find_duplicate_lead(db_session, florida_id, email, phone)

    assert match is None


# --- (f) No decryption -------------------------------------------------------


async def test_match_never_decrypts(seeded, db_session, monkeypatch):
    """The match succeeds with `decrypt_field` rigged to fail — proving no decrypt.

    `decrypt_field` is patched on `app.pii.service` to raise if it is ever called.
    The matcher computes only blind indexes and queries the `*_blind_index` columns,
    so it must never reach `decrypt_field`; the match still returning the prior lead
    proves the whole path runs on the fingerprint alone.
    """
    async def fail_if_called(*args, **kwargs):
        raise AssertionError("decrypt_field must never be called by the matcher")

    tenant_id = await _tenant_id_for_slug(db_session, SUNSHINE.slug)
    email, phone = _unique_contact()
    prior_id = await _insert_lead(
        db_session, SUNSHINE.schema_name, tenant_id, email=email, phone=phone
    )
    await _scope_session_to_schema(db_session, SUNSHINE.schema_name)

    monkeypatch.setattr(pii_service_module, "decrypt_field", fail_if_called)
    match = await find_duplicate_lead(db_session, tenant_id, email, phone)

    assert match is not None
    assert match.id == prior_id
