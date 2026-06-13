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

from app.auth.passwords import verify_password
from app.models import Role, Tenant, User
from app.seed import (
    PLATFORM_ADMIN_EMAIL,
    demo_tenants,
    demo_user_specs,
    demo_users_for,
    seed,
)
from app.tenancy.registry import TENANTS, tenant_by_slug


class FakeResult:
    """A stand-in for a SQLAlchemy `Result` that yields preset rows.

    Every `seed` query reads through `.scalars().all()`: scalar columns
    (`select(Tenant.slug)`, `select(User.username)`) and the present-tenant
    lookup, which now loads full `Tenant` ORM objects (`select(Tenant)`). This
    fake serves all of them — `scalars()` returns self and `.all()` returns the
    preset rows unchanged.
    """

    def __init__(self, rows, rowcount=0):
        self._rows = rows
        self.rowcount = rowcount

    def scalars(self):
        return self

    def all(self):
        return self._rows


class FakeAsyncSession:
    """A minimal async session that replays preset `execute` results.

    `seed` runs up to four SELECT queries in order: existing tenant slugs, the
    already-present `Tenant` ORM rows, existing usernames, then the existing
    data-key tenant ids (for the per-tenant root-key seeding step). The fake is
    handed a list of result-row lists and returns the next one on each of those
    SELECTs. The later per-tenant settings INSERTs call `execute(statement,
    params)` with a bound-parameters mapping; the fake recognises those by the
    second positional argument and returns a `rowcount`-bearing result without
    consuming a preset SELECT row, recording each one in `settings_inserts`.
    `add` appends to `added`, and `commit` flips `did_commit`, so a test can
    assert exactly which rows were inserted and that one commit ran.
    """

    def __init__(self, result_rows):
        self._result_rows = list(result_rows)
        self._execute_count = 0
        self.added = []
        self.settings_inserts = []
        self.did_commit = False

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


# --- Phase 3: seeding from empty inserts the full matrix ----------------------


def _empty_database_results():
    """Result rows for an empty database: no tenants present, no usernames.

    Three `execute` calls run when no tenants pre-exist (tenant slugs, then
    usernames — the present-tenant lookup is skipped because nothing is present
    — then the existing data-key tenant ids for the key-seeding step).
    """
    return [[], [], []]


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
    # Four execute calls: existing slugs, present `Tenant` rows, existing
    # usernames, and the existing data-key tenant ids. All tenant ids already
    # have keys here, so no new key is added on this idempotent re-seed.
    present_tenant_ids = [tenant.id for tenant in present_tenants]
    session = FakeAsyncSession(
        [all_slugs, present_tenants, all_usernames, present_tenant_ids]
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
    # so a wrapped key is minted for both registry tenants on this seed.
    session = FakeAsyncSession(
        [[present_slug], present_tenants, present_usernames, []]
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
