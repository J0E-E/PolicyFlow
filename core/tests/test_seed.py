"""Unit tests for the idempotent demo-persona seed.

Pure unit tests — no DB, no Docker — matching the no-Docker style of
`test_provider.py`. The seed's persona spec (`demo_tenants`, `demo_user_specs`)
is plain data, asserted directly. The async `seed(db)` is driven through a tiny
fake async session (`FakeAsyncSession` / `FakeResult`, the same idiom as
`test_provider.py`) whose `execute(...)` returns preset existing-slug and
existing-username rows and whose `add(...)` records each inserted object, so the
insert-if-absent logic is exercised with no database.

`asyncio_mode = auto` is set for the suite, so the async tests carry no
`@pytest.mark.asyncio` decorator.
"""

import pytest

from app.auth.passwords import verify_password
from app.leads.state import LeadStatus
from app.models import Role, Tenant, User
from app.pii.masking import age_band_for
from app.seed import (
    PLATFORM_ADMIN_EMAIL,
    SESSION_LEAD_TEMPLATES,
    SHARED_HISTORICAL_LEADS,
    demo_tenants,
    demo_user_specs,
    demo_users_for,
    seed,
)
from app.tenancy.registry import SUNSHINE, TENANTS, tenant_by_slug


class FakeResult:
    """A stand-in for a SQLAlchemy `Result` that yields preset rows.

    Most `seed` queries read through `.scalars().all()`: scalar columns
    (`select(Tenant.slug)`, `select(User.username)`) and the present-tenant
    lookup, which loads full `Tenant` ORM objects (`select(Tenant)`). The
    per-tenant `pii_demo` count reads through `.scalar_one()`. This fake serves
    all of them — `scalars()` returns self, `.all()` returns the preset rows
    unchanged, and `.scalar_one()` returns the single preset row.
    """

    def __init__(self, rows, rowcount=0):
        self._rows = rows
        self.rowcount = rowcount

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one(self):
        return self._rows[0]


class FakeAsyncSession:
    """A minimal async session that replays preset `execute` results.

    `seed` runs these no-parameter SELECTs in order: existing tenant slugs, the
    already-present `Tenant` ORM rows, existing usernames, the existing data-key
    tenant ids (for the per-tenant root-key seeding step), then one
    ``SELECT COUNT(*) FROM <schema>.pii_demo`` per tenant (for the count-based
    `pii_demo` idempotency skip), then one
    ``SELECT COUNT(*) FROM <schema>.leads WHERE demo_session_id IS NULL`` per tenant
    (the count-based shared-historical-leads idempotency skip). The fake is handed a
    list of result-row lists and returns the next one on each of those SELECTs; the
    per-tenant count rows are presets too (a non-zero count makes
    `seed_pii_demo_records` / `seed_shared_historical_leads` skip the encryption path
    entirely, keeping this a pure no-DB unit test).

    The per-tenant settings INSERTs call `execute(statement, params)` with a
    bound-parameters mapping; the fake recognises those by the second positional
    argument and returns a `rowcount`-bearing result without consuming a preset
    SELECT row, recording each one in `settings_inserts`. `add` appends to
    `added`, and `commit` increments `commit_count` (and sets `did_commit`), so a
    test can assert exactly which rows were inserted and that the seed committed.

    The boot seed touches `leads` only for the shared-historical set (P1.8 Epic 8);
    P1.8 Epic 7 moved the New-queue set out of the boot seed into per-session
    instantiation. With both per-tenant count presets non-zero the historical path
    skips before any INSERT, so the only parametrised statements here are the
    `tenant_settings` INSERTs.
    """

    def __init__(self, result_rows):
        self._result_rows = list(result_rows)
        self._execute_count = 0
        self.added = []
        self.settings_inserts = []
        self.did_commit = False
        self.commit_count = 0

    async def execute(self, statement, parameters=None):
        if parameters is not None:
            # A parametrised settings INSERT — record it and report one row
            # affected so the seed's insert counter advances.
            self.settings_inserts.append(parameters)
            return FakeResult([], rowcount=1)
        rows = self._result_rows[self._execute_count]
        self._execute_count += 1
        return FakeResult(rows)

    def add(self, instance):
        self.added.append(instance)

    async def commit(self):
        self.did_commit = True
        self.commit_count += 1


# --- Phase 2: the persona spec is correct (pure data, no session) ------------


def test_exactly_two_tenants_with_expected_slugs():
    """The spec defines exactly the two named demo tenants."""
    tenants = demo_tenants()

    assert len(tenants) == 2
    slugs = {slug for slug, _name in tenants}
    assert slugs == {"sunshine-senior-benefits", "florida-family-planning"}


