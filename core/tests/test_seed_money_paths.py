"""DB tests for the boot seed's baseline money-path chains — P2.4 Epic 5.

The boot seed builds whole baseline chains — household → contact → opportunity →
application → policy — in both tenants as shared read-only rows (`demo_session_id
IS NULL`), so the renewal sweeps (Epics 6/8) and the cross-sell prompt (Epic 13)
have real targets in a fresh demo session. These run against the real Postgres
booted in Docker (the same `database_engine` substrate as the other seed tests).

The container database is **session-scoped and shared**, so each test first clears
both tenants' money-path tables (and `leads`) — owning its precondition — then
seeds. The seed encrypts contact PII, so `db_session` depends (transitively) on the
container key store via `container_keys_session_factory`. `pytest.ini` sets
`asyncio_mode = auto`, so the async tests carry no decorator.
"""

from datetime import datetime, timezone

from sqlalchemy import text

from app.renewals.rules import anniversary_within
from app.seed import BASELINE_MONEY_PATH_HOUSEHOLDS, seed
from app.tenancy.registry import FLORIDA, SUNSHINE

# Deleted child-first so a plain DELETE never trips a constraint (there are none —
# the money path is FK-free — but the order reads as the dependency order anyway).
_MONEY_PATH_TABLES = (
    "tasks",
    "policies",
    "applications",
    "opportunities",
    "contacts",
    "households",
    "leads",
)


async def _clear_money_paths(db_session) -> None:
    """Empty both tenants' money-path tables (and `leads`) so a seed starts clean.

    The container database is shared across the whole test session, so this owns the
    precondition for the count assertions regardless of what other tests wrote. The
    schema identifiers come only from the registry, never user input. Committed so the
    seed (its own transaction) sees the cleared tables.
    """
    for schema_name in (SUNSHINE.schema_name, FLORIDA.schema_name):
        for table in _MONEY_PATH_TABLES:
            await db_session.execute(text(f"DELETE FROM {schema_name}.{table}"))
    await db_session.commit()


async def _count(db_session, schema_name: str, table: str) -> int:
    """Return the baseline (`demo_session_id IS NULL`) row count of a table."""
    return (
        await db_session.execute(
            text(
                f"SELECT COUNT(*) FROM {schema_name}.{table} "
                "WHERE demo_session_id IS NULL"
            )
        )
    ).scalar_one()


async def _baseline_policy_lines(db_session, schema_name: str) -> list[str]:
    """Return the product lines of a tenant's baseline policies (via the opp join).

    Coverage is derived exactly as Epic 13 will: a policy's line is its originating
    opportunity's `product_line`, joined on `policy.opportunity_id`.
    """
    rows = (
        await db_session.execute(
            text(
                f"SELECT opportunity.product_line "
                f"FROM {schema_name}.policies AS policy "
                f"JOIN {schema_name}.opportunities AS opportunity "
                "ON policy.opportunity_id = opportunity.id "
                "WHERE policy.demo_session_id IS NULL"
            )
        )
    ).all()
    return [product_line for (product_line,) in rows]


async def test_boot_seed_inserts_one_full_chain_per_tenant(
    container_keys_session_factory, db_session
):
    """Each tenant gets one baseline household + contact + backing lead and N chains.

    N is the tenant's number of seeded policies (3 for Sunshine, 4 for Florida); each
    policy has its own opportunity and application, all rolling up to the one household.
    """
    await _clear_money_paths(db_session)

    await seed(db_session)

    for tenant in (SUNSHINE, FLORIDA):
        expected_policies = len(BASELINE_MONEY_PATH_HOUSEHOLDS[tenant.slug]["policies"])
        schema = tenant.schema_name

        assert await _count(db_session, schema, "households") == 1
        assert await _count(db_session, schema, "contacts") == 1
        assert await _count(db_session, schema, "opportunities") == expected_policies
        assert await _count(db_session, schema, "applications") == expected_policies
        assert await _count(db_session, schema, "policies") == expected_policies
        # Exactly one `Converted` backing lead the contact chains back to.
        converted_leads = (
            await db_session.execute(
                text(
                    f"SELECT COUNT(*) FROM {schema}.leads "
                    "WHERE status = 'Converted' AND demo_session_id IS NULL"
                )
            )
        ).scalar_one()
        assert converted_leads == 1


async def test_sunshine_has_exactly_one_baseline_medicare_advantage_policy(
    container_keys_session_factory, db_session
):
    """Sunshine seeds exactly one baseline MA policy (Epic 6 depends on {1,0})."""
    await _clear_money_paths(db_session)

    await seed(db_session)

    lines = await _baseline_policy_lines(db_session, SUNSHINE.schema_name)
    assert lines.count("medicare_advantage") == 1


