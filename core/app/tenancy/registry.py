"""The single source of truth for which schema and DB role serve each tenant.

Phase P1.2 builds schema-per-tenant isolation. Every later epic — the migration
that creates the schemas and roles, the seed that fills the tenant columns, the
per-request scoping dependency — needs one agreed mapping of *which schema and
DB role serve which tenant*. If the migration and the seed each kept their own
copy of that mapping, they could silently drift and isolation would break.

This module is that single source of truth, held as **pure data, no database**:
a frozen ``TenantConfig`` per tenant plus the platform read-role constant. The
seed reads every per-tenant value from here, so there is exactly one place that
defines a tenant.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TenantConfig:
    """The full, immutable configuration of one tenant.

    ``schema_name`` and ``db_role`` are explicit strings rather than derived
    from ``slug`` because slugs contain hyphens (e.g. ``sunshine-senior-
    benefits``), which are invalid as bare SQL identifiers. Spelling them out
    keeps the migration's ``CREATE SCHEMA`` / ``CREATE ROLE`` identifiers valid
    and unambiguous.
    """

    slug: str
    display_name: str
    schema_name: str
    db_role: str
    email_domain: str


# The two demo tenants. Slugs and display names match the seed's current demo
# tenants verbatim; email domains match the seed's current per-tenant domains.
SUNSHINE = TenantConfig(
    slug="sunshine-senior-benefits",
    display_name="Sunshine Senior Benefits",
    schema_name="sunshine",
    db_role="tenant_sunshine",
    email_domain="sunshine.example",
)

FLORIDA = TenantConfig(
    slug="florida-family-planning",
    display_name="Florida Family Planning",
    schema_name="florida",
    db_role="tenant_florida",
    email_domain="florida.example",
)

# Every tenant, in seed and migration order.
TENANTS: tuple[TenantConfig, ...] = (SUNSHINE, FLORIDA)

# The platform read-role. Epic 2's migration grants it cross-tenant read access
# so Platform Admins can read every tenant's schema without belonging to any one
# tenant role.
PLATFORM_ROLE = "platform_reader"


def tenant_by_slug(slug: str) -> TenantConfig:
    """Return the tenant configuration for ``slug``.

    Raises ``KeyError`` if no tenant has that slug — matching the dictionary
    lookup behavior the seed relies on, so an unknown slug fails loudly rather
    than returning a silent ``None``.
    """
    for tenant in TENANTS:
        if tenant.slug == slug:
            return tenant
    raise KeyError(slug)
