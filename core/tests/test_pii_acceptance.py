"""PII-protection acceptance suite for P1.3 (Epic 13).

This is the phase's named acceptance proof: that personal data is ciphertext at
rest, that an exact-match lookup works **without decryption** under the real
per-tenant role (retiring the program's tracked **Risk #3**), that one tenant's
ciphertext cannot be unlocked with another tenant's key, and that the HTTP
surface masks by default with reveal as its single, RBAC-gated plaintext egress.

It is packaged **add-only** — it asserts only the genuinely-missing acceptance
proofs plus a thin named acceptance narrative, and deliberately does **not** move,
re-run, or duplicate the focused per-epic tests, nor re-implement migration
health. Specifically, what stays owned elsewhere:

- **Migration health** stays entirely in `test_migration_hygiene.py`: it asserts
  `alembic check` no-drift (with `tenant_data_keys` reflected and the schema-less
  `pii_demo` / `tenant_settings` excluded by the `alembic/env.py` filter) and the
  `downgrade base -> upgrade head` round-trip. This module adds **no new
  migration-health code**; the phase's "confirm CI/gate green" is satisfied by the
  complete step's green gate.
- **The full case matrices** stay in the per-epic endpoint tests: the masked
  write/read matrix in `test_pii_demo_endpoints.py`, the blind-index lookup matrix
  (incl. the HTTP-level cross-tenant isolation case) in `test_pii_demo_lookup.py`,
  and the 12-case reveal RBAC / refusal matrix in `test_pii_demo_reveal.py`. The
  narrative below is a concise summary, not a re-run of those matrices.

The four phases (simplest-first, each independently reviewable):

- **Phase 1 — ciphertext at rest (headline proof):** read the raw `*_encrypted`
  bytea straight from `sunshine.pii_demo` / `florida.pii_demo` with `text()` on
  `database_engine`, bypassing the service, and assert each blob is non-empty
  `bytes` and the known seeded plaintext (email, DOB, mock Medicare id) is absent
  from the raw bytes — so Postgres stores ciphertext, never plaintext.
- **Phase 2 — Risk #3: blind-index exact-match under the switched tenant role:**
  compute the blind index in Python, then under `SET LOCAL ROLE tenant_sunshine`
  (each attempt in its own `database_engine.begin()` block, the
  `test_isolation_acceptance.py` Phase-1 idiom) run a raw equality `SELECT ...
  WHERE email_blind_index = :index` and assert it returns Margaret's row with no
  decryption; a non-matching index returns zero rows.
- **Phase 3 — per-tenant key isolation with real seeded keys:** read both real
  seeded tenant UUIDs from `platform.tenants`, grab a real Sunshine
  `email_encrypted` blob, and assert `decrypt_field(sunshine_tenant_id, blob)`
  returns the plaintext email while `decrypt_field(florida_tenant_id, blob)`
  raises `ValueError` — real keys + tenant-id AAD, the acceptance-level version of
  the synthetic-uuid check in `test_pii_service.py`.
- **Phase 4 — masking-default + sole-plaintext-egress + reveal-RBAC narrative
  (HTTP):** as the Agent, create one record with sentinel PII and assert the
  sentinel plaintext never appears in get / list / lookup (masked) while
  `age_band` is returned in plaintext, then that the sentinel email plaintext
  appears in exactly the reveal response — the single sanctioned egress — and a
  thin reveal-RBAC summary (Agent 200, Read-Only / Platform-Admin 403,
  `mock_medicare_id` 422).

`pytest.ini` sets `asyncio_mode = auto`, so the Phase 4 async HTTP tests carry no
`@pytest.mark.asyncio` decorator; the Phase 1-3 substrate tests that drive the
`database_engine` directly keep it, matching `test_isolation_acceptance.py` and
the other `database_engine` substrate modules.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.user import Role
from app.pii.crypto import normalize_email
from app.pii.service import compute_blind_index, decrypt_field
from app.seed import seed
from app.tenancy.registry import FLORIDA, SUNSHINE

from .test_endpoints_db import (  # noqa: F401 — `seeded` fixture is used by name
    login_as,
    seeded,
)

# The known seeded plaintext the at-rest and isolation proofs assert against,
# read verbatim from `app.seed.DEMO_PII_RECORDS` so this module and the seed can
# never disagree about what was encrypted.
MARGARET_EMAIL = "margaret.sunshine@example.com"
MARGARET_DATE_OF_BIRTH_ISO = "1950-04-12"
MARGARET_MEDICARE_ID = "555-12-7788"
ANA_EMAIL = "ana.marisol@example.com"


async def _read_tenant_id(connection, slug: str) -> uuid.UUID:
    """Return the seed-generated tenant UUID for `slug` from `platform.tenants`.

    The registry carries the schema name and DB role but not the UUID (it is
    minted by the seed), so the real id is read back from the platform table the
    same way the seed and the scoping dependency resolve it.
    """
    return (
        await connection.execute(
            text("SELECT id FROM platform.tenants WHERE slug = :slug"),
            {"slug": slug},
        )
    ).scalar_one()


async def _read_first_email_blob(connection, schema_name: str) -> bytes:
    """Return one `email_encrypted` blob from `<schema>.pii_demo` (oldest first)."""
    return (
        await connection.execute(
            text(
                "SELECT email_encrypted "
                f"FROM {schema_name}.pii_demo "
                "ORDER BY created_at LIMIT 1"
            )
        )
    ).scalar_one()


# --- Phase 1: ciphertext at rest (headline proof) ----------------------------


@pytest.mark.asyncio
async def test_pii_is_ciphertext_at_rest(database_engine, container_keys_session_factory):
    """ACCEPTANCE: every PII field is stored as ciphertext, never plaintext.

    Seeds the demo data, then reads the raw `*_encrypted` bytea straight from
    `sunshine.pii_demo` and `florida.pii_demo` with `text()` — bypassing the
    service, so we observe exactly what Postgres stores. Each encrypted blob must
    be non-empty `bytes`, and the corresponding known seeded plaintext must be
    absent from those raw bytes: Margaret's email, ISO date of birth, and mock
    Medicare id for Sunshine, and Ana's email for Florida. This is the "PII is
    ciphertext at rest" proof.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    async with session_factory() as session:
        await seed(session)

    async with database_engine.begin() as connection:
        sunshine_row = (
            await connection.execute(
                text(
                    "SELECT email_encrypted, date_of_birth_encrypted, "
                    "mock_medicare_id_encrypted "
                    f"FROM {SUNSHINE.schema_name}.pii_demo "
                    "WHERE mock_medicare_id_encrypted IS NOT NULL "
                    "ORDER BY created_at LIMIT 1"
                )
            )
        ).one()
        florida_email_blob = await _read_first_email_blob(
            connection, FLORIDA.schema_name
        )

    # Every blob is real, non-empty bytes — not a NULL or an empty placeholder.
    for blob in (
        sunshine_row.email_encrypted,
        sunshine_row.date_of_birth_encrypted,
        sunshine_row.mock_medicare_id_encrypted,
        florida_email_blob,
    ):
        assert isinstance(blob, (bytes, bytearray))
        assert len(blob) > 0

    # The known seeded plaintext never appears in the raw stored bytes.
    assert MARGARET_EMAIL.encode("utf-8") not in sunshine_row.email_encrypted
    assert (
        MARGARET_DATE_OF_BIRTH_ISO.encode("utf-8")
        not in sunshine_row.date_of_birth_encrypted
    )
    assert (
        MARGARET_MEDICARE_ID.encode("utf-8")
        not in sunshine_row.mock_medicare_id_encrypted
    )
    assert ANA_EMAIL.encode("utf-8") not in florida_email_blob


