"""True unit tests for the masked lead read builder (`app.leads.masking`).

These are **pure unit tests with no database**. The builder's only I/O is the PII
service seam `decrypt_field`; here that seam is stubbed (monkeypatched as imported
into `app.leads.masking`) to map known blobs to known plaintext, so each test
runs without Docker, keys, or crypto. The encrypt/decrypt round-trip itself is
already proven by `tests/test_pii_service.py`, and the DB-backed blind-index match
proof is Epic 6's job — this file proves only the **shape**: which fields are
shown in the clear, which are masked, which render `null` when absent, and which
are never on the wire at all.

Leads are constructed as in-memory `Lead` instances (no session, no insert), so
the assertions read straight off the dictionary the builder returns.
"""

import uuid
from datetime import datetime, timezone

import pytest

from app.leads import masking as masking_module
from app.leads.masking import build_masked_lead
from app.models.lead import Lead

# A fixed tenant id and the known blob -> plaintext mapping the stubbed
# `decrypt_field` resolves against. Using distinct sentinel `bytes` blobs (rather
# than real ciphertext) keeps the test pure: the builder only ever passes a blob
# to `decrypt_field`, so the stub mapping is all the "decryption" it needs.
TENANT_ID = uuid.uuid4()
EMAIL_BLOB = b"email-blob"
PHONE_BLOB = b"phone-blob"
EMAIL_PLAINTEXT = "jane.doe@example.com"
PHONE_PLAINTEXT = "+1 (555) 867-5309"

# The blob -> plaintext table the stubbed seam looks the supplied blob up in.
DECRYPTED_PLAINTEXT_BY_BLOB: dict[bytes, str] = {
    EMAIL_BLOB: EMAIL_PLAINTEXT,
    PHONE_BLOB: PHONE_PLAINTEXT,
}

# The masked display strings the real maskers produce for the plaintext above —
# hand-written here, independent of the production code, so the assertions are a
# genuine cross-check rather than a tautology over the masker under test.
EXPECTED_MASKED_EMAIL = "j***@e***.com"
EXPECTED_MASKED_PHONE = "***-***-5309"
EXPECTED_MASKED_DATE_OF_BIRTH = "****-**-**"
EXPECTED_GENERIC_MASK = "***"

# The fields that must never appear in the masked output (the locked exclusions):
# the two blind indexes, the correlation id, and the always-null demo session id.
EXCLUDED_FIELDS: frozenset[str] = frozenset(
    {
        "email_blind_index",
        "phone_blind_index",
        "correlation_id",
        "demo_session_id",
    }
)


@pytest.fixture(autouse=True)
def stub_decrypt_field(monkeypatch):
    """Stub `decrypt_field` as imported into `app.leads.masking`.

    The builder calls `decrypt_field` through its own module-level name, so the
    stub is patched onto `app.leads.masking` (the binding the builder actually
    uses), not `app.pii.service`. It maps a known blob to its known plaintext and
    rejects anything unexpected, so a test that decrypts a blob it never registered
    fails loudly rather than silently masking the wrong thing.
    """

    async def fake_decrypt_field(tenant_id: uuid.UUID, blob: bytes) -> str:
        assert tenant_id == TENANT_ID
        return DECRYPTED_PLAINTEXT_BY_BLOB[blob]

    monkeypatch.setattr(masking_module, "decrypt_field", fake_decrypt_field)


