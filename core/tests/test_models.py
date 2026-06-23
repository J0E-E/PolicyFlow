"""No-Docker metadata tests for the `platform` domain models.

These assert the shape of the ORM models and the `0002` migration by reading
SQLAlchemy metadata and the migration module directly — they run no SQL and need
no live Postgres (mirroring the no-Docker style of `test_db.py`). Live apply
against real Postgres is exercised in Epic 11's testcontainers substrate.

Importing `app.models` registers all three tables on `Base.metadata`; `conftest`
defaults `DATABASE_URL` so the eager engine build in `app.db` never raises here.
"""

import importlib.util
from pathlib import Path

import app.models  # noqa: F401  (registers the tables on Base.metadata)
from app.db import Base
from app.models import Role


def get_table(qualified_name: str):
    """Return the registered table for a ``schema.name`` key, or None if absent."""
    return Base.metadata.tables.get(qualified_name)


def test_three_platform_tables_are_registered():
    """All three domain tables live in the `platform` schema on the metadata."""
    assert get_table("platform.tenants") is not None
    assert get_table("platform.users") is not None
    assert get_table("platform.auth_sessions") is not None


def test_demo_sessions_table_is_registered_in_platform_schema():
    """The `demo_sessions` table is registered in the `platform` schema (P1.8)."""
    assert get_table("platform.demo_sessions") is not None


def test_demo_sessions_columns_and_nullability():
    """`demo_sessions` carries id (pk), created_at, expires_at, last_tenant_slug.

    `expires_at` is required (the window must be bounded); `last_tenant_slug` is
    nullable (informational — a tenantless Platform-Admin visit may carry none).
    """
    demo_sessions = get_table("platform.demo_sessions")

    assert demo_sessions.c.id.primary_key is True
    assert demo_sessions.c.expires_at.nullable is False
    assert demo_sessions.c.last_tenant_slug.nullable is True


def test_demo_session_tenant_seed_table_is_registered_in_platform_schema():
    """The `demo_session_tenant_seed` ledger is registered in `platform` (P1.8 Epic 7)."""
    assert get_table("platform.demo_session_tenant_seed") is not None


def test_demo_session_tenant_seed_has_composite_primary_key():
    """The ledger is keyed by the composite `(demo_session_id, tenant_slug)`.

    Both columns carry the primary key (the per-(visit, tenant) idempotency
    marker); `seeded_at` is a required timestamp with a server default.
    """
    ledger = get_table("platform.demo_session_tenant_seed")

    primary_key_columns = {column.name for column in ledger.primary_key.columns}
    assert primary_key_columns == {"demo_session_id", "tenant_slug"}
    assert ledger.c.seeded_at.nullable is False


def test_role_enum_has_exactly_four_members_with_lowercase_values():
    """`Role` defines the four roles with their lowercase string values."""
    role_values = {member.name: member.value for member in Role}

    assert role_values == {
        "AGENT": "agent",
        "TENANT_ADMIN": "tenant_admin",
        "READ_ONLY": "read_only",
        "PLATFORM_ADMIN": "platform_admin",
    }


def test_users_tenant_id_is_nullable_and_username_is_unique():
    """`users.tenant_id` is nullable; `username` carries a unique constraint."""
    users = get_table("platform.users")

    assert users.c.tenant_id.nullable is True
    assert users.c.username.unique is True


def test_users_has_named_platform_admin_check_constraint():
    """The Platform-Admin CHECK is present under its deterministic name."""
    users = get_table("platform.users")

    check_constraint_names = {
        constraint.name
        for constraint in users.constraints
        if constraint.name is not None
    }

    assert "ck_users_platform_admin_tenantless" in check_constraint_names


def test_users_role_maps_to_platform_user_role_enum():
    """`users.role` is the `user_role` enum in the `platform` schema."""
    users = get_table("platform.users")
    role_type = users.c.role.type

    assert role_type.name == "user_role"
    assert role_type.schema == "platform"


def test_auth_sessions_token_hash_is_unique():
    """`auth_sessions.token_hash` carries a unique constraint."""
    auth_sessions = get_table("platform.auth_sessions")

    assert auth_sessions.c.token_hash.unique is True


def test_auth_sessions_user_id_cascades_on_delete():
    """The `auth_sessions.user_id` FK deletes sessions when its user is removed."""
    auth_sessions = get_table("platform.auth_sessions")

    user_id_foreign_keys = list(auth_sessions.c.user_id.foreign_keys)

    assert len(user_id_foreign_keys) == 1
    foreign_key = user_id_foreign_keys[0]
    assert foreign_key.column.table.fullname == "platform.users"
    assert foreign_key.ondelete == "CASCADE"


def load_migration_module(file_name: str):
    """Load a migration module by file path.

    The migration lives under `alembic/versions/`, which is not an importable
    package and whose file names start with a digit, so it is loaded directly
    from its path rather than via `import`.
    """
    migration_path = (
        Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
        / file_name
    )
    spec = importlib.util.spec_from_file_location(
        "migration_under_test", migration_path
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_migration_0002_follows_the_empty_baseline():
    """The `0002` migration chains onto `0001_empty_baseline`."""
    migration = load_migration_module("0002_platform_identity.py")

    assert migration.revision == "0002_platform_identity"
    assert migration.down_revision == "0001_empty_baseline"


def test_migration_0011_follows_0010():
    """The `0011` demo-sessions migration chains onto `0010_lead_rejection_reason`."""
    migration = load_migration_module("0011_demo_sessions.py")

    assert migration.revision == "0011_demo_sessions"
    assert migration.down_revision == "0010_lead_rejection_reason"


def test_migration_0012_follows_0011():
    """The `0012` seed-ledger migration chains onto `0011_demo_sessions`."""
    migration = load_migration_module("0012_demo_session_tenant_seed.py")

    assert migration.revision == "0012_demo_session_tenant_seed"
    assert migration.down_revision == "0011_demo_sessions"