# --- Phase 2: Risk #3 — blind-index exact-match under the switched role -------


@pytest.mark.asyncio
async def test_blind_index_exact_match_under_tenant_role_without_decryption(
    database_engine, container_keys_session_factory
):
    """ACCEPTANCE (Risk #3): blind-index equality finds the row under the tenant role.

    Computes Margaret's email blind index in Python with `compute_blind_index`
    (keys resolve through `container_keys_session_factory`), then under
    `SET LOCAL ROLE tenant_sunshine` runs a raw equality
    `SELECT ... WHERE email_blind_index = :index` against `sunshine.pii_demo`. The
    matching index must return exactly Margaret's row — with **no decryption on
    this path** — and a non-matching index must return zero rows. This retires
    Risk #3 with a physical DB-layer proof under the real per-tenant role,
    complementing the HTTP-level lookup test in `test_pii_demo_lookup.py`. Each
    attempt runs in its own `database_engine.begin()` block so `SET LOCAL ROLE`
    resets as the transaction ends — the `test_isolation_acceptance.py` Phase-1
    idiom.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    async with session_factory() as session:
        await seed(session)

    async with database_engine.begin() as connection:
        sunshine_tenant_id = await _read_tenant_id(connection, SUNSHINE.slug)

    matching_index = await compute_blind_index(
        sunshine_tenant_id, normalize_email(MARGARET_EMAIL)
    )
    non_matching_index = await compute_blind_index(
        sunshine_tenant_id, normalize_email("nobody-matches-this@example.com")
    )

    # An exact match: the equality query returns Margaret's display name, proving
    # the lookup found the row by fingerprint alone, with nothing decrypted.
    async with database_engine.begin() as connection:
        await connection.execute(
            text(f"SET LOCAL ROLE {SUNSHINE.db_role}")
        )
        matched = (
            await connection.execute(
                text(
                    "SELECT display_name "
                    f"FROM {SUNSHINE.schema_name}.pii_demo "
                    "WHERE email_blind_index = :index"
                ),
                {"index": matching_index},
            )
        ).all()
    assert len(matched) == 1
    assert matched[0].display_name == "Margaret Sunshine"

    # A non-matching fingerprint returns zero rows — exact-match, not a scan.
    async with database_engine.begin() as connection:
        await connection.execute(
            text(f"SET LOCAL ROLE {SUNSHINE.db_role}")
        )
        missed = (
            await connection.execute(
                text(
                    "SELECT display_name "
                    f"FROM {SUNSHINE.schema_name}.pii_demo "
                    "WHERE email_blind_index = :index"
                ),
                {"index": non_matching_index},
            )
        ).all()
    assert missed == []


# --- Phase 3: per-tenant key isolation with real seeded keys -----------------


@pytest.mark.asyncio
async def test_one_tenants_ciphertext_cannot_be_decrypted_with_another_tenants_key(
    database_engine, container_keys_session_factory
):
    """ACCEPTANCE: a Sunshine blob decrypts under Sunshine's key, not Florida's.

    Reads both real seeded tenant UUIDs from `platform.tenants` and a real Sunshine
    `email_encrypted` blob from `sunshine.pii_demo`. `decrypt_field` resolves each
    tenant's real seeded key (via `container_keys_session_factory`) and binds the
    tenant id as AES-GCM associated data, so decrypting the Sunshine blob under the
    Sunshine tenant id returns the plaintext email, while decrypting the *same*
    blob under the Florida tenant id raises `ValueError` — one tenant's ciphertext
    cannot be unlocked with another's key. This is the acceptance-level version of
    the synthetic-uuid check in `test_pii_service.py`, using the real seeded keys.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    async with session_factory() as session:
        await seed(session)

    async with database_engine.begin() as connection:
        sunshine_tenant_id = await _read_tenant_id(connection, SUNSHINE.slug)
        florida_tenant_id = await _read_tenant_id(connection, FLORIDA.slug)
        sunshine_email_blob = await _read_first_email_blob(
            connection, SUNSHINE.schema_name
        )

    # The owning tenant unlocks its own ciphertext.
    decrypted_email = await decrypt_field(sunshine_tenant_id, sunshine_email_blob)
    assert decrypted_email == MARGARET_EMAIL

    # Another tenant's key (and tenant-id AAD) cannot — a uniform `ValueError`.
    with pytest.raises(ValueError):
        await decrypt_field(florida_tenant_id, sunshine_email_blob)