def build_lead(**overrides) -> Lead:
    """Construct an in-memory `Lead` with sensible defaults, overridable per test.

    Defaults to the happy-path, fully-populated lead (owned, with a street-address
    blob and every optional set); each test overrides only the fields it is about.
    No database — this is a plain ORM instance built for the builder to read.
    """
    now = datetime(2026, 6, 19, 12, 0, 0, tzinfo=timezone.utc)
    defaults = {
        "id": uuid.uuid4(),
        "first_name": "Jane",
        "last_name": "Doe",
        "email_encrypted": EMAIL_BLOB,
        "email_blind_index": b"email-blind-index",
        "phone_encrypted": PHONE_BLOB,
        "phone_blind_index": b"phone-blind-index",
        "date_of_birth_encrypted": b"dob-blob",
        "age_band": "50-64",
        "zip_code": "33101",
        "street_address_encrypted": b"street-blob",
        "product_lines_of_interest": ["term_life", "whole_life"],
        "preferred_contact_method": "email",
        "notes": "Prefers morning calls.",
        "rejection_reason": "Not a fit.",
        "lead_source": "agent_entered",
        "status": "Working",
        "owner_user_id": uuid.uuid4(),
        "owner_username": "agent.smith",
        "duplicate_of_lead_id": uuid.uuid4(),
        "duplicate_resolution": "linked",
        "converted_contact_id": None,
        "converted_opportunity_ids": None,
        "correlation_id": uuid.uuid4(),
        "demo_session_id": None,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return Lead(**defaults)


# --- (a) Happy path -------------------------------------------------------


async def test_happy_path_masks_email_and_phone():
    """Email and phone are decrypted then masked, never returned in the clear."""
    masked = await build_masked_lead(TENANT_ID, build_lead())

    assert masked["email"] == EXPECTED_MASKED_EMAIL
    assert masked["phone"] == EXPECTED_MASKED_PHONE
    # The plaintext must never leak through under any key.
    assert EMAIL_PLAINTEXT not in masked.values()
    assert PHONE_PLAINTEXT not in masked.values()


async def test_happy_path_date_of_birth_is_the_masked_constant():
    """Date of birth is the constant masked date — never decrypted on this path."""
    masked = await build_masked_lead(TENANT_ID, build_lead())

    assert masked["date_of_birth"] == EXPECTED_MASKED_DATE_OF_BIRTH


async def test_happy_path_age_band_is_the_stored_plaintext():
    """`age_band` is shown from the stored plaintext, not recomputed from the dob."""
    masked = await build_masked_lead(TENANT_ID, build_lead(age_band="65+"))

    assert masked["age_band"] == "65+"


async def test_happy_path_passes_plaintext_columns_through_unchanged():
    """The non-sensitive columns are returned exactly as stored."""
    lead = build_lead()
    masked = await build_masked_lead(TENANT_ID, lead)

    assert masked["id"] == lead.id
    assert masked["first_name"] == lead.first_name
    assert masked["last_name"] == lead.last_name
    assert masked["zip_code"] == lead.zip_code
    assert masked["product_lines_of_interest"] == lead.product_lines_of_interest
    assert masked["preferred_contact_method"] == lead.preferred_contact_method
    assert masked["notes"] == lead.notes
    assert masked["rejection_reason"] == lead.rejection_reason
    assert masked["lead_source"] == lead.lead_source
    assert masked["status"] == lead.status
    assert masked["owner_user_id"] == lead.owner_user_id
    assert masked["owner_username"] == lead.owner_username
    assert masked["duplicate_of_lead_id"] == lead.duplicate_of_lead_id
    assert masked["duplicate_resolution"] == lead.duplicate_resolution
    assert masked["created_at"] == lead.created_at
    assert masked["updated_at"] == lead.updated_at


async def test_happy_path_emits_the_full_expected_field_set():
    """The output keys are exactly the locked field set — no more, no less."""
    masked = await build_masked_lead(TENANT_ID, build_lead())

    expected_fields = {
        "id",
        "first_name",
        "last_name",
        "email",
        "phone",
        "date_of_birth",
        "age_band",
        "zip_code",
        "street_address",
        "product_lines_of_interest",
        "preferred_contact_method",
        "notes",
        "rejection_reason",
        "lead_source",
        "status",
        "owner_user_id",
        "owner_username",
        "duplicate_of_lead_id",
        "duplicate_resolution",
        "converted_contact_id",
        "converted_opportunity_ids",
        "created_at",
        "updated_at",
        "is_seed",
        "is_session_record",
    }
    assert set(masked) == expected_fields


# --- (b) Present / absent variants ----------------------------------------


async def test_street_address_present_renders_generic_mask():
    """A present street-address blob renders the generic `***` token (no decrypt)."""
    masked = await build_masked_lead(
        TENANT_ID, build_lead(street_address_encrypted=b"street-blob")
    )

    assert masked["street_address"] == EXPECTED_GENERIC_MASK


async def test_street_address_absent_renders_null():
    """An absent street-address blob renders `null` rather than a masked token."""
    masked = await build_masked_lead(
        TENANT_ID, build_lead(street_address_encrypted=None)
    )

    assert masked["street_address"] is None


async def test_optional_fields_render_null_when_unset():
    """Each unset optional renders `null` — never a masked-of-nothing string.

    Covers the street-address blob, the free-text optionals (including the
    reject-only `rejection_reason`), the owner fields (an unowned lead), and the
    duplicate-linkage fields (a lead with no flag).
    """
    lead = build_lead(
        street_address_encrypted=None,
        preferred_contact_method=None,
        notes=None,
        rejection_reason=None,
        owner_user_id=None,
        owner_username=None,
        duplicate_of_lead_id=None,
        duplicate_resolution=None,
    )
    masked = await build_masked_lead(TENANT_ID, lead)

    assert masked["street_address"] is None
    assert masked["preferred_contact_method"] is None
    assert masked["notes"] is None
    assert masked["rejection_reason"] is None
    assert masked["owner_user_id"] is None
    assert masked["owner_username"] is None
    assert masked["duplicate_of_lead_id"] is None
    assert masked["duplicate_resolution"] is None


# --- (b2) Converted-ref columns (P2.1) ------------------------------------


async def test_converted_refs_render_null_for_an_unconverted_lead():
    """A lead that hasn't been converted carries `null` for both converted refs."""
    lead = build_lead(
        converted_contact_id=None, converted_opportunity_ids=None
    )
    masked = await build_masked_lead(TENANT_ID, lead)

    assert masked["converted_contact_id"] is None
    assert masked["converted_opportunity_ids"] is None


async def test_converted_refs_pass_through_raw_for_a_converted_lead():
    """A converted lead returns the raw uuid and uuid list — the encoder stringifies.

    The builder does no casting: `converted_contact_id` is the raw `uuid.UUID` and
    `converted_opportunity_ids` is the raw `list[uuid.UUID]` (the response encoder
    turns them into a string and a JSON array of strings, as it does for `id` and
    `product_lines_of_interest`).
    """
    contact_id = uuid.uuid4()
    opportunity_ids = [uuid.uuid4(), uuid.uuid4()]
    lead = build_lead(
        status="Converted",
        converted_contact_id=contact_id,
        converted_opportunity_ids=opportunity_ids,
    )
    masked = await build_masked_lead(TENANT_ID, lead)

    assert masked["converted_contact_id"] == contact_id
    assert masked["converted_opportunity_ids"] == opportunity_ids


# --- (c) Exclusions -------------------------------------------------------


async def test_excluded_fields_never_appear_in_the_output():
    """Blind indexes, correlation id, and demo session id are never on the wire."""
    masked = await build_masked_lead(TENANT_ID, build_lead())

    for excluded_field in EXCLUDED_FIELDS:
        assert excluded_field not in masked


# --- (d) Demo-session markers (Epic 6) ------------------------------------


async def test_session_markers_false_for_session_less_caller():
    """A caller with no demo session (the default arg) sees neither marker.

    Both markers are gated on the caller having a live session, so the non-demo read
    surface is unchanged: even a seed (`NULL`) row is neither `is_seed` nor
    `is_session_record` when the reader is session-less.
    """
    masked = await build_masked_lead(TENANT_ID, build_lead(demo_session_id=None))

    assert masked["is_seed"] is False
    assert masked["is_session_record"] is False


async def test_seed_row_is_marked_is_seed_for_a_session_caller():
    """A session caller reading a shared seed row (`NULL`) gets `is_seed` only."""
    caller_session_id = uuid.uuid4()
    masked = await build_masked_lead(
        TENANT_ID, build_lead(demo_session_id=None), caller_session_id
    )

    assert masked["is_seed"] is True
    assert masked["is_session_record"] is False


async def test_own_row_is_marked_is_session_record_for_a_session_caller():
    """A session caller reading their own session's row gets `is_session_record` only."""
    caller_session_id = uuid.uuid4()
    masked = await build_masked_lead(
        TENANT_ID, build_lead(demo_session_id=caller_session_id), caller_session_id
    )

    assert masked["is_session_record"] is True
    assert masked["is_seed"] is False


async def test_foreign_session_row_has_neither_marker():
    """A row owned by another session is neither marker (it is not seed, not theirs).

    (The read path 404s a foreign-session row before this builder is reached; this
    proves the derivation itself does not mis-mark one as seed or own.)
    """
    caller_session_id = uuid.uuid4()
    other_session_id = uuid.uuid4()
    masked = await build_masked_lead(
        TENANT_ID, build_lead(demo_session_id=other_session_id), caller_session_id
    )

    assert masked["is_seed"] is False
    assert masked["is_session_record"] is False
