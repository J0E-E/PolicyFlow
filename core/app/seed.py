"""Idempotent seed for the core service: two demo tenants and nine demo users.

The container entrypoint runs ``migrate -> seed -> serve`` on every boot, so this
module is where the demo data appears. It seeds the full RBAC role matrix so a
fresh boot is immediately signable-in: two demo tenants and nine demo users (per
tenant two Agents, one Tenant Admin, one Read-Only; plus one global tenantless
Platform Admin).

Seeding is **idempotent** — re-running on every reboot inserts only what is
absent (keyed by tenant ``slug`` and user ``username``), never duplicating or
erroring. Each persona logs in with their email: ``username`` and ``email`` hold
the same email-style string, and every persona shares the password from
``settings.seed_user_password``.

The module stays runnable as ``python -m app.seed`` via the thin sync ``run()``
entrypoint the container relies on.
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .auth.passwords import hash_password
from .config import settings
from .db import session_factory
from .events.catalog import (
    ENRICHMENT_STUB,
    SCHEMA_VERSION,
    EventType,
    consumers_for_event_type,
)
from .events.enrichment import enrichment_result_summary
from .leads.state import LeadSource, LeadStatus
from .models import Role, Tenant, TenantDataKey, User
from .pii.crypto import normalize_email, normalize_phone, wrap_key
from .pii.masking import age_band_for
from .pii.service import compute_blind_index, encrypt_field
from .tenancy.registry import TENANTS, tenant_by_slug

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# A tenant's root key is 32 random bytes; HKDF later derives the encryption and
# blind-index subkeys from it (see app/pii/keys.py).
ROOT_KEY_LENGTH_BYTES = 32


# --- The persona spec (pure data, no DB) -------------------------------------
#
# These module-level structures describe the demo data declaratively so the
# matrix can be unit-tested without touching a database.

# (slug, display name) for each demo tenant, derived from the tenant registry so
# the seed and the registry can never disagree about which tenants exist.
DEMO_TENANTS: tuple[tuple[str, str], ...] = tuple(
    (config.slug, config.display_name) for config in TENANTS
)

# The local part (before the @) and role of every per-tenant persona.
TENANT_USER_TEMPLATES: tuple[tuple[str, Role], ...] = (
    ("agent.one", Role.AGENT),
    ("agent.two", Role.AGENT),
    ("admin", Role.TENANT_ADMIN),
    ("readonly", Role.READ_ONLY),
)

# The single tenantless platform administrator (tenant_id stays None).
PLATFORM_ADMIN_EMAIL = "platform.admin@policyflow.example"

# The demo presentation settings for each tenant, keyed by slug. These are
# presentation content (logo, welcome message), so they live here in the seed
# rather than in the tenant registry, which is reserved for isolation config the
# migration imports. The brand colour is the one exception: it lives only in the
# registry (`TenantConfig.brand_primary_color`, the single source of truth) and
# the seed derives each tenant's `tenant_settings` colour from there, so
# `/api/tenants` and the seeded rows can never diverge. The seed writes one row
# per tenant into that tenant's own `tenant_settings` table. The logo URL is a
# distinct per-tenant placeholder built from the registry schema name.
DEMO_TENANT_SETTINGS: dict[str, dict[str, str]] = {
    "sunshine-senior-benefits": {
        "welcome_message": (
            "Welcome to Sunshine Senior Benefits — Medicare coverage made "
            "simple."
        ),
    },
    "florida-family-planning": {
        "welcome_message": (
            "Welcome to Florida Family Planning — coverage for every stage of "
            "your family's life."
        ),
    },
}


# The synthetic demo PII records seeded into each tenant's own `pii_demo` table,
# keyed by tenant slug. All values are fabricated (not real people). The personas
# are chosen to exercise both ends of the masked write/read demonstrator:
#
# - Sunshine Senior Benefits gets a 65+ persona **with** a mock Medicare id (and a
#   phone), so a row carries every field treatment, including the never-revealable
#   Medicare id, and lands in the `65+` age band.
# - Florida Family Planning gets younger personas **without** a Medicare id, one
#   with a phone and one without, so an absent optional field is exercised too.
#
# `age_band` is not stored here — it is always derived from `date_of_birth` at
# seed time, exactly as the create endpoint derives it. The birth dates are far
# enough from any plausible run date that the bands stay stable over time.
DEMO_PII_RECORDS: dict[str, list[dict]] = {
    "sunshine-senior-benefits": [
        {
            "display_name": "Margaret Sunshine",
            "email": "margaret.sunshine@example.com",
            "date_of_birth": date(1950, 4, 12),
            "phone": "+1 (305) 555-0142",
            "mock_medicare_id": "555-12-7788",
        },
        {
            "display_name": "Harold Brightwater",
            "email": "harold.brightwater@example.com",
            "date_of_birth": date(1948, 11, 3),
            "phone": "+1 (561) 555-0199",
            "mock_medicare_id": "555-34-9911",
        },
    ],
    "florida-family-planning": [
        {
            "display_name": "Ana Marisol",
            "email": "ana.marisol@example.com",
            "date_of_birth": date(1994, 7, 22),
            "phone": "+1 (786) 555-0123",
            "mock_medicare_id": None,
        },
        {
            "display_name": "Diego Familia",
            "email": "diego.familia@example.com",
            "date_of_birth": date(1989, 2, 9),
            "phone": None,
            "mock_medicare_id": None,
        },
    ],
}


# The per-session New-queue lead templates, keyed by tenant slug. These are the
# canonical set `app.demo.instantiation.ensure_session_leads` stamps into a
# visitor's **own** private queue (session-tagged) on first `assume-persona` — they
# are **not** seeded by the boot seed (P1.8 Epic 7 split them out of the shared
# `NULL` baseline so concurrent visitors each work their own claimable queue without
# touching shared seed; the shared-historical read-only set is Epic 8's). Every row
# is a **queue lead**: `public_form` source, unowned (`owner_user_id` null), born
# `New` — exactly the shape the unassigned queue filter surfaces.
#
# Each tenant gets 3 ordinary filler leads + 1 duplicate-bait (8 templates total).
# The fillers are clearly synthetic — `example.com` emails, `555-01xx` phones —
# with distinct, all-decimal phones and distinct emails (the matcher-collision
# gotcha: low-entropy contact details in the shared container DB flag unrelated
# leads), a spread of dates of birth across age bands, and a mix of present/absent
# `street_address`. Product-line keys are validated against the tenant's registry
# set (Epic 4) — Sunshine's Medicare/expense lines, Florida's life/health lines.
#
# The **duplicate-bait** is the *same identity* in both tenants (Jordan Rivera,
# same email + phone), so the "Try a duplicate scenario" prefill is one payload
# that flags in whichever tenant the shopper submits to. Its normalized email +
# phone are the cross-epic contract that prefill must submit (the frontend's
# `shopperIntakePrefills.ts` mirrors these constants verbatim). Only its product
# line differs per tenant (each tenant's first registry key). The bait is now
# **session-tagged** per visit (not the shared `NULL` bait), so a visitor's "Try a
# duplicate" flags against seed ∪ their own rows only (Epic 5's matcher scoping).
#
# `age_band` is never stored here — it is derived from `date_of_birth` at
# instantiation time, exactly as the create path derives it. The birth dates are
# far enough from any plausible run date that the bands stay stable over time.
JORDAN_RIVERA_BAIT_EMAIL = "jordan.rivera@example.com"
JORDAN_RIVERA_BAIT_PHONE = "(407) 555-0188"

SESSION_LEAD_TEMPLATES: dict[str, list[dict]] = {
    "sunshine-senior-benefits": [
        {
            "first_name": "Eleanor",
            "last_name": "Whitfield",
            "email": "eleanor.whitfield@example.com",
            "phone": "(305) 555-0142",
            "date_of_birth": date(1947, 9, 4),
            "zip_code": "33139",
            "street_address": "1820 Collins Avenue",
            "preferred_contact_method": "phone",
            "product_lines_of_interest": ["medicare_advantage"],
        },
        {
            "first_name": "Marcus",
            "last_name": "Delgado",
            "email": "marcus.delgado@example.com",
            "phone": "(561) 555-0173",
            "date_of_birth": date(1955, 1, 27),
            "zip_code": "33401",
            "street_address": None,
            "preferred_contact_method": "email",
            "product_lines_of_interest": ["medicare_supplement", "final_expense"],
        },
        {
            # Priya is intentionally **under 65** (planning ahead before she ages in)
            # **and** inquiring about a Medicare line, so converting her yields a
            # Medicare-gated, under-65 opportunity the agent can demonstrate the
            # *Quoted* block on (walkthrough step 8) — no ad-hoc data entry needed
            # (P2.2 Epic 9, Risk R1). Her DOB sits comfortably under 65 so the scripted
            # block stays reliable for years.
            "first_name": "Priya",
            "last_name": "Nakamura",
            "email": "priya.nakamura@example.com",
            "phone": "(786) 555-0156",
            "date_of_birth": date(1965, 6, 11),
            "zip_code": "33156",
            "street_address": "640 Sunset Drive",
            "preferred_contact_method": "email",
            "product_lines_of_interest": ["medicare_advantage"],
        },
        {
            "first_name": "Jordan",
            "last_name": "Rivera",
            "email": JORDAN_RIVERA_BAIT_EMAIL,
            "phone": JORDAN_RIVERA_BAIT_PHONE,
            "date_of_birth": date(1958, 6, 15),
            "zip_code": "32801",
            "street_address": "742 Marina Bay Drive",
            "preferred_contact_method": "email",
            "product_lines_of_interest": ["medicare_advantage"],
        },
    ],
    "florida-family-planning": [
        {
            "first_name": "Tomas",
            "last_name": "Esperanza",
            "email": "tomas.esperanza@example.com",
            "phone": "(813) 555-0119",
            "date_of_birth": date(1996, 3, 30),
            "zip_code": "33602",
            "street_address": "210 Channelside Drive",
            "preferred_contact_method": "text",
            "product_lines_of_interest": ["term_life"],
        },
        {
            "first_name": "Sofia",
            "last_name": "Almeida",
            "email": "sofia.almeida@example.com",
            "phone": "(904) 555-0134",
            "date_of_birth": date(1983, 12, 5),
            "zip_code": "32202",
            "street_address": None,
            "preferred_contact_method": "phone",
            "product_lines_of_interest": ["whole_life", "critical_illness"],
        },
        {
            "first_name": "Devin",
            "last_name": "Okonkwo",
            "email": "devin.okonkwo@example.com",
            "phone": "(727) 555-0167",
            "date_of_birth": date(1971, 8, 19),
            "zip_code": "33701",
            "street_address": "95 Beach Drive Northeast",
            "preferred_contact_method": "email",
            "product_lines_of_interest": ["health"],
        },
        {
            "first_name": "Jordan",
            "last_name": "Rivera",
            "email": JORDAN_RIVERA_BAIT_EMAIL,
            "phone": JORDAN_RIVERA_BAIT_PHONE,
            "date_of_birth": date(1958, 6, 15),
            "zip_code": "32801",
            "street_address": "742 Marina Bay Drive",
            "preferred_contact_method": "email",
            "product_lines_of_interest": ["term_life"],
        },
    ],
}


# The shared read-only historical lead set, keyed by tenant slug. These are the
# worked/historical leads the boot seed stamps into each tenant's `leads` table as
# the shared `NULL` baseline (`demo_session_id IS NULL`), so lists and dashboards
# render non-trivially from seed alone — context every visitor sees, none can claim
# (P1.8 Epic 8). They are the complement of `SESSION_LEAD_TEMPLATES`: that set is
# the per-visit *claimable* New queue; this set is the shared *read-only* history.
#
# 6 rows per tenant — **2 Working / 2 Qualified / 2 Rejected** — all **owned**, split
# 3/3 across `agent.one` and `agent.two` (`owner_local_part`, resolved to the seeded
# user's id + email at seed time). There are deliberately **no unowned / `New` rows**:
# an unowned `New` row would surface in the Unassigned-queue tab looking claimable
# while the Epic 5 write guard silently `409`s a live-session caller acting on it, so
# every historical row is owned and past `New`. Each **Rejected** row is a
# `Working → Rejected` outcome and carries a `rejection_reason` (the reject path's
# free-text), so it reads as a real worked-then-declined lead. `lead_source` is
# `agent_entered` — these are agent-worked records, not fresh public submissions.
#
# `created_at_offset_days` backdates each row relative to boot (computed at seed time,
# so the rows stay recent — spread over the last few weeks): they sort **below**
# today's fresh session queue and read as history. Emails are distinct and clearly
# synthetic (`example.com`); phones are distinct and **all-decimal** (the matcher-
# collision gotcha: low-entropy contact details in the shared container DB flag
# unrelated leads). Product-line keys come from each tenant's registry set (Sunshine's
# Medicare/expense lines, Florida's life/health lines); dates of birth spread across
# the age bands; `street_address` mixes present/absent.
#
# `age_band` is never stored here — it is derived from `date_of_birth` at seed time,
# exactly as the create path derives it. The birth dates are far enough from any
# plausible run date that the bands stay stable over time.
SHARED_HISTORICAL_LEADS: dict[str, list[dict]] = {
    "sunshine-senior-benefits": [
        {
            "first_name": "Gloria",
            "last_name": "Hampton",
            "email": "gloria.hampton@example.com",
            "phone": "(305) 555-0201",
            "date_of_birth": date(1951, 2, 18),
            "zip_code": "33139",
            "street_address": "1450 Ocean Drive",
            "preferred_contact_method": "phone",
            "product_lines_of_interest": ["medicare_advantage"],
            "status": LeadStatus.WORKING,
            "owner_local_part": "agent.one",
            "rejection_reason": None,
            "created_at_offset_days": 4,
        },
        {
            "first_name": "Walter",
            "last_name": "Brennan",
            "email": "walter.brennan@example.com",
            "phone": "(561) 555-0212",
            "date_of_birth": date(1956, 10, 7),
            "zip_code": "33401",
            "street_address": None,
            "preferred_contact_method": "email",
            "product_lines_of_interest": ["medicare_supplement"],
            "status": LeadStatus.WORKING,
            "owner_local_part": "agent.two",
            "rejection_reason": None,
            "created_at_offset_days": 9,
        },
        {
            "first_name": "Estelle",
            "last_name": "Marchetti",
            "email": "estelle.marchetti@example.com",
            "phone": "(786) 555-0223",
            "date_of_birth": date(1948, 6, 25),
            "zip_code": "33156",
            "street_address": "980 Brickell Avenue",
            "preferred_contact_method": "phone",
            "product_lines_of_interest": ["final_expense"],
            "status": LeadStatus.QUALIFIED,
            "owner_local_part": "agent.one",
            "rejection_reason": None,
            "created_at_offset_days": 13,
        },
        {
            "first_name": "Raymond",
            "last_name": "Castellano",
            "email": "raymond.castellano@example.com",
            "phone": "(954) 555-0234",
            "date_of_birth": date(1953, 12, 1),
            "zip_code": "33301",
            "street_address": "60 Las Olas Boulevard",
            "preferred_contact_method": "email",
            "product_lines_of_interest": ["dental_vision_hearing", "medicare_advantage"],
            "status": LeadStatus.QUALIFIED,
            "owner_local_part": "agent.two",
            "rejection_reason": None,
            "created_at_offset_days": 17,
        },
        {
            "first_name": "Doris",
            "last_name": "Whitlock",
            "email": "doris.whitlock@example.com",
            "phone": "(727) 555-0245",
            "date_of_birth": date(1959, 3, 14),
            "zip_code": "33701",
            "street_address": None,
            "preferred_contact_method": "phone",
            "product_lines_of_interest": ["medicare_supplement"],
            "status": LeadStatus.REJECTED,
            "owner_local_part": "agent.one",
            "rejection_reason": "Outside service area — referred to another carrier.",
            "created_at_offset_days": 21,
        },
        {
            "first_name": "Clifford",
            "last_name": "Yamamoto",
            "email": "clifford.yamamoto@example.com",
            "phone": "(813) 555-0256",
            "date_of_birth": date(1962, 8, 30),
            "zip_code": "33602",
            "street_address": "415 Bayshore Boulevard",
            "preferred_contact_method": "email",
            "product_lines_of_interest": ["medicare_advantage"],
            "status": LeadStatus.REJECTED,
            "owner_local_part": "agent.two",
            "rejection_reason": "Not yet Medicare-eligible — follow up at 65.",
            "created_at_offset_days": 26,
        },
    ],
    "florida-family-planning": [
        {
            "first_name": "Bianca",
            "last_name": "Castro",
            "email": "bianca.castro@example.com",
            "phone": "(813) 555-0301",
            "date_of_birth": date(1990, 5, 12),
            "zip_code": "33602",
            "street_address": "300 Channelside Drive",
            "preferred_contact_method": "text",
            "product_lines_of_interest": ["term_life"],
            "status": LeadStatus.WORKING,
            "owner_local_part": "agent.one",
            "rejection_reason": None,
            "created_at_offset_days": 5,
        },
        {
            "first_name": "Andre",
            "last_name": "Solomon",
            "email": "andre.solomon@example.com",
            "phone": "(904) 555-0312",
            "date_of_birth": date(1978, 9, 3),
            "zip_code": "32202",
            "street_address": None,
            "preferred_contact_method": "email",
            "product_lines_of_interest": ["whole_life"],
            "status": LeadStatus.WORKING,
            "owner_local_part": "agent.two",
            "rejection_reason": None,
            "created_at_offset_days": 10,
        },
        {
            "first_name": "Renata",
            "last_name": "Oliveira",
            "email": "renata.oliveira@example.com",
            "phone": "(727) 555-0323",
            "date_of_birth": date(1985, 1, 28),
            "zip_code": "33701",
            "street_address": "120 Beach Drive Northeast",
            "preferred_contact_method": "phone",
            "product_lines_of_interest": ["health"],
            "status": LeadStatus.QUALIFIED,
            "owner_local_part": "agent.one",
            "rejection_reason": None,
            "created_at_offset_days": 14,
        },
        {
            "first_name": "Felix",
            "last_name": "Nordquist",
            "email": "felix.nordquist@example.com",
            "phone": "(954) 555-0334",
            "date_of_birth": date(1969, 11, 19),
            "zip_code": "33301",
            "street_address": "25 Las Olas Boulevard",
            "preferred_contact_method": "email",
            "product_lines_of_interest": ["critical_illness", "whole_life"],
            "status": LeadStatus.QUALIFIED,
            "owner_local_part": "agent.two",
            "rejection_reason": None,
            "created_at_offset_days": 18,
        },
        {
            "first_name": "Camila",
            "last_name": "Reyes",
            "email": "camila.reyes@example.com",
            "phone": "(305) 555-0345",
            "date_of_birth": date(2003, 4, 6),
            "zip_code": "33139",
            "street_address": None,
            "preferred_contact_method": "text",
            "product_lines_of_interest": ["term_life"],
            "status": LeadStatus.REJECTED,
            "owner_local_part": "agent.one",
            "rejection_reason": "Duplicate of an existing household policy.",
            "created_at_offset_days": 22,
        },
        {
            "first_name": "Hassan",
            "last_name": "Abdullah",
            "email": "hassan.abdullah@example.com",
            "phone": "(561) 555-0356",
            "date_of_birth": date(1995, 7, 24),
            "zip_code": "33401",
            "street_address": "78 Clematis Street",
            "preferred_contact_method": "phone",
            "product_lines_of_interest": ["health"],
            "status": LeadStatus.REJECTED,
            "owner_local_part": "agent.two",
            "rejection_reason": "No longer interested — declined to proceed.",
            "created_at_offset_days": 27,
        },
    ],
}


def demo_tenants() -> tuple[tuple[str, str], ...]:
    """Return the (slug, display name) pairs for the demo tenants."""
    return DEMO_TENANTS


def demo_users_for(tenant_slug: str) -> tuple[tuple[str, Role, str], ...]:
    """Return the (email, role, tenant_slug) tuples for one tenant's personas.

    Username equals email, so the first element doubles as both. The email is
    built from each template's local part and the tenant's email domain, read
    from the tenant registry.
    """
    domain = tenant_by_slug(tenant_slug).email_domain
    return tuple(
        (f"{local_part}@{domain}", role, tenant_slug)
        for local_part, role in TENANT_USER_TEMPLATES
    )


def demo_user_specs() -> tuple[tuple[str, Role, Optional[str]], ...]:
    """Return a flat (email==username, role, tenant_slug | None) tuple per user.

    This is the whole nine-persona matrix: four per-tenant personas for each of
    the two tenants, then the one tenantless platform admin (tenant_slug None).
    """
    specs: list[tuple[str, Role, Optional[str]]] = []
    for tenant_slug, _display_name in DEMO_TENANTS:
        specs.extend(demo_users_for(tenant_slug))
    specs.append((PLATFORM_ADMIN_EMAIL, Role.PLATFORM_ADMIN, None))
    return tuple(specs)


# --- The idempotent async seed (insert-if-absent) ----------------------------


async def seed_tenant_data_keys(
    db: AsyncSession, tenant_ids: Iterable[uuid.UUID]
) -> int:
    """Mint one master-key-wrapped root key per tenant, insert-if-absent.

    For each tenant id that has no key row yet, generate a fresh random 32-byte
    root key, wrap it under ``settings.pii_master_key``, and add a
    ``TenantDataKey`` row. Returns the number of keys newly created.

    Insert-if-absent (never re-wrap): a tenant that already has a wrapped key is
    skipped, because the container re-seeds on every boot and overwriting the key
    would orphan all of that tenant's already-encrypted PII. The plaintext root
    key lives only in the local variable during wrapping; only the wrapped blob
    persists. Rows are added to the session here and flushed by the caller's
    single ``commit``.
    """
    tenant_ids = list(tenant_ids)
    if not tenant_ids:
        return 0

    existing_tenant_ids = set(
        (
            await db.execute(
                select(TenantDataKey.tenant_id).where(
                    TenantDataKey.tenant_id.in_(tenant_ids)
                )
            )
        )
        .scalars()
        .all()
    )

    keys_created = 0
    for tenant_id in tenant_ids:
        if tenant_id in existing_tenant_ids:
            continue
        root_key = os.urandom(ROOT_KEY_LENGTH_BYTES)
        wrapped_root_key = wrap_key(settings.pii_master_key, root_key)
        db.add(
            TenantDataKey(
                tenant_id=tenant_id,
                wrapped_root_key=wrapped_root_key,
            )
        )
        keys_created += 1
    return keys_created


async def seed_pii_demo_records(
    db: AsyncSession, slug_to_tenant_id: dict[str, uuid.UUID]
) -> int:
    """Insert the synthetic demo PII records into each tenant's `pii_demo` table.

    For each tenant, skips entirely if that tenant's `pii_demo` already holds any
    rows (count-based idempotency — the container re-seeds on every boot, and the
    records have no natural unique key to conflict on). Otherwise it encrypts each
    PII field via `encrypt_field`, computes the email (and phone) blind index over
    the normalized value via `compute_blind_index`, derives the plaintext
    `age_band` from the birth date, and `INSERT`s the row with raw SQL. Returns the
    total number of records newly inserted.

    The schema identifier is interpolated **only** from the registry (never user
    input), exactly like the `tenant_settings` seed; every value is a bound
    parameter. The per-tenant keys this resolves are read by `get_tenant_keys`
    through its **own** session, so the caller must have already committed the
    seeded `tenant_data_keys` before calling this — otherwise the key load (a
    separate session) cannot see them.
    """
    records_inserted = 0
    for tenant_slug, tenant_id in slug_to_tenant_id.items():
        config = tenant_by_slug(tenant_slug)
        existing_count = (
            await db.execute(
                text(f"SELECT COUNT(*) FROM {config.schema_name}.pii_demo")
            )
        ).scalar_one()
        if existing_count > 0:
            continue

        for demo_record in DEMO_PII_RECORDS.get(tenant_slug, []):
            email_encrypted = await encrypt_field(tenant_id, demo_record["email"])
            email_blind_index = await compute_blind_index(
                tenant_id, normalize_email(demo_record["email"])
            )
            date_of_birth_encrypted = await encrypt_field(
                tenant_id, demo_record["date_of_birth"].isoformat()
            )
            age_band = age_band_for(demo_record["date_of_birth"])

            phone_encrypted = None
            phone_blind_index = None
            if demo_record["phone"] is not None:
                phone_encrypted = await encrypt_field(
                    tenant_id, demo_record["phone"]
                )
                phone_blind_index = await compute_blind_index(
                    tenant_id, normalize_phone(demo_record["phone"])
                )

            mock_medicare_id_encrypted = None
            if demo_record["mock_medicare_id"] is not None:
                mock_medicare_id_encrypted = await encrypt_field(
                    tenant_id, demo_record["mock_medicare_id"]
                )

            await db.execute(
                text(
                    f"INSERT INTO {config.schema_name}.pii_demo "
                    "(id, display_name, email_encrypted, email_blind_index, "
                    "phone_encrypted, phone_blind_index, date_of_birth_encrypted, "
                    "age_band, mock_medicare_id_encrypted) "
                    "VALUES (:id, :display_name, :email_encrypted, "
                    ":email_blind_index, :phone_encrypted, :phone_blind_index, "
                    ":date_of_birth_encrypted, :age_band, "
                    ":mock_medicare_id_encrypted)"
                ),
                {
                    "id": uuid.uuid4(),
                    "display_name": demo_record["display_name"],
                    "email_encrypted": email_encrypted,
                    "email_blind_index": email_blind_index,
                    "phone_encrypted": phone_encrypted,
                    "phone_blind_index": phone_blind_index,
                    "date_of_birth_encrypted": date_of_birth_encrypted,
                    "age_band": age_band,
                    "mock_medicare_id_encrypted": mock_medicare_id_encrypted,
                },
            )
            records_inserted += 1
    return records_inserted


async def seed_shared_historical_leads(
    db: AsyncSession, slug_to_tenant_id: dict[str, uuid.UUID]
) -> int:
    """Insert the shared read-only historical leads into each tenant's `leads` table.

    For each tenant, skips entirely if that tenant's `leads` already holds any
    shared-baseline row (`demo_session_id IS NULL`) — count-based idempotency, the
    same shape `seed_pii_demo_records` uses, because the container re-seeds on every
    boot and these rows have no natural unique key to conflict on. Scoping the count
    to `demo_session_id IS NULL` keeps it from being defeated by a visitor's own
    session-tagged rows in the shared container (those are `NOT NULL`). Otherwise it
    resolves each row's owner (`agent.one` / `agent.two`) to a seeded user id, encrypts
    every PII field via `encrypt_field`, computes the email/phone blind indexes over the
    normalized value, derives the plaintext `age_band`, backdates `created_at` by the
    row's offset, and `INSERT`s the row as a shared (`demo_session_id IS NULL`) lead
    with its `status` / owner / `rejection_reason`. Returns the total newly inserted.

    The schema identifier is interpolated **only** from the registry (never user
    input), exactly like `seed_pii_demo_records`; every value is a bound parameter.
    The per-tenant keys this resolves are read by `get_tenant_keys` through its **own**
    session, so the caller must have already committed the seeded `tenant_data_keys`
    before calling this — the same ordering `seed_pii_demo_records` relies on.
    """
    boot_time = datetime.now(timezone.utc)
    leads_inserted = 0
    for tenant_slug, tenant_id in slug_to_tenant_id.items():
        config = tenant_by_slug(tenant_slug)
        existing_count = (
            await db.execute(
                text(
                    f"SELECT COUNT(*) FROM {config.schema_name}.leads "
                    "WHERE demo_session_id IS NULL"
                )
            )
        ).scalar_one()
        if existing_count > 0:
            continue

        # Resolve each historical row's owner (agent.one / agent.two) to the seeded
        # user's id and email-style username. The usernames are built from the
        # registry email domain, exactly as `demo_users_for` builds them, so the
        # lookup can never disagree with the seeded personas.
        owner_username_by_local_part = {
            local_part: f"{local_part}@{config.email_domain}"
            for local_part in ("agent.one", "agent.two")
        }
        owner_id_by_username = {
            username: user_id
            for user_id, username in (
                await db.execute(
                    select(User.id, User.username).where(
                        User.username.in_(owner_username_by_local_part.values())
                    )
                )
            ).all()
        }

        for historical_lead in SHARED_HISTORICAL_LEADS.get(tenant_slug, []):
            email_encrypted = await encrypt_field(
                tenant_id, historical_lead["email"]
            )
            email_blind_index = await compute_blind_index(
                tenant_id, normalize_email(historical_lead["email"])
            )
            phone_encrypted = await encrypt_field(
                tenant_id, historical_lead["phone"]
            )
            phone_blind_index = await compute_blind_index(
                tenant_id, normalize_phone(historical_lead["phone"])
            )
            date_of_birth_encrypted = await encrypt_field(
                tenant_id, historical_lead["date_of_birth"].isoformat()
            )
            age_band = age_band_for(historical_lead["date_of_birth"])

            street_address_encrypted = None
            if historical_lead["street_address"] is not None:
                street_address_encrypted = await encrypt_field(
                    tenant_id, historical_lead["street_address"]
                )

            owner_username = owner_username_by_local_part[
                historical_lead["owner_local_part"]
            ]
            owner_user_id = owner_id_by_username[owner_username]
            created_at = boot_time - timedelta(
                days=historical_lead["created_at_offset_days"]
            )

            # The lead's id and correlation_id are minted here and reused by both
            # the lead INSERT below and the synthesized event trail, so every event
            # carries the lead's own trace id — exactly as the live writers reuse
            # the row's `correlation_id` across `lead.created` and every later event.
            lead_id = uuid.uuid4()
            correlation_id = uuid.uuid4()

            await db.execute(
                text(
                    f"INSERT INTO {config.schema_name}.leads "
                    "(id, first_name, last_name, email_encrypted, "
                    "email_blind_index, phone_encrypted, phone_blind_index, "
                    "date_of_birth_encrypted, age_band, zip_code, "
                    "street_address_encrypted, product_lines_of_interest, "
                    "preferred_contact_method, rejection_reason, lead_source, "
                    "status, owner_user_id, owner_username, correlation_id, "
                    "demo_session_id, created_at, updated_at) "
                    "VALUES (:id, :first_name, :last_name, :email_encrypted, "
                    ":email_blind_index, :phone_encrypted, :phone_blind_index, "
                    ":date_of_birth_encrypted, :age_band, :zip_code, "
                    ":street_address_encrypted, :product_lines_of_interest, "
                    ":preferred_contact_method, :rejection_reason, :lead_source, "
                    ":status, :owner_user_id, :owner_username, :correlation_id, "
                    ":demo_session_id, :created_at, :created_at)"
                ),
                {
                    "id": lead_id,
                    "first_name": historical_lead["first_name"],
                    "last_name": historical_lead["last_name"],
                    "email_encrypted": email_encrypted,
                    "email_blind_index": email_blind_index,
                    "phone_encrypted": phone_encrypted,
                    "phone_blind_index": phone_blind_index,
                    "date_of_birth_encrypted": date_of_birth_encrypted,
                    "age_band": age_band,
                    "zip_code": historical_lead["zip_code"],
                    "street_address_encrypted": street_address_encrypted,
                    "product_lines_of_interest": historical_lead[
                        "product_lines_of_interest"
                    ],
                    "preferred_contact_method": historical_lead[
                        "preferred_contact_method"
                    ],
                    "rejection_reason": historical_lead["rejection_reason"],
                    "lead_source": LeadSource.AGENT_ENTERED.value,
                    "status": historical_lead["status"].value,
                    "owner_user_id": owner_user_id,
                    "owner_username": owner_username,
                    "correlation_id": correlation_id,
                    "demo_session_id": None,
                    "created_at": created_at,
                },
            )
            leads_inserted += 1

            # Synthesize this lead's status-derived event trail (P1.9 Epic 5) so a
            # baseline lead opens with a coherent, non-empty timeline that matches
            # its status — the same fan-out a live delivery would have produced.
            await _seed_lead_event_trail(
                db,
                schema_name=config.schema_name,
                tenant_id=tenant_id,
                lead_id=lead_id,
                correlation_id=correlation_id,
                status=historical_lead["status"],
                created_at=created_at,
            )
    return leads_inserted


def _synthesized_lead_events(
    status: LeadStatus, created_at: datetime
) -> list[tuple[EventType, datetime]]:
    """Return one baseline lead's status-derived `(event_type, occurred_at)` trail.

    The sequence mirrors the live lifecycle writers, oldest-first: `lead.created`
    always (at the lead's backdated `created_at`); `+ lead.assigned` at +1h because
    every baseline lead is owned (it carries an `owner_local_part`); then the
    terminal `lead.qualified` / `lead.rejected` at +2h for a Qualified / Rejected
    lead. A Working lead stops after `lead.assigned`. Because `created_at` is days
    in the past, every stamp stays comfortably before now.
    """
    events: list[tuple[EventType, datetime]] = [
        (EventType.LEAD_CREATED, created_at),
        (EventType.LEAD_ASSIGNED, created_at + timedelta(hours=1)),
    ]
    if status is LeadStatus.QUALIFIED:
        events.append((EventType.LEAD_QUALIFIED, created_at + timedelta(hours=2)))
    elif status is LeadStatus.REJECTED:
        events.append((EventType.LEAD_REJECTED, created_at + timedelta(hours=2)))
    return events


async def _seed_lead_event_trail(
    db: AsyncSession,
    *,
    schema_name: str,
    tenant_id: uuid.UUID,
    lead_id: uuid.UUID,
    correlation_id: uuid.UUID,
    status: LeadStatus,
    created_at: datetime,
) -> None:
    """Insert one baseline lead's synthesized `outbox` + `processed_events` trail.

    For each status-derived event (`_synthesized_lead_events`): one `outbox` row —
    a fresh `event_id`, the lead's own `correlation_id`, `demo_session_id NULL`,
    `published_at = occurred_at` (so the timeline read derives a *terminal*
    reaction, not pending), and a payload of `{"entity_id": <lead id>}` plus
    `"entity_type": "lead"` on `lead.created` only (mirroring the live writers; the
    timeline read filters on `entity_id` alone). Then, for each consumer the catalog
    fans the event out to (`consumers_for_event_type`, registry-ordered), one
    `processed_events` row — the row's existence *is* `done` in the read-time
    derivation, `processed_at` = the event's `occurred_at` + 1 min, and a
    `result_summary` of `enrichment_result_summary(event_id)` for `enrichment.stub`
    (reused, never re-derived, so the seeded score equals a live delivery's) or
    NULL for `sync.logger`. Both writes use the schema-qualified raw `text()` INSERT
    idiom the surrounding seed uses — not the search-path-bound ORM `enqueue_event`,
    which would leave `published_at` NULL.
    """
    for event_type, occurred_at in _synthesized_lead_events(status, created_at):
        event_id = uuid.uuid4()
        payload: dict[str, str] = {"entity_id": str(lead_id)}
        if event_type is EventType.LEAD_CREATED:
            payload["entity_type"] = "lead"

        await db.execute(
            text(
                f"INSERT INTO {schema_name}.outbox "
                "(id, event_id, event_type, schema_version, tenant_id, "
                "correlation_id, causation_id, actor_user_id, actor_role, "
                "demo_session_id, payload, occurred_at, published_at) "
                "VALUES (:id, :event_id, :event_type, :schema_version, "
                ":tenant_id, :correlation_id, NULL, NULL, NULL, NULL, "
                "CAST(:payload AS jsonb), :occurred_at, :published_at)"
            ),
            {
                "id": uuid.uuid4(),
                "event_id": event_id,
                "event_type": event_type.value,
                "schema_version": SCHEMA_VERSION,
                "tenant_id": tenant_id,
                "correlation_id": correlation_id,
                "payload": json.dumps(payload),
                "occurred_at": occurred_at,
                "published_at": occurred_at,
            },
        )

        processed_at = occurred_at + timedelta(minutes=1)
        for consumer_name in consumers_for_event_type(event_type.value):
            result_summary = (
                enrichment_result_summary(event_id)
                if consumer_name == ENRICHMENT_STUB
                else None
            )
            await db.execute(
                text(
                    f"INSERT INTO {schema_name}.processed_events "
                    "(id, consumer_name, event_id, tenant_id, event_type, "
                    "correlation_id, processed_at, result_summary) "
                    "VALUES (:id, :consumer_name, :event_id, :tenant_id, "
                    ":event_type, :correlation_id, :processed_at, "
                    ":result_summary)"
                ),
                {
                    "id": uuid.uuid4(),
                    "consumer_name": consumer_name,
                    "event_id": event_id,
                    "tenant_id": tenant_id,
                    "event_type": event_type.value,
                    "correlation_id": correlation_id,
                    "processed_at": processed_at,
                    "result_summary": result_summary,
                },
            )


async def seed(db: AsyncSession) -> None:
    """Insert any missing demo tenants and users, then commit once.

    Idempotent: existing tenant slugs and usernames are read first, and only the
    absent rows are added. Logs how many of each were inserted versus already
    present so the boot logs show the seed result.
    """
    # --- Tenants: read what already exists, insert what is missing. ---
    existing_tenant_slugs = set(
        (await db.execute(select(Tenant.slug))).scalars().all()
    )
    slug_to_tenant_id: dict[str, uuid.UUID] = {}
    tenants_inserted = 0
    for slug, display_name in DEMO_TENANTS:
        if slug in existing_tenant_slugs:
            continue
        tenant_id = uuid.uuid4()
        config = tenant_by_slug(slug)
        db.add(
            Tenant(
                id=tenant_id,
                slug=slug,
                name=display_name,
                schema_name=config.schema_name,
                db_role=config.db_role,
            )
        )
        slug_to_tenant_id[slug] = tenant_id
        tenants_inserted += 1

    # Load the tenants that were already present so users in those tenants can be
    # linked to the right tenant_id, and so their schema_name / db_role can be
    # backfilled from the registry. Loading full ORM objects (rather than just
    # slug + id) lets us set the columns in place; the mutations flush on the
    # single commit below. Always setting to the registry value keeps this
    # idempotent, and orphan rows never appear here because already_present_slugs
    # is built from the registry-derived DEMO_TENANTS.
    already_present_slugs = [
        slug for slug, _name in DEMO_TENANTS if slug in existing_tenant_slugs
    ]
    if already_present_slugs:
        present_tenants = (
            await db.execute(
                select(Tenant).where(Tenant.slug.in_(already_present_slugs))
            )
        ).scalars().all()
        for tenant in present_tenants:
            config = tenant_by_slug(tenant.slug)
            tenant.schema_name = config.schema_name
            tenant.db_role = config.db_role
            slug_to_tenant_id[tenant.slug] = tenant.id

    # --- Users: read existing usernames, insert the missing personas. ---
    existing_usernames = set(
        (await db.execute(select(User.username))).scalars().all()
    )
    password_hash = hash_password(settings.seed_user_password)
    users_inserted = 0
    for email, role, tenant_slug in demo_user_specs():
        if email in existing_usernames:
            continue
        tenant_id = (
            slug_to_tenant_id[tenant_slug] if tenant_slug is not None else None
        )
        db.add(
            User(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                username=email,
                email=email,
                password_hash=password_hash,
                role=role,
            )
        )
        users_inserted += 1

    # --- Tenant settings: one distinct row per tenant, in its own schema. ---
    # slug_to_tenant_id now covers both inserted and already-present tenants, so
    # each registry tenant has a known id. The schema identifier comes only from
    # the registry (never user input); the values are bound parameters. The
    # INSERT ... ON CONFLICT (tenant_id) DO NOTHING makes a re-seed idempotent.
    settings_inserted = 0
    for tenant_slug, tenant_id in slug_to_tenant_id.items():
        config = tenant_by_slug(tenant_slug)
        demo_settings = DEMO_TENANT_SETTINGS[tenant_slug]
        brand_logo_url = (
            f"https://assets.policyflow.example/{config.schema_name}/logo.svg"
        )
        # The brand colour comes from the registry (the single source of truth),
        # so the seeded row can never diverge from `/api/tenants`.
        result = await db.execute(
            text(
                f"INSERT INTO {config.schema_name}.tenant_settings "
                "(tenant_id, brand_primary_color, brand_logo_url, "
                "welcome_message) "
                "VALUES (:tenant_id, :brand_primary_color, :brand_logo_url, "
                ":welcome_message) "
                "ON CONFLICT (tenant_id) DO NOTHING"
            ),
            {
                "tenant_id": tenant_id,
                "brand_primary_color": config.brand_primary_color,
                "brand_logo_url": brand_logo_url,
                "welcome_message": demo_settings["welcome_message"],
            },
        )
        settings_inserted += result.rowcount or 0

    # --- Data keys: one master-key-wrapped root key per tenant, insert-if-
    # absent. slug_to_tenant_id covers both inserted and already-present tenants,
    # so this is the full set of registry tenant ids.
    keys_inserted = await seed_tenant_data_keys(db, slug_to_tenant_id.values())

    # Commit the tenants, users, settings, and data keys before seeding the demo
    # PII records. `seed_pii_demo_records` encrypts each field, and the per-tenant
    # key it needs is read by `get_tenant_keys` through its **own** session — which
    # cannot see the just-added `tenant_data_keys` rows until this commit lands.
    await db.commit()

    # --- Demo PII records: synthetic encrypted rows per tenant, in each tenant's
    # own `pii_demo` table. They encrypt on write and so need the data keys above
    # to be durable (the key load runs in its own session), which the commit above
    # guarantees. The boot seed seeds no per-session New-queue `leads` rows: P1.8
    # Epic 7 moved that set to per-session instantiation (`SESSION_LEAD_TEMPLATES`,
    # stamped session-tagged on `assume-persona`). It does seed the shared-historical
    # read-only `leads` set below.
    pii_demo_rows_inserted = await seed_pii_demo_records(db, slug_to_tenant_id)

    # --- Shared historical leads: the read-only `demo_session_id IS NULL` baseline
    # (worked/qualified/rejected, owned) per tenant, so lists and dashboards render
    # non-trivially from seed alone (P1.8 Epic 8). Like `seed_pii_demo_records` it
    # encrypts on write (needs the durable data keys above) and resolves each row's
    # owner to a seeded user committed above — both guaranteed by the commit above.
    historical_leads_inserted = await seed_shared_historical_leads(
        db, slug_to_tenant_id
    )
    await db.commit()

    total_tenants = len(DEMO_TENANTS)
    total_users = len(demo_user_specs())
    logger.info(
        "seed complete: tenants inserted=%d already-present=%d; "
        "users inserted=%d already-present=%d; settings rows inserted=%d; "
        "data keys inserted=%d; pii_demo rows inserted=%d; "
        "historical leads inserted=%d",
        tenants_inserted,
        total_tenants - tenants_inserted,
        users_inserted,
        total_users - users_inserted,
        settings_inserted,
        keys_inserted,
        pii_demo_rows_inserted,
        historical_leads_inserted,
    )


def run() -> None:
    """Open a session and drive the async seed to completion.

    The thin sync wrapper the container entrypoint calls via
    ``python -m app.seed`` after migrations and before serving traffic.
    """

    async def main() -> None:
        async with session_factory() as db:
            await seed(db)

    asyncio.run(main())


if __name__ == "__main__":
    run()
