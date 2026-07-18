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

from dataclasses import dataclass, field


@dataclass(frozen=True)
class QuoteOptionTemplate:
    """One canned quote option a product line offers, as static registry data.

    The P2.3 ``carrier.quote`` stub (Epic 3) reads a product line's templates and
    writes one ``quotes`` row per template when a quote is requested, so the demo's
    options are deterministic and seed-free. ``carrier`` is one of the owning
    tenant's ``carriers``; ``product_label`` is the human-facing plan name shown
    on the quote card; ``coverage_amount`` and ``premium_monthly`` are whole
    dollars. ``premium_annual`` is **derived** as twelve monthly premiums (TDD D4)
    so the monthly figure stays the single source of truth and the two can never
    drift.
    """

    carrier: str
    product_label: str
    coverage_amount: int
    premium_monthly: int

    @property
    def premium_annual(self) -> int:
        """The annualized premium — twelve monthly premiums (TDD D4)."""
        return self.premium_monthly * 12


@dataclass(frozen=True)
class ProductLine:
    """One insurance product line a tenant offers, as static registry data.

    ``key`` is the snake_case stored vocabulary (matching the ``LeadSource``
    naming): both intake forms validate a submitted lead's product line against
    its tenant's keys, and the seed and reads carry the key verbatim. ``label``
    is the human-facing display string the intake forms and lead views render.
    Renaming a key is a cross-tenant contract change, so the keys are fixed here.

    ``requires_medicare_age`` flags a Medicare-gated line (P2.2 D4): the stage
    machine blocks entry to *Quoted* for an under-65 contact on such a line. It
    defaults ``False`` so only the Medicare lines opt in.

    ``renewal_rule`` classifies how this line renews (P2.4 / ADR 0003): ``"aep"``
    (the seasonal Medicare Annual Enrollment sweep), ``"anniversary"`` (a rolling
    60-day-before-the-issue-anniversary sweep), or ``"none"`` (lines that never
    auto-renew). It defaults ``"none"`` so a line opts in to a sweep explicitly.

    ``application_step`` names the product-specific step a Draft application on
    this line must capture (P2.3 D10): ``"beneficiary"`` (life-style lines),
    ``"health"`` (health-style lines), or ``None`` for lines that submit with no
    extra step. ``quote_options`` is this line's tuple of 2–3 canned quote
    templates the ``carrier.quote`` stub turns into quotes. Both default empty so a
    line with no step and no catalog is still valid registry data.
    """

    key: str
    label: str
    requires_medicare_age: bool = False
    renewal_rule: str = "none"
    application_step: str | None = None
    quote_options: tuple[QuoteOptionTemplate, ...] = ()


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
    # The carriers this tenant sells (P2.3 D4), seed-free registry data: every
    # `QuoteOptionTemplate.carrier` on this tenant's product lines is one of these
    # names. `collects_medicare_id` flags the tenant whose application step captures
    # an encrypted, masked, audited Medicare ID (P2.3 D9 — Sunshine only); it
    # defaults `False` so a tenant without the field opts out. Both default empty/off
    # so a tenant predating the catalog stays valid.
    carriers: tuple[str, ...] = ()
    collects_medicare_id: bool = False
    # Per-tenant pipeline config (P2.2 D1), seed-free registry data served to the
    # board endpoint like `brand_primary_color`. `stage_labels` maps a canonical
    # `OpportunityStage` value to this tenant's display override (absent ⇒ the
    # canonical label); `enabled_optional_stages` is this tenant's switched-on
    # subset of the optional stages `{"Quoted", "Approved"}`. Both default empty,
    # so a tenant with no overrides shows canonical labels and no optional stages.
    stage_labels: dict[str, str] = field(default_factory=dict)
    enabled_optional_stages: frozenset[str] = frozenset()


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
        ProductLine(
            key="medicare_advantage",
            label="Medicare Advantage",
            requires_medicare_age=True,
            renewal_rule="aep",
            quote_options=(
                QuoteOptionTemplate("Humana", "Gold Plus HMO", 7500, 29),
                QuoteOptionTemplate("Aetna", "Medicare Eagle PPO", 9000, 49),
                QuoteOptionTemplate("UnitedHealthcare", "AARP Complete HMO", 8200, 39),
            ),
        ),
        ProductLine(
            key="medicare_supplement",
            label="Medicare Supplement",
            requires_medicare_age=True,
            renewal_rule="anniversary",
            quote_options=(
                QuoteOptionTemplate("Mutual of Omaha", "Plan G", 6000, 142),
                QuoteOptionTemplate("Aetna", "Plan N", 6000, 118),
                QuoteOptionTemplate("UnitedHealthcare", "AARP Plan G", 6000, 155),
            ),
        ),
        ProductLine(
            key="final_expense",
            label="Final Expense",
            renewal_rule="none",
            application_step="beneficiary",
            quote_options=(
                QuoteOptionTemplate("Mutual of Omaha", "Living Promise Whole Life", 15000, 58),
                QuoteOptionTemplate("Aetna", "Final Expense Whole Life", 10000, 41),
                QuoteOptionTemplate("Humana", "Guaranteed Issue Whole Life", 8000, 36),
            ),
        ),
        ProductLine(
            key="dental_vision_hearing",
            label="Dental, Vision & Hearing",
            renewal_rule="anniversary",
            quote_options=(
                QuoteOptionTemplate("Humana", "Dental Preventive Plus", 1500, 32),
                QuoteOptionTemplate("Aetna", "Dental, Vision & Hearing Bundle", 2000, 45),
            ),
        ),
    ),
    carriers=("Humana", "Aetna", "UnitedHealthcare", "Mutual of Omaha"),
    collects_medicare_id=True,
    # Sunshine runs the full pipeline (both optional stages on) and relabels the
    # Medicare journey (P2.2 D13).
    stage_labels={
        "Qualified": "Needs Assessment",
        "Policy Active": "Enrolled",
    },
    enabled_optional_stages=frozenset({"Quoted", "Approved"}),
)

