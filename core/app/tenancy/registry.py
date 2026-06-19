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
class ProductLine:
    """One insurance product line a tenant offers, as static registry data.

    ``key`` is the snake_case stored vocabulary (matching the ``LeadSource``
    naming): both intake forms validate a submitted lead's product line against
    its tenant's keys, and the seed and reads carry the key verbatim. ``label``
    is the human-facing display string the intake forms and lead views render.
    Renaming a key is a cross-tenant contract change, so the keys are fixed here.
    """

    key: str
    label: str


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
    brand_primary_color: str
    product_lines: tuple[ProductLine, ...]


# The two demo tenants. Slugs and display names match the seed's current demo
# tenants verbatim; email domains match the seed's current per-tenant domains.
# `brand_primary_color` holds the Guide §2.3 authoritative brand primaries — the
# single source of truth for each tenant's `--primary`. The seed derives its
# `tenant_settings` colors from these values in Epic 22 (until then the seed keeps
# its own placeholder colors, so the two intentionally diverge).
SUNSHINE = TenantConfig(
    slug="sunshine-senior-benefits",
    display_name="Sunshine Senior Benefits",
    schema_name="sunshine",
    db_role="tenant_sunshine",
    email_domain="sunshine.example",
    brand_primary_color="#9C4A1E",
    product_lines=(
        ProductLine(key="medicare_advantage", label="Medicare Advantage"),
        ProductLine(key="medicare_supplement", label="Medicare Supplement"),
        ProductLine(key="final_expense", label="Final Expense"),
        ProductLine(key="dental_vision_hearing", label="Dental, Vision & Hearing"),
    ),
)

FLORIDA = TenantConfig(
    slug="florida-family-planning",
    display_name="Florida Family Planning",
    schema_name="florida",
    db_role="tenant_florida",
    email_domain="florida.example",
    brand_primary_color="#0F6A72",
    product_lines=(
        ProductLine(key="term_life", label="Term Life Insurance"),
        ProductLine(key="whole_life", label="Whole Life Insurance"),
        ProductLine(key="health", label="Health Insurance"),
        ProductLine(key="critical_illness", label="Critical Illness"),
    ),
)

# Every tenant, in seed and migration order.
TENANTS: tuple[TenantConfig, ...] = (SUNSHINE, FLORIDA)

# The platform read-role. Epic 2's migration grants it cross-tenant read access
# so Platform Admins can read every tenant's schema without belonging to any one
# tenant role.
PLATFORM_ROLE = "platform_reader"

# The dedicated audit-writer role. Phase P1.4 Epic 2's `0007` migration creates
# it and grants it INSERT+SELECT on the audit stores; the audit-emit service
# (Epic 4) sets this role before writing append-only records.
AUDIT_WRITER_ROLE = "audit_writer"

# The dedicated outbox-relay role. Phase P1.5 Epic 2's `0008` migration creates
# it and grants it SELECT+UPDATE on each tenant's `outbox` table; the polling
# relay (Epic 5) sets this role to read unpublished rows and stamp `published_at`
# — never INSERT or DELETE, mirroring the tight `audit_writer` grant shape.
OUTBOX_RELAY_ROLE = "outbox_relay"

# The dedicated event-consumer role. Phase P1.5 Epic 2's `0008` migration creates
# it and grants it INSERT+SELECT on each tenant's `processed_events` table; the
# stub consumers (Epic 6) set this role to dedupe and record their processed
# events — never UPDATE or DELETE, mirroring the tight `audit_writer` grant shape.
EVENT_CONSUMER_ROLE = "event_consumer"


def is_known_schema(schema_name: str) -> bool:
    """Return whether ``schema_name`` matches a registered tenant's schema.

    The registry is the single source of truth for which schemas serve tenants.
    Confirming a looked-up schema name against it before that name is interpolated
    into a schema-qualified ``INSERT`` is the whitelist guard that makes the
    interpolation safe — a schema name cannot be passed as a bound parameter, so an
    unrecognized name must never reach the statement text.

    This is the schema-only sibling of `app.tenancy.scoping.is_known_tenant_pair`,
    kept here in the dependency-free registry leaf so the Epic 4 audit-emit service
    can import the guard **without** importing `scoping.py`. That deliberately
    avoids a circular import in Epic 6, where `scoping.py` starts calling the audit
    service (a `scoping → service → scoping` cycle would break). The service writes
    as `audit_writer`, not the tenant's `db_role`, so validating the schema alone is
    the right shape — there is no need for the pair check `is_known_tenant_pair`.
    """
    return any(tenant.schema_name == schema_name for tenant in TENANTS)


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


def tenant_by_schema(schema_name: str) -> TenantConfig:
    """Return the tenant configuration for ``schema_name``.

    The schema-keyed sibling of ``tenant_by_slug``: an authenticated request is
    scoped to its tenant by ``search_path`` (not by slug), so the lead intake
    handler resolves the caller's product-line keys from the active schema name
    rather than a slug. Raises ``KeyError`` if no tenant has that schema, so an
    unrecognized schema fails loudly rather than returning a silent ``None``.
    """
    for tenant in TENANTS:
        if tenant.schema_name == schema_name:
            return tenant
    raise KeyError(schema_name)
