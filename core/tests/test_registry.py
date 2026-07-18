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


# The renewal rule each product line carries (P2.4 D1 / ADR 0003), keyed by slug
# then product-line key. Hand-built here separate from the registry so a drift in
# either side is caught: Medicare Advantage renews on the AEP sweep; the ancillary
# and health lines renew on the rolling anniversary sweep; the life-style and final-
# expense lines never auto-renew. Epic 4's generation core keys its sweeps on this.
EXPECTED_RENEWAL_RULES: dict[str, dict[str, str]] = {
    "sunshine-senior-benefits": {
        "medicare_advantage": "aep",
        "medicare_supplement": "anniversary",
        "final_expense": "none",
        "dental_vision_hearing": "anniversary",
    },
    "florida-family-planning": {
        "term_life": "none",
        "whole_life": "none",
        "health": "anniversary",
        "critical_illness": "anniversary",
    },
}

# The only renewal-rule values a product line may carry (P2.4 D1 / ADR 0003).
VALID_RENEWAL_RULES = {"aep", "anniversary", "none"}


def test_renewal_rule_matches_the_expected_value_per_line():
    """Each product line's `renewal_rule` matches the hand-written expectation."""
    for tenant in TENANTS:
        actual = {
            product_line.key: product_line.renewal_rule
            for product_line in tenant.product_lines
        }
        assert actual == EXPECTED_RENEWAL_RULES[tenant.slug], tenant.slug


def test_renewal_rule_is_always_one_of_the_valid_values():
    """No product line carries a renewal rule outside the valid set."""
    for tenant in TENANTS:
        for product_line in tenant.product_lines:
            assert product_line.renewal_rule in VALID_RENEWAL_RULES, product_line.key


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


# --- P2.3 catalog: carriers, quote-option templates, and the two new flags -----

# The product step each line captures (P2.3 D10), keyed by slug then product-line
# key. Hand-built here separate from the registry: beneficiary for the life-style
# lines, health for the health-style lines, None for lines that submit with no
# extra step (Sunshine's Medicare + DVH lines). Epic 6 keys its step form on this.
EXPECTED_APPLICATION_STEPS: dict[str, dict[str, str | None]] = {
    "sunshine-senior-benefits": {
        "medicare_advantage": None,
        "medicare_supplement": None,
        "final_expense": "beneficiary",
        "dental_vision_hearing": None,
    },
    "florida-family-planning": {
        "term_life": "beneficiary",
        "whole_life": "beneficiary",
        "health": "health",
        "critical_illness": "health",
    },
}

# The carriers each tenant sells (P2.3 D4), hand-built separate from the registry.
EXPECTED_CARRIERS: dict[str, set[str]] = {
    "sunshine-senior-benefits": {"Humana", "Aetna", "UnitedHealthcare", "Mutual of Omaha"},
    "florida-family-planning": {"Prudential", "MetLife", "Cigna", "Aflac"},
}

# The tenant that captures a Medicare ID on its application step (P2.3 D9) — only
# Sunshine. Hand-built separate from the registry.
EXPECTED_COLLECTS_MEDICARE_ID: dict[str, bool] = {
    "sunshine-senior-benefits": True,
    "florida-family-planning": False,
}

# The only application-step values a product line may carry (P2.3 D10).
VALID_APPLICATION_STEPS = {"beneficiary", "health", None}


def test_application_step_matches_the_expected_value_per_line():
    """Each product line's `application_step` matches the hand-written expectation."""
    for tenant in TENANTS:
        actual = {
            product_line.key: product_line.application_step
            for product_line in tenant.product_lines
        }
        assert actual == EXPECTED_APPLICATION_STEPS[tenant.slug], tenant.slug


def test_application_step_is_always_one_of_the_valid_values():
    """No product line carries an application step outside the valid set."""
    for tenant in TENANTS:
        for product_line in tenant.product_lines:
            assert product_line.application_step in VALID_APPLICATION_STEPS, product_line.key


def test_carriers_match_the_expected_set_per_tenant():
    """Each tenant's carrier list matches the hand-written expectation."""
    for tenant in TENANTS:
        assert set(tenant.carriers) == EXPECTED_CARRIERS[tenant.slug], tenant.slug


def test_collects_medicare_id_matches_the_expected_flag():
    """Only the expected tenant collects a Medicare ID on its application step."""
    for tenant in TENANTS:
        assert tenant.collects_medicare_id == EXPECTED_COLLECTS_MEDICARE_ID[tenant.slug], (
            tenant.slug
        )


def test_every_product_line_offers_two_or_three_quote_options():
    """Each product line carries 2–3 canned quote-option templates (TDD D4)."""
    for tenant in TENANTS:
        for product_line in tenant.product_lines:
            assert 2 <= len(product_line.quote_options) <= 3, product_line.key


def test_every_quote_option_template_carrier_belongs_to_the_tenant():
    """Each template's carrier is one of its owning tenant's carriers."""
    for tenant in TENANTS:
        carriers = set(tenant.carriers)
        for product_line in tenant.product_lines:
            for option in product_line.quote_options:
                assert option.carrier in carriers, f"{product_line.key}:{option.carrier}"


def test_every_quote_option_template_has_positive_amounts():
    """Coverage and monthly premium are positive whole dollars on every template."""
    for tenant in TENANTS:
        for product_line in tenant.product_lines:
            for option in product_line.quote_options:
                assert option.coverage_amount > 0, product_line.key
                assert option.premium_monthly > 0, product_line.key


def test_quote_option_annual_premium_is_twelve_monthly_premiums():
    """`premium_annual` is derived as exactly twelve monthly premiums (TDD D4)."""
    for tenant in TENANTS:
        for product_line in tenant.product_lines:
            for option in product_line.quote_options:
                assert option.premium_annual == option.premium_monthly * 12, product_line.key
