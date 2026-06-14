"""DB tests for the seed step that inserts the demo PII records (Epic 10).

These run against the real Postgres booted in Docker (the same `database_engine`
substrate as the other seed tests). They prove `app.seed.seed_pii_demo_records`,
driven through the full `seed(db)`:

- after a seed, each tenant's own `pii_demo` table holds exactly the 2 synthetic
  demo rows the spec defines;
- the Sunshine tenant carries at least one row with a non-null
  `mock_medicare_id_encrypted` (the 65+ /w-Medicare persona), while the Florida
  rows carry none (younger /wo-Medicare personas);
- a re-seed is idempotent: the count-based skip leaves each tenant at 2 rows.

The encrypted INSERT path resolves per-tenant keys via `get_tenant_keys`, which
reads the wrapped root key through the module-global `app.pii.keys.session_factory`
— a session separate from the seed's own. The `container_session_factory` fixture
monkeypatches that global to the container engine so the key load reads the real,
migrated, just-seeded key store.

The container database is **session-scoped and shared** (other tests also seed and
write `pii_demo` rows), so each test here first **clears** both tenants' `pii_demo`
tables — owning its precondition — then seeds, so the count-based idempotency
behaves deterministically regardless of test ordering. `pytest.ini` sets
`asyncio_mode = auto`, so the async tests carry no `@pytest.mark.asyncio` decorator.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.pii import keys as keys_module
from app.seed import seed
from app.tenancy.registry import FLORIDA, SUNSHINE


@pytest.fixture
def container_session_factory(database_engine, monkeypatch):
    """Point `app.pii.keys.session_factory` at the migrated container database.

    The seed encrypts each field, and `get_tenant_keys` reads the wrapped root key
    through the module-global `session_factory`. This swaps that global for a
    sessionmaker bound to the container engine so the key load reads the real,
    seeded key store; `monkeypatch` restores the real factory after each test.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    monkeypatch.setattr(keys_module, "session_factory", session_factory)
    return session_factory


async def _clear_demo_rows(session_factory: async_sessionmaker) -> None:
    """Empty both tenants' `pii_demo` tables so a following seed starts clean.

    The container database is shared across the whole test session, so this owns
    the precondition for the count-based idempotency assertions below regardless
    of what other tests have written. The schema identifiers come only from the
    registry, never user input.
    """
    async with session_factory() as session:
        for schema_name in (SUNSHINE.schema_name, FLORIDA.schema_name):
            await session.execute(text(f"DELETE FROM {schema_name}.pii_demo"))
        await session.commit()


async def _count_rows(session_factory: async_sessionmaker, schema_name: str) -> int:
    """Return the number of rows in `<schema_name>.pii_demo`."""
    async with session_factory() as session:
        return (
            await session.execute(
                text(f"SELECT COUNT(*) FROM {schema_name}.pii_demo")
            )
        ).scalar_one()


async def _count_rows_with_medicare(
    session_factory: async_sessionmaker, schema_name: str
) -> int:
    """Return the number of `<schema_name>.pii_demo` rows that carry a Medicare id."""
    async with session_factory() as session:
        return (
            await session.execute(
                text(
                    f"SELECT COUNT(*) FROM {schema_name}.pii_demo "
                    "WHERE mock_medicare_id_encrypted IS NOT NULL"
                )
            )
        ).scalar_one()


async def test_seed_inserts_two_demo_rows_per_tenant(
    container_session_factory, db_session
):
    """After seeding a cleared store, each tenant's `pii_demo` holds 2 demo rows."""
    await _clear_demo_rows(container_session_factory)

    await seed(db_session)

    assert await _count_rows(container_session_factory, SUNSHINE.schema_name) == 2
    assert await _count_rows(container_session_factory, FLORIDA.schema_name) == 2


async def test_sunshine_has_a_medicare_row_and_florida_has_none(
    container_session_factory, db_session
):
    """Sunshine carries a /w-Medicare row; Florida's younger personas carry none."""
    await _clear_demo_rows(container_session_factory)

    await seed(db_session)

    sunshine_with_medicare = await _count_rows_with_medicare(
        container_session_factory, SUNSHINE.schema_name
    )
    florida_with_medicare = await _count_rows_with_medicare(
        container_session_factory, FLORIDA.schema_name
    )

    assert sunshine_with_medicare >= 1
    assert florida_with_medicare == 0


async def test_re_seed_is_idempotent_and_leaves_two_rows_per_tenant(
    container_session_factory, db_session
):
    """A second seed adds no new demo rows — the count-based skip holds them at 2."""
    await _clear_demo_rows(container_session_factory)

    await seed(db_session)
    await seed(db_session)

    assert await _count_rows(container_session_factory, SUNSHINE.schema_name) == 2
    assert await _count_rows(container_session_factory, FLORIDA.schema_name) == 2
