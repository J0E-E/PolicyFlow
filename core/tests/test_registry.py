"""Unit tests for the tenant registry — the single source of truth for tenancy.

Pure unit tests — no DB, no Docker — matching the no-Docker style of
`test_seed.py`. The registry is plain frozen data, so every assertion reads it
directly: the tenant count and slugs, the SQL-identifier validity of each
schema/role, the platform read-role constant, the email domains, and the
`tenant_by_slug` lookup (including its `KeyError` on an unknown slug) and the
frozen-dataclass guarantee.
"""

import re

import pytest
from dataclasses import FrozenInstanceError

from app.tenancy.registry import (
    AUDIT_WRITER_ROLE,
    FLORIDA,
    PLATFORM_ROLE,
    SUNSHINE,
    TENANTS,
    TenantConfig,
    tenant_by_slug,
)

# A bare (unquoted) SQL identifier: a letter or underscore, then letters,
# digits, or underscores. Both schema names and role names must satisfy this so
# the migration can interpolate them without quoting.
BARE_SQL_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")

# A 6-digit hex color with a leading `#` — the shape every tenant's authoritative
# brand primary must take.
HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")

# A snake_case product-line key: lowercase letters, digits, and underscores only,
# starting with a letter. The keys are the stored vocabulary (matching the
# `LeadSource` style), so each must satisfy this.
SNAKE_CASE_KEY = re.compile(r"^[a-z][a-z0-9_]*$")

# The exact product-line catalog each tenant must carry, keyed by slug, as
# `(key, label)` pairs in registry order. Hand-built here on purpose — separate
# from the registry — so a drift in either side is caught. Renaming a key is a
# cross-epic contract change (Epics 7/10 validate against these keys, 18/19 render
# the labels, 16's duplicate-bait seed uses them).
EXPECTED_PRODUCT_LINES: dict[str, tuple[tuple[str, str], ...]] = {
    "sunshine-senior-benefits": (
        ("medicare_advantage", "Medicare Advantage"),
        ("medicare_supplement", "Medicare Supplement"),
        ("final_expense", "Final Expense"),
        ("dental_vision_hearing", "Dental, Vision & Hearing"),
    ),
    "florida-family-planning": (
        ("term_life", "Term Life Insurance"),
        ("whole_life", "Whole Life Insurance"),
        ("health", "Health Insurance"),
        ("critical_illness", "Critical Illness"),
    ),
}


def test_exactly_two_tenants_with_expected_slugs():
    """The registry defines exactly the two named demo tenants."""
    assert len(TENANTS) == 2
    slugs = {tenant.slug for tenant in TENANTS}
    assert slugs == {"sunshine-senior-benefits", "florida-family-planning"}


def test_schema_names_and_roles_are_valid_bare_sql_identifiers():
    """Every schema name and DB role is usable as an unquoted SQL identifier."""
    for tenant in TENANTS:
        assert BARE_SQL_IDENTIFIER.match(tenant.schema_name)
        assert BARE_SQL_IDENTIFIER.match(tenant.db_role)


def test_schema_names_and_roles_are_distinct_across_tenants():
    """No two tenants share a schema name or a DB role."""
    schema_names = [tenant.schema_name for tenant in TENANTS]
    db_roles = [tenant.db_role for tenant in TENANTS]
    assert len(schema_names) == len(set(schema_names))
    assert len(db_roles) == len(set(db_roles))


def test_platform_role_is_the_expected_constant():
    """The platform read-role constant matches the confirmed identifier."""
    assert PLATFORM_ROLE == "platform_reader"


def test_audit_writer_role_is_the_expected_constant():
    """The audit-writer role constant matches the confirmed identifier and is a
    valid bare SQL identifier (Epic 2's `0007` migration interpolates it)."""
    assert AUDIT_WRITER_ROLE == "audit_writer"
    assert BARE_SQL_IDENTIFIER.match(AUDIT_WRITER_ROLE)


def test_every_tenant_has_a_non_empty_email_domain():
    """Each tenant carries an email domain its personas live at."""
    for tenant in TENANTS:
        assert tenant.email_domain


def test_every_tenant_has_a_well_formed_brand_primary_color():
    """Each tenant carries a `brand_primary_color` that is a 6-digit hex color."""
    for tenant in TENANTS:
        assert HEX_COLOR.match(tenant.brand_primary_color)