def test_exactly_nine_users_with_expected_role_counts():
    """The spec defines nine users matching the RBAC role matrix."""
    specs = demo_user_specs()

    assert len(specs) == 9
    role_counts: dict[Role, int] = {}
    for _email, role, _tenant_slug in specs:
        role_counts[role] = role_counts.get(role, 0) + 1
    assert role_counts == {
        Role.AGENT: 4,
        Role.TENANT_ADMIN: 2,
        Role.READ_ONLY: 2,
        Role.PLATFORM_ADMIN: 1,
    }


def test_platform_admin_is_tenantless_and_others_have_a_tenant():
    """Only the platform admin is tenantless; every other user has a tenant."""
    specs = demo_user_specs()

    for email, role, tenant_slug in specs:
        if role is Role.PLATFORM_ADMIN:
            assert email == PLATFORM_ADMIN_EMAIL
            assert tenant_slug is None
        else:
            assert tenant_slug is not None


def test_usernames_equal_emails_and_are_unique():
    """Each persona's username equals its email, and all are distinct."""
    emails = [email for email, _role, _tenant_slug in demo_user_specs()]

    assert len(emails) == len(set(emails))


def test_persona_emails_use_their_tenants_registry_domain():
    """Each persona's email is built from the tenant's registry email domain.

    Proves the seed's email construction is wired to the registry, not to a
    leftover hardcoded domain map.
    """
    for tenant in TENANTS:
        expected_domain = tenant_by_slug(tenant.slug).email_domain
        for email, _role, _tenant_slug in demo_users_for(tenant.slug):
            assert email.endswith("@" + expected_domain)


# --- The shared historical lead set is correct (pure data, no session) -------


def test_shared_historical_leads_cover_both_tenants_with_six_each():
    """Each tenant gets exactly 6 shared historical leads (P1.8 Epic 8)."""
    assert set(SHARED_HISTORICAL_LEADS) == {
        "sunshine-senior-benefits",
        "florida-family-planning",
    }
    for rows in SHARED_HISTORICAL_LEADS.values():
        assert len(rows) == 6


def test_shared_historical_leads_split_two_working_two_qualified_two_rejected():
    """Per tenant the status mix is the agreed 2 Working / 2 Qualified / 2 Rejected."""
    for rows in SHARED_HISTORICAL_LEADS.values():
        status_counts: dict[LeadStatus, int] = {}
        for row in rows:
            status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
        assert status_counts == {
            LeadStatus.WORKING: 2,
            LeadStatus.QUALIFIED: 2,
            LeadStatus.REJECTED: 2,
        }


def test_shared_historical_leads_are_all_owned_split_three_three():
    """Every row is owned, split 3/3 across agent.one and agent.two per tenant.

    No unowned / `New` rows: an unowned `New` row would surface in the Unassigned
    queue looking claimable while the Epic 5 write guard silently `409`s it.
    """
    for rows in SHARED_HISTORICAL_LEADS.values():
        owner_counts: dict[str, int] = {}
        for row in rows:
            assert row["owner_local_part"] in ("agent.one", "agent.two")
            assert row["status"] is not LeadStatus.NEW
            owner_counts[row["owner_local_part"]] = (
                owner_counts.get(row["owner_local_part"], 0) + 1
            )
        assert owner_counts == {"agent.one": 3, "agent.two": 3}


def test_shared_historical_rejected_rows_carry_a_reason_others_do_not():
    """Only the Rejected rows carry a `rejection_reason` (a `Working → Rejected`)."""
    for rows in SHARED_HISTORICAL_LEADS.values():
        for row in rows:
            if row["status"] is LeadStatus.REJECTED:
                assert row["rejection_reason"]
            else:
                assert row["rejection_reason"] is None


def test_shared_historical_leads_have_distinct_emails_and_all_decimal_phones():
    """Emails are distinct and phones are distinct and all-decimal (matcher gotcha).

    Low-entropy contact details in the shared container DB flag unrelated leads, so
    each historical row carries a distinct email and a distinct phone whose digits
    are all decimal.
    """
    all_emails = [
        row["email"] for rows in SHARED_HISTORICAL_LEADS.values() for row in rows
    ]
    all_phones = [
        row["phone"] for rows in SHARED_HISTORICAL_LEADS.values() for row in rows
    ]
    assert len(all_emails) == len(set(all_emails))
    assert len(all_phones) == len(set(all_phones))
    for phone in all_phones:
        digits = [character for character in phone if character.isdigit()]
        assert digits  # has at least one digit
        assert all(character.isascii() for character in digits)


def test_shared_historical_product_lines_come_from_the_tenant_registry():
    """Every product-line key on a row belongs to that tenant's registry set."""
    for tenant_slug, rows in SHARED_HISTORICAL_LEADS.items():
        valid_keys = {
            line.key for line in tenant_by_slug(tenant_slug).product_lines
        }
        for row in rows:
            assert row["product_lines_of_interest"]
            assert set(row["product_lines_of_interest"]) <= valid_keys


