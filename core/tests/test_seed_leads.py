"""DB tests for the demo-lead seed (`app.seed.seed_demo_leads`) — Epic 16, P1.7.

These run against the real Postgres booted in Docker (the same `database_engine`
substrate as the other seed tests). They prove the minimal lead seed, driven
through the full `seed(db)`:

- after a seed, each tenant's own `leads` table holds exactly the 4 demo leads the
  spec defines (3 ordinary fillers + 1 duplicate-bait), and every one is a **queue
  lead**: `public_form` source, unowned (`owner_user_id IS NULL`), born `New`;
- the duplicate-bait reliably **flags** — `find_duplicate_lead` run in each
  tenant's schema against Jordan Rivera's normalized email/phone returns the seeded
  bait row, proving the seed routed the bait through the same blind-index path the
  matcher reads (the cross-epic contract Epic 18's prefill submits);
- a re-seed is idempotent: the per-lead insert-if-absent (keyed on
  `email_blind_index`) leaves each tenant at 4 rows.

The seed encrypts each field, and `get_tenant_keys` reads the wrapped root key
through the module-global `app.pii.keys.session_factory` — a session separate from
the seed's own. The `db_session` fixture already depends on
`container_keys_session_factory`, which monkeypatches that global to the container
engine, so the key load reads the real, migrated, just-seeded key store.

The container database is **session-scoped and shared** (other tests also seed and
write `leads` rows), so each test here first **clears** both tenants' `leads`
tables — owning its precondition — then seeds, so the per-lead idempotency behaves
deterministically regardless of test ordering. `pytest.ini` sets
`asyncio_mode = auto`, so the async tests carry no `@pytest.mark.asyncio` decorator.
"""

import uuid

from sqlalchemy import select, text

from app.leads.matching import find_duplicate_lead
from app.models.tenant import Tenant
from app.seed import (
    DEMO_LEADS,
    JORDAN_RIVERA_BAIT_EMAIL,
    JORDAN_RIVERA_BAIT_PHONE,
    seed,
)
from app.tenancy.registry import FLORIDA, SUNSHINE


async def _tenant_id_for_slug(db_session, slug: str) -> uuid.UUID:
    """Return the seeded runtime tenant id for `slug` (its per-tenant keys' owner)."""
    return (
        await db_session.execute(select(Tenant.id).where(Tenant.slug == slug))
    ).scalar_one()


async def _clear_demo_leads(db_session) -> None:
    """Empty both tenants' `leads` tables so a following seed starts clean.

    The container database is shared across the whole test session, so this owns
    the precondition for the count/idempotency assertions below regardless of what
    other tests have written. The schema identifiers come only from the registry,
    never user input. Committed so the seed (its own transaction) sees the cleared
    tables.
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


async def test_seed_inserts_four_demo_leads_per_tenant(
    container_keys_session_factory, db_session
):
    """After seeding a cleared store, each tenant's `leads` holds 4 demo leads."""
    await _clear_demo_leads(db_session)

    await seed(db_session)

    assert await _count_leads(db_session, SUNSHINE.schema_name) == 4
    assert await _count_leads(db_session, FLORIDA.schema_name) == 4
    # The spec defines exactly four per tenant (3 fillers + 1 bait).
    assert len(DEMO_LEADS[SUNSHINE.slug]) == 4
    assert len(DEMO_LEADS[FLORIDA.slug]) == 4


async def test_every_seeded_lead_is_an_unassigned_new_queue_lead(
    container_keys_session_factory, db_session
):
    """Every seeded lead is `public_form`, unowned, born `New` — a queue lead."""
    await _clear_demo_leads(db_session)

    await seed(db_session)

    for schema_name in (SUNSHINE.schema_name, FLORIDA.schema_name):
        rows = (
            await db_session.execute(
                text(
                    f"SELECT status, lead_source, owner_user_id "
                    f"FROM {schema_name}.leads"
                )
            )
        ).all()
        assert len(rows) == 4
        for status, lead_source, owner_user_id in rows:
            assert status == "New"
            assert lead_source == "public_form"
            assert owner_user_id is None


async def test_duplicate_bait_flags_via_blind_index(
    container_keys_session_factory, db_session
):
    """The seeded bait is found by the matcher in each tenant — the duplicate scenario.

    Runs `find_duplicate_lead` (the matcher Epic 18's prefill triggers) against
    Jordan Rivera's normalized email/phone in each tenant's schema; it must return
    the seeded bait row, proving the seed wrote the bait through the same
    blind-index path the matcher reads.
    """
    await _clear_demo_leads(db_session)

    await seed(db_session)

    for tenant in (SUNSHINE, FLORIDA):
        # `Tenant` is `platform`-schema-bound, so this lookup is independent of the
        # `search_path` set next for the schema-less `Lead` the matcher queries.
        tenant_id = await _tenant_id_for_slug(db_session, tenant.slug)
        await db_session.execute(text(f"SET search_path TO {tenant.schema_name}"))

        match = await find_duplicate_lead(
            db_session,
            tenant_id,
            JORDAN_RIVERA_BAIT_EMAIL,
            JORDAN_RIVERA_BAIT_PHONE,
        )

        assert match is not None
        assert match.first_name == "Jordan"
        assert match.last_name == "Rivera"

    # Reset the session's search_path so it does not leak to a following test.
    await db_session.execute(text("SET search_path TO public"))


async def test_re_seed_is_idempotent_and_leaves_four_leads_per_tenant(
    container_keys_session_factory, db_session
):
    """A second seed adds no new leads — the per-lead insert-if-absent holds at 4."""
    await _clear_demo_leads(db_session)

    await seed(db_session)
    await seed(db_session)

    assert await _count_leads(db_session, SUNSHINE.schema_name) == 4
    assert await _count_leads(db_session, FLORIDA.schema_name) == 4
