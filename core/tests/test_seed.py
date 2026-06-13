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

    `seed` reads scalar columns (`select(Tenant.slug)`, `select(User.username)`)
    via `.scalars().all()`, and the present-tenant lookup reads `(slug, id)`
    rows via `.all()`. This fake serves both: `scalars().all()` returns the
    preset rows as-is, and `.all()` returns them unchanged.
    """

    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class FakeAsyncSession:
    """A minimal async session that replays preset `execute` results.

    `seed` runs up to three queries in order: existing tenant slugs, the
    already-present tenant (slug, id) rows, then existing usernames. The fake is
    handed a list of result-row lists and returns the next one on each
    `execute`. `add` appends to `added`, and `commit` flips `did_commit`, so a
    test can assert exactly which rows were inserted and that one commit ran.
    """

    def __init__(self, result_rows):
        self._result_rows = list(result_rows)
        self._execute_count = 0
        self.added = []
        self.did_commit = False

    async def execute(self, statement):
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

    Two `execute` calls run when no tenants pre-exist (tenant slugs, then
    usernames — the present-tenant lookup is skipped because nothing is present).
    """
    return [[], []]


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


# --- Phase 3: idempotency — insert only what is absent ------------------------


async def test_seed_is_idempotent_when_everything_already_present():
    """With all slugs and usernames present, nothing new is added."""
    all_slugs = [slug for slug, _name in demo_tenants()]
    present_tenant_rows = [(slug, "id-" + slug) for slug in all_slugs]
    all_usernames = [email for email, _role, _tenant_slug in demo_user_specs()]
    # Three execute calls: existing slugs, present-tenant (slug, id) rows,
    # existing usernames.
    session = FakeAsyncSession(
        [all_slugs, present_tenant_rows, all_usernames]
    )

    await seed(session)

    assert session.added == []
    assert session.did_commit is True


async def test_seed_adds_only_missing_rows_on_partial_state():
    """A partial existing state inserts only the absent tenant and users."""
    # One tenant already present, the other absent; the present tenant's four
    # users already exist, so only the missing tenant and its four users insert.
    present_slug = "sunshine-senior-benefits"
    present_tenant_rows = [(present_slug, "id-" + present_slug)]
    present_usernames = [
        email
        for email, _role, tenant_slug in demo_user_specs()
        if tenant_slug == present_slug
    ]
    session = FakeAsyncSession(
        [[present_slug], present_tenant_rows, present_usernames]
    )

    await seed(session)

    inserted_tenants = [row for row in session.added if isinstance(row, Tenant)]
    inserted_users = [row for row in session.added if isinstance(row, User)]
    assert len(inserted_tenants) == 1
    assert inserted_tenants[0].slug == "florida-family-planning"
    # The five not-yet-present personas: the absent tenant's four users plus the
    # tenantless platform admin.
    assert len(inserted_users) == 5
    assert session.did_commit is True