# --- Phase 4: masking-default + sole-plaintext-egress + reveal-RBAC narrative -


# The sentinel record this phase creates and tracks through the HTTP surface. Its
# plaintext values are deliberately recognizable so an unmasked leak in any read
# response would be unmistakable.
SENTINEL_RECORD_BODY = {
    "display_name": "Acceptance Sentinel",
    "email": "acceptance.sentinel@example.com",
    "date_of_birth": "1950-06-14",
    "phone": "+1 (305) 555-7777",
    "mock_medicare_id": "999-88-7777",
}


async def test_masking_is_default_and_reveal_is_the_sole_plaintext_egress(
    seeded, db_client
):
    """ACCEPTANCE: reads are masked by default; reveal is the only plaintext egress.

    As the Agent, create one record with sentinel PII, then assert the sentinel
    email / phone / date-of-birth / mock-Medicare-id plaintext appears in **none**
    of the masked read responses (`GET /{id}`, `GET /` list, `POST /lookup`), while
    the plaintext `age_band` **is** returned. Then assert the sentinel email
    plaintext appears in exactly the `POST /{id}/reveal` response — the single
    sanctioned plaintext egress for this phase.
    """
    assert (await login_as(db_client, Role.AGENT)).status_code == 200

    create_response = await db_client.post(
        "/api/pii-demo/", json=SENTINEL_RECORD_BODY
    )
    assert create_response.status_code == 201
    record_id = create_response.json()["record"]["id"]

    sentinel_plaintext_values = (
        SENTINEL_RECORD_BODY["email"],
        SENTINEL_RECORD_BODY["phone"],
        SENTINEL_RECORD_BODY["date_of_birth"],
        SENTINEL_RECORD_BODY["mock_medicare_id"],
    )

    get_response = await db_client.get(f"/api/pii-demo/{record_id}")
    assert get_response.status_code == 200
    list_response = await db_client.get("/api/pii-demo/")
    assert list_response.status_code == 200
    lookup_response = await db_client.post(
        "/api/pii-demo/lookup", json={"email": SENTINEL_RECORD_BODY["email"]}
    )
    assert lookup_response.status_code == 200

    # No masked read response — get, list, or lookup — leaks any sentinel plaintext.
    for masked_response in (get_response, list_response, lookup_response):
        response_text = masked_response.text
        for plaintext_value in sentinel_plaintext_values:
            assert plaintext_value not in response_text

    # The plaintext age band is shown in place of the date of birth on the masked read.
    masked_record = get_response.json()["record"]
    assert masked_record["age_band"] == "65+"
    assert masked_record["date_of_birth"] == "****-**-**"

    # Reveal is the single sanctioned plaintext egress: the sentinel email comes
    # back unmasked here and nowhere else.
    reveal_response = await db_client.post(
        f"/api/pii-demo/{record_id}/reveal", json={"field": "email"}
    )
    assert reveal_response.status_code == 200
    assert reveal_response.json() == {
        "field": "email",
        "value": SENTINEL_RECORD_BODY["email"],
    }


