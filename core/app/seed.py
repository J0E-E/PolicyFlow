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
import uuid
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .auth.passwords import hash_password
from .config import settings
from .db import session_factory
from .models import Role, Tenant, User
from .tenancy.registry import TENANTS, tenant_by_slug

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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

    await db.commit()

    total_tenants = len(DEMO_TENANTS)
    total_users = len(demo_user_specs())
    logger.info(
        "seed complete: tenants inserted=%d already-present=%d; "
        "users inserted=%d already-present=%d; settings rows inserted=%d",
        tenants_inserted,
        total_tenants - tenants_inserted,
        users_inserted,
        total_users - users_inserted,
        settings_inserted,
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
