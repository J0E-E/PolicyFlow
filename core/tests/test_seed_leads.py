"""DB tests for the boot seed's relationship to `leads` — P1.8 Epic 7.

These run against the real Postgres booted in Docker (the same `database_engine`
substrate as the other seed tests). Originally (P1.7 Epic 16) this file proved the
boot seed inserted 4 New-queue demo leads per tenant. P1.8 Epic 7 **split that set
out** of the boot seed: the New-queue templates (3 fillers + the Jordan Rivera
dup-bait) now live in `app.seed.SESSION_LEAD_TEMPLATES` and are stamped into a
visitor's own private, session-tagged queue by `ensure_session_leads` on first
`assume-persona` (proven in `test_session_lead_instantiation.py`), never by the
shared boot seed. The shared-historical read-only `leads` set arrives in Epic 8.

So the boot-seed contract this file now guards is the **negative** one: a boot
seed inserts **no** `leads` rows. The templates structure is asserted to still
carry the canonical 4-per-tenant shape (the data Epic 7's instantiation consumes).

The seed encrypts each PII field, and `get_tenant_keys` reads the wrapped root key
through the module-global `app.pii.keys.session_factory`. The `db_session` fixture
depends on `container_keys_session_factory`, which monkeypatches that global to the
container engine. The container database is **session-scoped and shared** (other
tests also seed and write `leads` rows), so each test here first **clears** both
tenants' `leads` tables — owning its precondition — then seeds. `pytest.ini` sets
`asyncio_mode = auto`, so the async tests carry no `@pytest.mark.asyncio`.
"""

from sqlalchemy import text

from app.seed import SESSION_LEAD_TEMPLATES, seed
from app.tenancy.registry import FLORIDA, SUNSHINE


async def _clear_demo_leads(db_session) -> None:
    """Empty both tenants' `leads` tables so a following seed starts clean.

    The container database is shared across the whole test session, so this owns
    the precondition for the count assertions below regardless of what other tests
    have written. The schema identifiers come only from the registry, never user
    input. Committed so the seed (its own transaction) sees the cleared tables.
    """
    for schema_name in (SUNSHINE.schema_name, FLORIDA.schema_name):
        await db_session.execute(text(f"DELETE FROM {schema_name}.leads"))
    await db_session.commit()


async def _count_leads(db_session, schema_name: str) -> int:
    """Return the number of rows in `<schema_name>.leads`."""
    return (
        await db_session.execute(
            text(f"SELECT COUNT(*) FROM {schema_name}.leads")
        )
    ).scalar_one()


async def test_boot_seed_inserts_no_leads(
    container_keys_session_factory, db_session
):
    """After a boot seed, each tenant's `leads` table stays empty (the Epic 7 split).

    The New-queue set moved to per-session instantiation, and the shared-historical
    set is Epic 8, so the boot seed inserts no `leads` rows at all.
    """
    await _clear_demo_leads(db_session)

    await seed(db_session)

    assert await _count_leads(db_session, SUNSHINE.schema_name) == 0
    assert await _count_leads(db_session, FLORIDA.schema_name) == 0


async def test_re_seed_still_inserts_no_leads(
    container_keys_session_factory, db_session
):
    """A second boot seed also adds no `leads` rows — the split is stable."""
    await _clear_demo_leads(db_session)

    await seed(db_session)
    await seed(db_session)

    assert await _count_leads(db_session, SUNSHINE.schema_name) == 0
    assert await _count_leads(db_session, FLORIDA.schema_name) == 0


def test_session_lead_templates_carry_four_per_tenant():
    """The per-session templates keep the canonical 3 fillers + 1 dup-bait shape.

    A pure-data assertion on the structure `ensure_session_leads` consumes — the
    boot seed no longer inserts these, but the canonical set Epic 7 instantiates
    is still the 4-per-tenant New queue.
    """
    assert len(SESSION_LEAD_TEMPLATES[SUNSHINE.slug]) == 4
    assert len(SESSION_LEAD_TEMPLATES[FLORIDA.slug]) == 4