async def test_reveal_rbac_summary(seeded, db_client):
    """ACCEPTANCE (thin narrative): who may reveal, and what is never revealable.

    A concise reveal-RBAC summary — not a re-run of the 12-case
    `test_pii_demo_reveal.py` matrix. As the Agent (holds `REVEAL_PII`), revealing
    `email` returns the real value (200) and `mock_medicare_id` is refused as
    never revealable (422). As a Read-Only user and as the Platform Admin (neither
    holds `REVEAL_PII`), reveal is forbidden (403).
    """
    # Agent: holds REVEAL_PII — reveals the real value, but never the Medicare id.
    assert (await login_as(db_client, Role.AGENT)).status_code == 200
    create_response = await db_client.post(
        "/api/pii-demo/", json=SENTINEL_RECORD_BODY
    )
    assert create_response.status_code == 201
    record_id = create_response.json()["record"]["id"]

    email_reveal = await db_client.post(
        f"/api/pii-demo/{record_id}/reveal", json={"field": "email"}
    )
    assert email_reveal.status_code == 200
    assert email_reveal.json()["value"] == SENTINEL_RECORD_BODY["email"]

    medicare_reveal = await db_client.post(
        f"/api/pii-demo/{record_id}/reveal", json={"field": "mock_medicare_id"}
    )
    assert medicare_reveal.status_code == 422
    assert medicare_reveal.json() == {"detail": "field is never revealable"}

    # Read-Only and Platform Admin: lack REVEAL_PII — forbidden.
    for role_without_reveal in (Role.READ_ONLY, Role.PLATFORM_ADMIN):
        assert (await login_as(db_client, role_without_reveal)).status_code == 200
        forbidden_reveal = await db_client.post(
            f"/api/pii-demo/{uuid.uuid4()}/reveal", json={"field": "email"}
        )
        assert forbidden_reveal.status_code == 403
        assert forbidden_reveal.json() == {"detail": "insufficient permissions"}