FLORIDA = TenantConfig(
    slug="florida-family-planning",
    display_name="Florida Family Planning",
    schema_name="florida",
    db_role="tenant_florida",
    email_domain="florida.example",
    brand_primary_color="#0F6A72",
    product_lines=(
        ProductLine(
            key="term_life",
            label="Term Life Insurance",
            renewal_rule="none",
            application_step="beneficiary",
            quote_options=(
                QuoteOptionTemplate("Prudential", "Term Essential 20", 250000, 28),
                QuoteOptionTemplate("MetLife", "Level Term 30", 500000, 47),
                QuoteOptionTemplate("Cigna", "Term Life 20", 100000, 16),
            ),
        ),
        ProductLine(
            key="whole_life",
            label="Whole Life Insurance",
            renewal_rule="none",
            application_step="beneficiary",
            quote_options=(
                QuoteOptionTemplate("Prudential", "Whole Life Advantage", 100000, 96),
                QuoteOptionTemplate("MetLife", "Whole Life Premier", 50000, 58),
            ),
        ),
        ProductLine(
            key="health",
            label="Health Insurance",
            renewal_rule="anniversary",
            application_step="health",
            quote_options=(
                QuoteOptionTemplate("Cigna", "Connect Bronze HMO", 9000, 312),
                QuoteOptionTemplate("Aflac", "Major Medical Silver", 7000, 389),
                QuoteOptionTemplate("MetLife", "Health Select Gold", 5000, 465),
            ),
        ),
        ProductLine(
            key="critical_illness",
            label="Critical Illness",
            renewal_rule="anniversary",
            application_step="health",
            quote_options=(
                QuoteOptionTemplate("Aflac", "Critical Care Protection", 20000, 34),
                QuoteOptionTemplate("MetLife", "Critical Illness Plus", 30000, 48),
            ),
        ),
    ),
    carriers=("Prudential", "MetLife", "Cigna", "Aflac"),
    collects_medicare_id=False,
    # Florida disables the optional *Approved* stage (Submitted → Policy Active
    # skips it, proving the skip) and relabels two stages (P2.2 D13). No Medicare
    # lines, so no product line is `requires_medicare_age`.
    stage_labels={
        "Quoted": "Proposal Sent",
        "Application Started": "App In Progress",
    },
    enabled_optional_stages=frozenset({"Quoted"}),
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

# The dedicated demo-purge role. Phase P1.8 Epic 9's `0013` migration creates it
# and grants it SELECT+DELETE on each tenant's `leads` table plus SELECT+DELETE on
# the two platform demo tables (`demo_session_tenant_seed`, `demo_sessions`); the
# purge engine (`app.demo.purge`) sets this role to remove a demo session's
# overlay across every tenant schema — never INSERT or UPDATE, mirroring the tight
# `audit_writer` / `outbox_relay` grant shape. It is the *only* role granted
# DELETE on `leads`, kept separate from the tenant roles' read/write grant on the
# `0012` ledger so the destructive sweep never rides a request transaction.
DEMO_PURGE_ROLE = "demo_purge"


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
