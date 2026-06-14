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
import logging
import os
import uuid
from datetime import date
from typing import Iterable, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .auth.passwords import hash_password
from .config import settings
from .db import session_factory
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
# presentation content (brand colour, logo, welcome message), so they live here
# in the seed rather than in the tenant registry, which is reserved for isolation
# config the migration imports. The seed writes one row per tenant into that
# tenant's own `tenant_settings` table. The logo URL is a distinct per-tenant
# placeholder built from the registry schema name.
DEMO_TENANT_SETTINGS: dict[str, dict[str, str]] = {
    "sunshine-senior-benefits": {
        "brand_primary_color": "#F5A623",
        "welcome_message": (
            "Welcome to Sunshine Senior Benefits — Medicare coverage made "
            "simple."
        ),
    },
    "florida-family-planning": {
        "brand_primary_color": "#2E86C1",
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
                "brand_primary_color": demo_settings["brand_primary_color"],
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

    # --- Demo PII records: a couple of synthetic rows per tenant, encrypted on
    # write, in each tenant's own `pii_demo` table. Committed separately after the
    # data keys above are durable so the key load can resolve them.
    pii_demo_rows_inserted = await seed_pii_demo_records(db, slug_to_tenant_id)
    await db.commit()

    total_tenants = len(DEMO_TENANTS)
    total_users = len(demo_user_specs())
    logger.info(
        "seed complete: tenants inserted=%d already-present=%d; "
        "users inserted=%d already-present=%d; settings rows inserted=%d; "
        "data keys inserted=%d; pii_demo rows inserted=%d",
        tenants_inserted,
        total_tenants - tenants_inserted,
        users_inserted,
        total_users - users_inserted,
        settings_inserted,
        keys_inserted,
        pii_demo_rows_inserted,
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