def test_brand_primary_colors_are_the_guide_authoritative_values():
    """The two brand primaries are exactly the Guide §2.3 authoritative values."""
    assert SUNSHINE.brand_primary_color == "#9C4A1E"
    assert FLORIDA.brand_primary_color == "#0F6A72"


def test_tenant_by_slug_returns_the_matching_config():
    """The lookup returns the exact config for each known slug."""
    assert tenant_by_slug("sunshine-senior-benefits") is SUNSHINE
    assert tenant_by_slug("florida-family-planning") is FLORIDA


def test_tenant_by_slug_raises_key_error_on_unknown_slug():
    """An unknown slug fails loudly with a KeyError, never a silent None."""
    with pytest.raises(KeyError):
        tenant_by_slug("does-not-exist")


def test_every_tenant_offers_at_least_one_product_line():
    """Each tenant carries a non-empty product-line catalog."""
    for tenant in TENANTS:
        assert len(tenant.product_lines) >= 1


def test_product_line_keys_are_snake_case_and_unique_within_a_tenant():
    """Within each tenant the keys are snake_case and distinct."""
    for tenant in TENANTS:
        keys = [product_line.key for product_line in tenant.product_lines]
        for key in keys:
            assert SNAKE_CASE_KEY.match(key)
        assert len(keys) == len(set(keys))


def test_product_line_catalogs_match_the_expected_constant():
    """Each tenant's catalog matches its hand-written `(key, label)` expectation."""
    for tenant in TENANTS:
        actual = tuple(
            (product_line.key, product_line.label)
            for product_line in tenant.product_lines
        )
        assert actual == EXPECTED_PRODUCT_LINES[tenant.slug]


# The product-line keys each tenant flags `requires_medicare_age` (P2.2 D4),
# hand-built here separate from the registry. Only Sunshine's two Medicare lines.
EXPECTED_MEDICARE_LINES: dict[str, set[str]] = {
    "sunshine-senior-benefits": {"medicare_advantage", "medicare_supplement"},
    "florida-family-planning": set(),
}

# The per-tenant pipeline config (P2.2 D13), hand-built separate from the registry.
EXPECTED_STAGE_LABELS: dict[str, dict[str, str]] = {
    "sunshine-senior-benefits": {
        "Qualified": "Needs Assessment",
        "Policy Active": "Enrolled",
    },
    "florida-family-planning": {
        "Quoted": "Proposal Sent",
        "Application Started": "App In Progress",
    },
}
EXPECTED_ENABLED_OPTIONAL: dict[str, set[str]] = {
    "sunshine-senior-benefits": {"Quoted", "Approved"},
    "florida-family-planning": {"Quoted"},
}
# The only stages a tenant may switch on — the optional set (P2.2 §5.1).
OPTIONAL_STAGE_VALUES = {"Quoted", "Approved"}


def test_requires_medicare_age_flags_only_the_expected_lines():
    """Each tenant flags `requires_medicare_age` on exactly its Medicare lines."""
    for tenant in TENANTS:
        flagged = {
            product_line.key
            for product_line in tenant.product_lines
            if product_line.requires_medicare_age
        }
        assert flagged == EXPECTED_MEDICARE_LINES[tenant.slug], tenant.slug


def test_stage_labels_match_the_expected_overrides():
    """Each tenant's stage-label overrides match the hand-written expectation."""
    for tenant in TENANTS:
        assert tenant.stage_labels == EXPECTED_STAGE_LABELS[tenant.slug], tenant.slug


def test_enabled_optional_stages_match_and_are_a_valid_subset():
    """Each tenant's enabled optional stages match expectation ⊆ the optional set."""
    for tenant in TENANTS:
        assert set(tenant.enabled_optional_stages) == EXPECTED_ENABLED_OPTIONAL[
            tenant.slug
        ], tenant.slug
        assert set(tenant.enabled_optional_stages) <= OPTIONAL_STAGE_VALUES, tenant.slug


def test_tenant_config_is_frozen():
    """A TenantConfig is immutable — assigning a field raises."""
    with pytest.raises(FrozenInstanceError):
        SUNSHINE.slug = "changed"  # type: ignore[misc]
