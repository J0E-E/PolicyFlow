"""DB tests for per-session seed instantiation — P1.8 Epic 7.

These run against the real Postgres booted in Docker (the same `database_engine` /
`db_session` substrate as the other seed tests). They prove
`app.demo.instantiation.ensure_session_leads`:

- **Instantiation tags the set into the right schema.** A first call for a live
  `(demo_session_id, tenant)` inserts every `SESSION_LEAD_TEMPLATES` row for that
  tenant into *that tenant's* `leads` table, each tagged with the session id and
  none other, all born `New` / unowned / `public_form` queue leads.
- **Idempotency is the ledger, not a per-lead skip.** A second call for the same
  `(visit, tenant)` is a no-op (ledger row present) — no duplicate rows.
- **A second visit gets its own copy.** A distinct `demo_session_id` seeds its own
  tagged set even though the dup-bait email repeats across visits — proving the
  guard is the ledger, never the boot seed's `email_blind_index` skip (which would
  wrongly suppress the second copy).

The encrypt path resolves per-tenant keys through `app.pii.keys.session_factory`;
the `db_session` fixture depends on `container_keys_session_factory`, which points
that global at the container engine. The container database is **session-scoped and
shared**, so each test first clears both tenants' `leads` and the seed ledger —
owning its precondition — then runs `seed(db_session)` so the tenants + keys exist.
`pytest.ini` sets `asyncio_mode = auto`, so the async tests carry no decorator.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.demo.instantiation import ensure_session_leads
from app.seed import SESSION_LEAD_TEMPLATES, seed
from app.tenancy.registry import FLORIDA, SUNSHINE


async def _reset_state(db_session) -> None:
    """Clear both tenants' `leads` and the whole seed ledger, then seed tenants/keys.

    Owns the precondition on the shared container: a clean `leads` table per tenant
    and an empty ledger so the count / idempotency assertions are deterministic
    regardless of test order. `seed(db_session)` (idempotent) guarantees the tenant
    rows and per-tenant data keys the encrypt path needs are present.
    """
    for schema_name in (SUNSHINE.schema_name, FLORIDA.schema_name):
        await db_session.execute(text(f"DELETE FROM {schema_name}.leads"))
    await db_session.execute(
        text("DELETE FROM platform.demo_session_tenant_seed")
    )
    await db_session.commit()
    await seed(db_session)


async def _mint_demo_session(db_session) -> uuid.UUID:
    """Insert a live `platform.demo_sessions` row and return its id.

    `ensure_session_leads` does not itself read `demo_sessions`, but a real row
    keeps the ledger's `(demo_session_id, tenant_slug)` referentially honest and
    mirrors the production flow where `assume-persona` has already minted it.
    """
    session_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO platform.demo_sessions (id, expires_at) "
            "VALUES (:id, :expires_at)"
        ),
        {
            "id": session_id,
            "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
        },
    )
    await db_session.commit()
    return session_id


async def _count_leads_for_session(
    db_session, schema_name: str, demo_session_id: uuid.UUID
) -> int:
    """Count `<schema>.leads` rows tagged with `demo_session_id`."""
    return (
        await db_session.execute(
            text(
                f"SELECT COUNT(*) FROM {schema_name}.leads "
                "WHERE demo_session_id = :demo_session_id"
            ),
            {"demo_session_id": demo_session_id},
        )
    ).scalar_one()


async def _count_all_leads(db_session, schema_name: str) -> int:
    """Count every **session-tagged** (`demo_session_id IS NOT NULL`) lead.

    These tests reason only about the rows `ensure_session_leads` produces (always
    session-tagged). Since P1.8 Epic 8 the boot seed — run by `_reset_state` — also
    inserts the shared read-only **historical** baseline as `demo_session_id IS NULL`
    rows, so an unscoped `COUNT(*)` would now include those 6-per-tenant baseline
    rows and break the exact-total assertions. Scoping to `IS NOT NULL` counts the
    instantiated set alone, preserving each assertion's original intent.
    """
    return (
        await db_session.execute(
            text(
                f"SELECT COUNT(*) FROM {schema_name}.leads "
                "WHERE demo_session_id IS NOT NULL"
            )
        )
    ).scalar_one()


async def test_instantiation_inserts_the_session_tagged_set(
    container_keys_session_factory, db_session
):
    """A first call tags the full template set into the tenant's own schema.

    Every inserted row carries the session id and is a `New` / unowned /
    `public_form` queue lead; the count matches the canonical 4-per-tenant set, and
    nothing lands in the *other* tenant's schema.
    """
    await _reset_state(db_session)
    session_id = await _mint_demo_session(db_session)

    inserted = await ensure_session_leads(db_session, SUNSHINE, session_id)

    assert inserted == len(SESSION_LEAD_TEMPLATES[SUNSHINE.slug]) == 4
    assert (
        await _count_leads_for_session(
            db_session, SUNSHINE.schema_name, session_id
        )
        == 4
    )
    # The set landed only in Sunshine's schema, not Florida's.
    assert await _count_all_leads(db_session, FLORIDA.schema_name) == 0

    # Scope to the session-tagged rows: since P1.8 Epic 8 the boot seed (run by
    # `_reset_state`) also leaves the shared historical `demo_session_id IS NULL`
    # baseline in this schema, which these per-row assertions deliberately exclude.
    rows = (
        await db_session.execute(
            text(
                f"SELECT status, lead_source, owner_user_id, demo_session_id "
                f"FROM {SUNSHINE.schema_name}.leads "
                "WHERE demo_session_id IS NOT NULL"
            )
        )
    ).all()
    assert len(rows) == 4
    for status, lead_source, owner_user_id, row_session_id in rows:
        assert status == "New"
        assert lead_source == "public_form"
        assert owner_user_id is None
        assert row_session_id == session_id


async def test_re_call_is_idempotent_via_ledger(
    container_keys_session_factory, db_session
):
    """A second call for the same (visit, tenant) inserts nothing — the ledger guards it."""
    await _reset_state(db_session)
    session_id = await _mint_demo_session(db_session)

    first = await ensure_session_leads(db_session, SUNSHINE, session_id)
    second = await ensure_session_leads(db_session, SUNSHINE, session_id)

    assert first == 4
    assert second == 0  # no-op: ledger row already present
    # Still exactly the one instantiated set — no duplicate rows.
    assert await _count_all_leads(db_session, SUNSHINE.schema_name) == 4
    # The ledger holds exactly one marker row for this (visit, tenant).
    ledger_count = (
        await db_session.execute(
            text(
                "SELECT COUNT(*) FROM platform.demo_session_tenant_seed "
                "WHERE demo_session_id = :id AND tenant_slug = :slug"
            ),
            {"id": session_id, "slug": SUNSHINE.slug},
        )
    ).scalar_one()
    assert ledger_count == 1


async def test_second_visit_gets_its_own_copy_despite_shared_bait_email(
    container_keys_session_factory, db_session
):
    """A distinct visit seeds its own tagged set even though the dup-bait email repeats.

    This is the load-bearing distinction from the boot seed: idempotency is the
    ledger, never a per-lead `email_blind_index` skip — so two different visits each
    own a full copy of the Jordan Rivera dup-bait (same email), isolated by session.
    """
    await _reset_state(db_session)
    first_session = await _mint_demo_session(db_session)
    second_session = await _mint_demo_session(db_session)

    await ensure_session_leads(db_session, SUNSHINE, first_session)
    inserted_second = await ensure_session_leads(
        db_session, SUNSHINE, second_session
    )

    assert inserted_second == 4
    # Each visit owns its own full copy, tagged by its own session id.
    assert (
        await _count_leads_for_session(
            db_session, SUNSHINE.schema_name, first_session
        )
        == 4
    )
    assert (
        await _count_leads_for_session(
            db_session, SUNSHINE.schema_name, second_session
        )
        == 4
    )
    # Eight rows total in the schema: two isolated copies of the same templates.
    assert await _count_all_leads(db_session, SUNSHINE.schema_name) == 8