async def test_seeded_supplement_policy_anniversary_is_inside_the_window(
    container_keys_session_factory, db_session
):
    """The back-dated Medicare Supplement policy's next anniversary is within 60 days.

    This is the anniversary sweep's target (Epic 8): the seed back-dates its `issued_at`
    so `rules.anniversary_within` reports it in-window against the seed-run date.
    """
    await _clear_money_paths(db_session)

    await seed(db_session)

    issued_at = (
        await db_session.execute(
            text(
                f"SELECT policy.issued_at "
                f"FROM {SUNSHINE.schema_name}.policies AS policy "
                f"JOIN {SUNSHINE.schema_name}.opportunities AS opportunity "
                "ON policy.opportunity_id = opportunity.id "
                "WHERE opportunity.product_line = 'medicare_supplement' "
                "AND policy.demo_session_id IS NULL"
            )
        )
    ).scalar_one()

    today = datetime.now(timezone.utc).date()
    assert anniversary_within(issued_at.date(), today, 60) is True


async def test_sunshine_is_partially_covered_florida_is_fully_covered(
    container_keys_session_factory, db_session
):
    """Coverage shape: Sunshine's household is partial (one open line); Florida is full.

    Coverage is the `policy → opportunity.product_line` join Epic 13 uses. Sunshine
    leaves `dental_vision_hearing` uncovered (a cross-sell prompt target); Florida
    covers every one of its lines (the prompt is suppressed).
    """
    await _clear_money_paths(db_session)

    await seed(db_session)

    sunshine_covered = set(
        await _baseline_policy_lines(db_session, SUNSHINE.schema_name)
    )
    sunshine_lines = {line.key for line in SUNSHINE.product_lines}
    assert sunshine_covered == {
        "medicare_advantage",
        "medicare_supplement",
        "final_expense",
    }
    assert sunshine_lines - sunshine_covered == {"dental_vision_hearing"}

    florida_covered = set(
        await _baseline_policy_lines(db_session, FLORIDA.schema_name)
    )
    florida_lines = {line.key for line in FLORIDA.product_lines}
    assert florida_covered == florida_lines
    assert florida_lines - florida_covered == set()


async def test_baseline_note_tasks_render_for_the_queue(
    container_keys_session_factory, db_session
):
    """Each tenant seeds baseline `note` tasks on its contact, split by assignee.

    Sunshine seeds two (one agent.one, one agent.two) to exercise the role-scoped
    queue; Florida seeds one agent.one note. All hang off the household's contact and
    open in the shared baseline.
    """
    await _clear_money_paths(db_session)

    await seed(db_session)

    async def _note_assignees(schema_name: str) -> list[str]:
        rows = (
            await db_session.execute(
                text(
                    f"SELECT task.assignee_username "
                    f"FROM {schema_name}.tasks AS task "
                    f"JOIN {schema_name}.contacts AS contact "
                    "ON task.related_entity_id = contact.id "
                    "WHERE task.task_type = 'note' "
                    "AND task.related_entity_type = 'contact' "
                    "AND task.status = 'open' "
                    "AND task.demo_session_id IS NULL"
                )
            )
        ).all()
        return [assignee for (assignee,) in rows]

    sunshine_assignees = await _note_assignees(SUNSHINE.schema_name)
    assert len(sunshine_assignees) == 2
    assert {username.split("@")[0] for username in sunshine_assignees} == {
        "agent.one",
        "agent.two",
    }

    florida_assignees = await _note_assignees(FLORIDA.schema_name)
    assert len(florida_assignees) == 1
    assert florida_assignees[0].split("@")[0] == "agent.one"


async def test_re_seed_inserts_no_duplicate_chains(
    container_keys_session_factory, db_session
):
    """A second boot seed adds no further chains (count-based household idempotency).

    The money-path seed skips a tenant whose baseline holds any household, so a re-run
    on every reboot never duplicates the chains — and the existing rows are untouched
    (their ids and back-dated `issued_at` are byte-identical, the documented drift only
    arising on a *fresh* re-seed against a new run date).
    """
    await _clear_money_paths(db_session)

    await seed(db_session)

    def _policy_fingerprint(rows):
        return {(str(policy_id), policy_number, issued_at) for policy_id, policy_number, issued_at in rows}

    async def _policies(schema_name):
        return (
            await db_session.execute(
                text(
                    f"SELECT id, policy_number, issued_at "
                    f"FROM {schema_name}.policies WHERE demo_session_id IS NULL"
                )
            )
        ).all()

    before = {
        schema: _policy_fingerprint(await _policies(schema))
        for schema in (SUNSHINE.schema_name, FLORIDA.schema_name)
    }

    await seed(db_session)

    for schema in (SUNSHINE.schema_name, FLORIDA.schema_name):
        after = _policy_fingerprint(await _policies(schema))
        assert after == before[schema]
        assert after, "expected a non-empty baseline policy set"
