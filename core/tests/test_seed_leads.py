"""DB tests for the boot seed's shared historical `leads` set — P1.8 Epic 8.

These run against the real Postgres booted in Docker (the same `database_engine`
substrate as the other seed tests). Originally (P1.7 Epic 16) this file proved the
boot seed inserted 4 New-queue demo leads per tenant; P1.8 Epic 7 **split that set
out** of the boot seed (the New-queue templates moved to `SESSION_LEAD_TEMPLATES`,
stamped into a visitor's own session-tagged queue by `ensure_session_leads`), and
this file briefly guarded the **negative** contract that the boot seed touched no
`leads` at all.

P1.8 Epic 8 brings the **positive** contract back, but for a different set: the boot
seed now inserts the shared **read-only historical** leads — `SHARED_HISTORICAL_LEADS`
(6 per tenant: 2 Working / 2 Qualified / 2 Rejected, all owned, split 3/3 across
`agent.one` + `agent.two`) — as the shared `demo_session_id IS NULL` baseline so lists
and dashboards render non-trivially from seed alone. Every row stays `NULL` (read-only,
visible to all, never claimable). So this file now guards: a boot seed inserts 6
`NULL`-session historical leads per tenant with the agreed status/owner spread, and a
re-seed is a no-op (count-based idempotency on the `NULL` baseline).

The seed encrypts each PII field, and `get_tenant_keys` reads the wrapped root key
through the module-global `app.pii.keys.session_factory`. The `db_session` fixture
depends on `container_keys_session_factory`, which monkeypatches that global to the
container engine. The container database is **session-scoped and shared** (other
tests also seed and write `leads` rows), so each test here first **clears** both
tenants' `leads` tables — owning its precondition — then seeds. `pytest.ini` sets
`asyncio_mode = auto`, so the async tests carry no `@pytest.mark.asyncio`.
"""

from sqlalchemy import text

from app.seed import SESSION_LEAD_TEMPLATES, SHARED_HISTORICAL_LEADS, seed
from app.tenancy.registry import FLORIDA, SUNSHINE, tenant_by_slug

# The expected shared-historical row count per tenant (2 Working + 2 Qualified +
# 2 Rejected = 6), derived from the canonical set so the count can never drift.
EXPECTED_HISTORICAL_LEADS_PER_TENANT = 6


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


# The boot seed also inserts one baseline money-path chain per tenant (P2.4 Epic 5),
# whose backing lead is a `Converted`, `demo_session_id IS NULL` row. That row is part
# of the shared baseline too, so these historical-lead assertions filter it out by
# status — the shared **historical** set is exactly the Working / Qualified / Rejected
# rows this file owns.
_MONEY_PATH_BACKING_LEAD_STATUS = "Converted"


async def _count_historical_leads(db_session, schema_name: str) -> int:
    """Return the number of shared historical (non-`Converted`) rows in `leads`."""
    return (
        await db_session.execute(
            text(
                f"SELECT COUNT(*) FROM {schema_name}.leads "
                "WHERE status <> :backing_status"
            ),
            {"backing_status": _MONEY_PATH_BACKING_LEAD_STATUS},
        )
    ).scalar_one()


async def _count_null_session_historical_leads(db_session, schema_name: str) -> int:
    """Return the shared-baseline (`NULL`) historical (non-`Converted`) lead count."""
    return (
        await db_session.execute(
            text(
                f"SELECT COUNT(*) FROM {schema_name}.leads "
                "WHERE demo_session_id IS NULL AND status <> :backing_status"
            ),
            {"backing_status": _MONEY_PATH_BACKING_LEAD_STATUS},
        )
    ).scalar_one()


async def _historical_rows(db_session, schema_name: str) -> list:
    """Return the (status, owner_username, demo_session_id) of every historical lead.

    Excludes the money-path backing lead (`Converted`), so the rows are exactly the
    shared historical set this file owns.
    """
    return (
        await db_session.execute(
            text(
                f"SELECT status, owner_username, demo_session_id "
                f"FROM {schema_name}.leads WHERE status <> :backing_status"
            ),
            {"backing_status": _MONEY_PATH_BACKING_LEAD_STATUS},
        )
    ).all()


