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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth.passwords import hash_password
from .config import settings
from .db import session_factory
from .models import Role, Tenant, User

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# --- The persona spec (pure data, no DB) -------------------------------------
#
# These module-level structures describe the demo data declaratively so the
# matrix can be unit-tested without touching a database.

# (slug, display name) for each demo tenant.
DEMO_TENANTS: tuple[tuple[str, str], ...] = (
    ("sunshine-senior-benefits", "Sunshine Senior Benefits"),
    ("florida-family-planning", "Florida Family Planning"),
)

# Per-tenant email domain, keyed by tenant slug. Each tenant's users live at
# this domain (e.g. agent.one@sunshine.example).
TENANT_EMAIL_DOMAINS: dict[str, str] = {
    "sunshine-senior-benefits": "sunshine.example",
    "florida-family-planning": "florida.example",
}

# The local part (before the @) and role of every per-tenant persona.
TENANT_USER_TEMPLATES: tuple[tuple[str, Role], ...] = (
    ("agent.one", Role.AGENT),
    ("agent.two", Role.AGENT),
    ("admin", Role.TENANT_ADMIN),
    ("readonly", Role.READ_ONLY),
)

# The single tenantless platform administrator (tenant_id stays None).
PLATFORM_ADMIN_EMAIL = "platform.admin@policyflow.example"


def demo_tenants() -> tuple[tuple[str, str], ...]:
    """Return the (slug, display name) pairs for the demo tenants."""
    return DEMO_TENANTS


def demo_users_for(tenant_slug: str) -> tuple[tuple[str, Role, str], ...]:
    """Return the (email, role, tenant_slug) tuples for one tenant's personas.

    Username equals email, so the first element doubles as both. The email is
    built from each template's local part and the tenant's email domain.
    """
    domain = TENANT_EMAIL_DOMAINS[tenant_slug]
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
        db.add(Tenant(id=tenant_id, slug=slug, name=display_name))
        slug_to_tenant_id[slug] = tenant_id
        tenants_inserted += 1

    # Query back the ids of tenants that were already present, so users in those
    # tenants can be linked to the right tenant_id.
    already_present_slugs = [
        slug for slug, _name in DEMO_TENANTS if slug in existing_tenant_slugs
    ]
    if already_present_slugs:
        present_rows = (
            await db.execute(
                select(Tenant.slug, Tenant.id).where(
                    Tenant.slug.in_(already_present_slugs)
                )
            )
        ).all()
        for slug, tenant_id in present_rows:
            slug_to_tenant_id[slug] = tenant_id

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

    await db.commit()

    total_tenants = len(DEMO_TENANTS)
    total_users = len(demo_user_specs())
    logger.info(
        "seed complete: tenants inserted=%d already-present=%d; "
        "users inserted=%d already-present=%d",
        tenants_inserted,
        total_tenants - tenants_inserted,
        users_inserted,
        total_users - users_inserted,
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