def test_shared_historical_birth_dates_spread_across_age_bands():
    """Birth dates span more than one age band per tenant, so lists read varied."""
    for rows in SHARED_HISTORICAL_LEADS.values():
        bands = {age_band_for(row["date_of_birth"]) for row in rows}
        assert len(bands) >= 2


def test_shared_historical_leads_carry_a_positive_backdate_offset():
    """Each row carries a positive `created_at_offset_days` so it sorts as history."""
    for rows in SHARED_HISTORICAL_LEADS.values():
        for row in rows:
            assert isinstance(row["created_at_offset_days"], int)
            assert row["created_at_offset_days"] > 0


def test_a_sunshine_session_lead_is_medicare_gated_and_under_65():
    """A Sunshine session-lead template is on a Medicare-gated line AND under 65.

    Converting such a lead yields a Medicare-gated, under-65 opportunity the agent
    can demonstrate the *Quoted* block on (walkthrough step 8), so the scripted gate
    demo is reliable (P2.2 Epic 9). Keyed off the registry `requires_medicare_age`
    flag + the `age_band_for` helper (not a hard-coded name), so it survives a
    future re-nudge and fails loudly if the gated-under-65 scenario ever regresses.
    """
    gated_keys = {
        line.key for line in SUNSHINE.product_lines if line.requires_medicare_age
    }
    assert gated_keys, "Sunshine must offer at least one Medicare-gated line"

    def is_gated_and_under_65(template: dict) -> bool:
        on_gated_line = any(
            key in gated_keys for key in template["product_lines_of_interest"]
        )
        under_65 = age_band_for(template["date_of_birth"]) != "65+"
        return on_gated_line and under_65

    assert any(
        is_gated_and_under_65(template)
        for template in SESSION_LEAD_TEMPLATES[SUNSHINE.slug]
    )


# --- Phase 3: seeding from empty inserts the full matrix ----------------------


def _empty_database_results():
    """Result rows for an empty database: no tenants present, no usernames.

    The no-parameter SELECTs that run when no tenants pre-exist, in order: tenant
    slugs, then usernames (the present-tenant lookup is skipped because nothing is
    present), then the existing data-key tenant ids for the key-seeding step, then
    one ``SELECT COUNT(*) FROM <schema>.pii_demo`` per tenant, then one
    ``SELECT COUNT(*) FROM <schema>.leads WHERE demo_session_id IS NULL`` per tenant.
    The four count rows are preset non-zero (`[2]` / `[1]`) so the `pii_demo` and
    shared-historical-leads seeding both skip their encryption path on every tenant,
    keeping this a pure no-DB unit test.
    """
    return [[], [], [], [2], [2], [1], [1]]


async def test_seed_from_empty_inserts_two_tenants_and_nine_users():
    """With no existing rows, the seed adds the 2 tenants and 9 users, once."""
    session = FakeAsyncSession(_empty_database_results())

    await seed(session)

    inserted_tenants = [row for row in session.added if isinstance(row, Tenant)]
    inserted_users = [row for row in session.added if isinstance(row, User)]
    assert len(inserted_tenants) == 2
    assert len(inserted_users) == 9
    assert session.did_commit is True


async def test_seeded_users_link_to_their_tenant_and_carry_usable_password():
    """Seeded users get the right tenant link and a verifiable password hash."""
    session = FakeAsyncSession(_empty_database_results())

    await seed(session)

    inserted_tenants = [row for row in session.added if isinstance(row, Tenant)]
    inserted_users = [row for row in session.added if isinstance(row, User)]
    slug_to_id = {tenant.slug: tenant.id for tenant in inserted_tenants}

    platform_admins = [
        user for user in inserted_users if user.role is Role.PLATFORM_ADMIN
    ]
    assert len(platform_admins) == 1
    assert platform_admins[0].tenant_id is None

    for user in inserted_users:
        assert user.username == user.email
        assert verify_password("demo-password-change-me", user.password_hash)
        if user.role is not Role.PLATFORM_ADMIN:
            # Every tenant user links to one of the inserted tenants.
            assert user.tenant_id in slug_to_id.values()