async def test_boot_seed_inserts_six_null_session_historical_leads_per_tenant(
    container_keys_session_factory, db_session
):
    """After a boot seed, each tenant carries 6 shared `NULL`-session historical leads.

    The shared-historical set (P1.8 Epic 8) is the read-only baseline; every row is
    `demo_session_id IS NULL` so it is visible to all and claimable by none.
    """
    await _clear_demo_leads(db_session)

    await seed(db_session)

    for schema_name in (SUNSHINE.schema_name, FLORIDA.schema_name):
        assert (
            await _count_historical_leads(db_session, schema_name)
            == EXPECTED_HISTORICAL_LEADS_PER_TENANT
        )
        # Every seeded historical row is part of the shared `NULL` baseline.
        assert (
            await _count_null_session_historical_leads(db_session, schema_name)
            == EXPECTED_HISTORICAL_LEADS_PER_TENANT
        )


async def test_re_seed_is_a_no_op_on_the_historical_leads(
    container_keys_session_factory, db_session
):
    """A second boot seed adds no further historical leads (count-based idempotency).

    The shared-historical seed skips a tenant whose `leads` already holds any
    `demo_session_id IS NULL` row, so re-running on every reboot never duplicates it.
    """
    await _clear_demo_leads(db_session)

    await seed(db_session)
    await seed(db_session)

    for schema_name in (SUNSHINE.schema_name, FLORIDA.schema_name):
        assert (
            await _count_historical_leads(db_session, schema_name)
            == EXPECTED_HISTORICAL_LEADS_PER_TENANT
        )


async def test_seeded_historical_leads_carry_the_agreed_status_and_owner_spread(
    container_keys_session_factory, db_session
):
    """Each tenant's seeded rows are 2/2/2 by status, all `NULL`, owned 3/3 by agent.

    Proves the boot seed wrote the canonical shape: every row in the shared `NULL`
    baseline, the status mix 2 Working / 2 Qualified / 2 Rejected, and ownership
    split 3/3 across the two seeded agents (resolved to their email-style usernames).
    """
    await _clear_demo_leads(db_session)

    await seed(db_session)

    for tenant_config in (SUNSHINE, FLORIDA):
        rows = await _historical_rows(db_session, tenant_config.schema_name)
        assert len(rows) == EXPECTED_HISTORICAL_LEADS_PER_TENANT

        # Every row is part of the shared baseline — never a session row.
        assert all(demo_session_id is None for _status, _owner, demo_session_id in rows)

        status_counts: dict[str, int] = {}
        owner_counts: dict[str, int] = {}
        for status, owner_username, _demo_session_id in rows:
            status_counts[status] = status_counts.get(status, 0) + 1
            owner_counts[owner_username] = owner_counts.get(owner_username, 0) + 1

        assert status_counts == {"Working": 2, "Qualified": 2, "Rejected": 2}

        # Every row is owned by one of the two seeded agents, split 3/3.
        domain = tenant_config.email_domain
        assert owner_counts == {
            f"agent.one@{domain}": 3,
            f"agent.two@{domain}": 3,
        }


def test_shared_historical_leads_carry_six_per_tenant():
    """The shared-historical set keeps the canonical 6-per-tenant shape (pure data).

    A no-DB assertion on the structure the boot seed consumes — 2 Working / 2
    Qualified / 2 Rejected per tenant.
    """
    assert len(SHARED_HISTORICAL_LEADS[SUNSHINE.slug]) == 6
    assert len(SHARED_HISTORICAL_LEADS[FLORIDA.slug]) == 6
    # The keys resolve to known tenants (guards against a slug typo in the data).
    for tenant_slug in SHARED_HISTORICAL_LEADS:
        assert tenant_by_slug(tenant_slug) is not None


def test_each_tenant_seeds_a_deny_decline_fixture_lead():
    """Each tenant's session queue carries a lead whose email contains `deny` (P2.3).

    The decline-thread prerequisite (R3 / C4): converting this lead and submitting its
    application takes the deterministic carrier-decline path. It lives in the session
    queue (not the shared baseline) so a live session can actually convert it, and on
    a non-Medicare-gated line so the quote round-trip is unblocked.
    """
    for tenant_slug in (SUNSHINE.slug, FLORIDA.slug):
        deny_leads = [
            lead
            for lead in SESSION_LEAD_TEMPLATES[tenant_slug]
            if "deny" in lead["email"].lower()
        ]
        assert len(deny_leads) == 1, tenant_slug
        # Non-Medicare-gated, so the round-trip to a quote is not blocked.
        product_lines = deny_leads[0]["product_lines_of_interest"]
        assert product_lines and all(
            line not in {"medicare_advantage", "medicare_supplement"}
            for line in product_lines
        )