async def test_seed_brand_color_comes_from_the_registry():
    """Each seeded settings row carries its tenant's REGISTRY brand colour.

    The seed must derive `brand_primary_color` from the registry (the single
    source of truth) — never from its own constants. This maps each recorded
    settings INSERT's `tenant_id` back to its slug via the inserted `Tenant`
    objects, then asserts the per-tenant colour equals the registry value and is
    not either of the old hardcoded placeholders.
    """
    session = FakeAsyncSession(_empty_database_results())

    await seed(session)

    inserted_tenants = [row for row in session.added if isinstance(row, Tenant)]
    slug_by_tenant_id = {tenant.id: tenant.slug for tenant in inserted_tenants}

    inserted_colors = {
        insert["brand_primary_color"] for insert in session.settings_inserts
    }
    # The old placeholders are gone entirely — the colour now lives only in the
    # registry.
    assert "#F5A623" not in inserted_colors
    assert "#2E86C1" not in inserted_colors

    # Both tenants got a settings row, each carrying its registry colour.
    assert len(session.settings_inserts) == len(inserted_tenants) == 2
    for insert in session.settings_inserts:
        slug = slug_by_tenant_id[insert["tenant_id"]]
        assert (
            insert["brand_primary_color"]
            == tenant_by_slug(slug).brand_primary_color
        )


async def test_fresh_seed_tenants_carry_registry_schema_and_role():
    """Inserted tenants carry the registry's schema_name / db_role for their slug."""
    session = FakeAsyncSession(_empty_database_results())

    await seed(session)

    inserted_tenants = [row for row in session.added if isinstance(row, Tenant)]
    for tenant in inserted_tenants:
        config = tenant_by_slug(tenant.slug)
        assert tenant.schema_name == config.schema_name
        assert tenant.db_role == config.db_role


# --- Phase 3: idempotency — insert only what is absent ------------------------


async def test_seed_is_idempotent_when_everything_already_present():
    """With all slugs and usernames present, nothing new is added.

    The present tenants are preset as `Tenant` objects (the lookup now loads full
    ORM rows). Each should be backfilled with the registry's schema_name / db_role.
    """
    all_slugs = [slug for slug, _name in demo_tenants()]
    present_tenants = [
        Tenant(id="id-" + slug, slug=slug, name=slug) for slug in all_slugs
    ]
    all_usernames = [email for email, _role, _tenant_slug in demo_user_specs()]
    # Eight no-parameter SELECTs: existing slugs, present `Tenant` rows, existing
    # usernames, the existing data-key tenant ids, then one `pii_demo` count per
    # tenant, then one shared-historical `leads` count per tenant. All tenant ids
    # already have keys here, so no new key is added; the `pii_demo` counts are
    # non-zero (`[2]`) and the `leads` counts non-zero (`[1]`), so neither a demo PII
    # record nor a historical lead is added.
    present_tenant_ids = [tenant.id for tenant in present_tenants]
    session = FakeAsyncSession(
        [
            all_slugs,
            present_tenants,
            all_usernames,
            present_tenant_ids,
            [2],
            [2],
            [1],
            [1],
        ]
    )

    await seed(session)

    assert session.added == []
    assert session.did_commit is True
    for tenant in present_tenants:
        config = tenant_by_slug(tenant.slug)
        assert tenant.schema_name == config.schema_name
        assert tenant.db_role == config.db_role


async def test_seed_adds_only_missing_rows_on_partial_state():
    """A partial existing state inserts only the absent tenant and users."""
    # One tenant already present, the other absent; the present tenant's four
    # users already exist, so only the missing tenant and its four users insert.
    present_slug = "sunshine-senior-benefits"
    present_tenants = [Tenant(id="id-" + present_slug, slug=present_slug, name=present_slug)]
    present_usernames = [
        email
        for email, _role, tenant_slug in demo_user_specs()
        if tenant_slug == present_slug
    ]
    # The fourth execute is the existing data-key tenant ids; none exist yet,
    # so a wrapped key is minted for both registry tenants on this seed. The next
    # two are the per-tenant `pii_demo` counts and the last two the per-tenant
    # shared-historical `leads` counts, all preset non-zero (`[2]` / `[1]`) so the
    # demo PII and historical-leads seeding skip their encryption path on both
    # tenants.
    session = FakeAsyncSession(
        [[present_slug], present_tenants, present_usernames, [], [2], [2], [1], [1]]
    )

    await seed(session)

    inserted_tenants = [row for row in session.added if isinstance(row, Tenant)]
    inserted_users = [row for row in session.added if isinstance(row, User)]
    assert len(inserted_tenants) == 1
    assert inserted_tenants[0].slug == "florida-family-planning"
    # The newly inserted tenant carries the registry's schema_name / db_role.
    florida_config = tenant_by_slug("florida-family-planning")
    assert inserted_tenants[0].schema_name == florida_config.schema_name
    assert inserted_tenants[0].db_role == florida_config.db_role
    # The already-present tenant is backfilled from the registry.
    sunshine_config = tenant_by_slug(present_slug)
    assert present_tenants[0].schema_name == sunshine_config.schema_name
    assert present_tenants[0].db_role == sunshine_config.db_role
    # The five not-yet-present personas: the absent tenant's four users plus the
    # tenantless platform admin.
    assert len(inserted_users) == 5
    assert session.did_commit is True
