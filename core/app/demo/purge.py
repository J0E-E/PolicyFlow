"""The purge engine — one sweep removes a demo session's overlay everywhere.

P1.8's whole lifecycle (24h expiry, nightly canonical reset, operator on-demand,
visitor session-scoped reset) reduces to **one** operation: remove a set of demo
sessions' overlay rows across every tenant schema, plus their ledger markers, plus
— when asked — the `demo_sessions` rows themselves (TDD §5.5 / D5). Because the
shared `NULL` baseline is never mutated, "reset to canonical state" *is* "delete the
overlays"; this module is that single delete, parameterized by **scope**.

**Scope (a small closed union).** `Session(id)` purges exactly one session's data
and **keeps** its `demo_sessions` row (the visitor's session continues — Epic 11's
reset); `Expired` and `All` (Epic 10's scheduler / the Epic 11 CLI) purge whole
session footprints **including** the rows. Each scope resolves to a list of in-scope
`demo_sessions.id`; the delete core is identical regardless of how the list was
chosen.

**Own session, dedicated role, one transaction.** Like `app.events.relay` and
`app.audit.service`, the engine holds a module-global `session_factory` (the engine
from `app.db`, monkeypatchable in tests) and opens its **own** short-lived session —
it is not part of any web request. It becomes the `demo_purge` role with a single
`SET LOCAL ROLE` (the `0013` + `0015` grants give that role SELECT + DELETE on every
tenant's `leads` and the four P2.1 conversion tables, and on the two platform demo
tables, nothing more) and runs the **whole** sweep in one transaction: delete every
tenant's conversion overlay (households / contacts / opportunities / tasks) and leads,
then the ledger rows, then — when `delete_session_row` — the session rows, then one
commit. Every statement is
fully schema-qualified (no `search_path` needed — the `audit/service.py` idiom);
the only interpolated identifiers are registry schema names, never user input.

**Observability (one INFO line per run).** Every run logs exactly one summary INFO
line — `scope`, in-scope session count, the per-tenant `leads_deleted` map,
`ledger_deleted`, and `session_rows_deleted` — in the house parameterized
`logger.info` idiom. The in-scope session **ids** log at DEBUG only (an `All`/nightly
run can name dozens). An empty/no-op run **still** logs at INFO: unlike the ~1s
relay's suppressed empty sweep, the purge cadence is slow, so "ran, deleted nothing"
is a wanted signal.
"""

import logging
import uuid
from dataclasses import dataclass, field
from typing import Union

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session_factory
from app.tenancy.registry import DEMO_PURGE_ROLE, TENANTS

__all__ = [
    "Expired",
    "All",
    "Session",
    "PurgeScope",
    "PurgeCounts",
    "purge_sessions",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Expired:
    """Scope: every session whose `expires_at` is in the past (the gentle sweep)."""


@dataclass(frozen=True)
class All:
    """Scope: every demo session (the nightly canonical reset / `--all`)."""


@dataclass(frozen=True)
class Session:
    """Scope: exactly one session, by id (the visitor's session-scoped reset)."""

    id: uuid.UUID


# The closed set of purge scopes. A new scope is a new member here + a branch in
# `_resolve_session_ids`; the delete core never changes.
PurgeScope = Union[Expired, All, Session]


@dataclass(frozen=True)
class PurgeCounts:
    """What one purge run deleted — the return value and the INFO line's source.

    `leads_deleted` and the four conversion-entity maps
    (`households_deleted` / `contacts_deleted` / `opportunities_deleted` /
    `tasks_deleted`, P2.1 Epic 10) map each tenant `schema_name` to the rows removed
    from that table; `ledger_deleted` and `session_rows_deleted` count the
    `demo_session_tenant_seed` and `demo_sessions` rows. `session_ids` is the
    in-scope set the scope resolved to (logged at DEBUG only). `session_rows_deleted`
    is always 0 when the caller passed `delete_session_row=False` (the `Session`
    reset keeps the row).
    """

    session_ids: tuple[uuid.UUID, ...]
    leads_deleted: dict[str, int] = field(default_factory=dict)
    households_deleted: dict[str, int] = field(default_factory=dict)
    contacts_deleted: dict[str, int] = field(default_factory=dict)
    opportunities_deleted: dict[str, int] = field(default_factory=dict)
    tasks_deleted: dict[str, int] = field(default_factory=dict)
    ledger_deleted: int = 0
    session_rows_deleted: int = 0

    @property
    def total_leads_deleted(self) -> int:
        """The total leads removed across every tenant schema."""
        return sum(self.leads_deleted.values())


async def _resolve_session_ids(
    session: AsyncSession, scope: PurgeScope
) -> list[uuid.UUID]:
    """Resolve a scope to the list of in-scope `demo_sessions.id`.

    `Session(id)` resolves to `[id]` without a query (the caller already named it).
    `Expired` selects `id WHERE expires_at < now()`; `All` selects every `id`. Both
    read `platform.demo_sessions` under the already-set `demo_purge` role (granted
    SELECT on that table by `0013`). The resolved list feeds the identical delete
    core regardless of scope.
    """
    if isinstance(scope, Session):
        return [scope.id]

    if isinstance(scope, Expired):
        rows = await session.execute(
            text(
                "SELECT id FROM platform.demo_sessions "
                "WHERE expires_at < now()"
            )
        )
    elif isinstance(scope, All):
        rows = await session.execute(
            text("SELECT id FROM platform.demo_sessions")
        )
    else:  # pragma: no cover - the union is closed; a new scope must add a branch.
        raise TypeError(f"unknown purge scope: {scope!r}")

    return [row[0] for row in rows]


async def purge_sessions(
    scope: PurgeScope, *, delete_session_row: bool
) -> PurgeCounts:
    """Delete the in-scope sessions' overlay everywhere, in one transaction.

    Opens the engine's **own** session, becomes the `demo_purge` role, resolves the
    scope to a list of `demo_sessions.id`, then in one transaction:

    1. `DELETE FROM <schema>.leads WHERE demo_session_id = ANY(:ids)` for **every**
       registry tenant schema (capturing each tenant's rowcount);
    2. `DELETE` the matching `platform.demo_session_tenant_seed` ledger rows;
    3. only when `delete_session_row` — `DELETE` the `platform.demo_sessions` rows.

    Then commits once and returns the `PurgeCounts`. An empty in-scope set is a clean
    no-op (every delete matches zero rows) and still logs one INFO line. The session
    schema names are registry constants, never user input, so interpolating them is
    safe (the `audit/service.py` `SET LOCAL ROLE` idiom); every id is a bound
    parameter.
    """
    async with session_factory() as session:
        await session.begin()
        # `DEMO_PURGE_ROLE` is a fixed registry constant, not user input, so this
        # identifier interpolation is safe (the `audit/service.py` idiom). One role
        # switch covers the whole sweep — the role reaches every tenant schema and
        # the platform demo tables (the `0013` grants).
        await session.execute(text(f"SET LOCAL ROLE {DEMO_PURGE_ROLE}"))

        session_ids = await _resolve_session_ids(session, scope)

        # Sweep every tenant's session-tagged overlay: the four P2.1 conversion
        # entities (Epic 10) plus `leads`. All five tables carry `demo_session_id`
        # directly, so each is one keyed DELETE; there are no FK constraints between
        # them (the schema boundary is the isolation layer), so the order is for
        # readability only — children (opportunities / tasks) before their contact,
        # contacts before households, leads last. A session contact that linked to a
        # NULL-baseline household is removed here while that household (its
        # `demo_session_id` is NULL, not the session's) correctly survives.
        leads_deleted: dict[str, int] = {}
        households_deleted: dict[str, int] = {}
        contacts_deleted: dict[str, int] = {}
        opportunities_deleted: dict[str, int] = {}
        tasks_deleted: dict[str, int] = {}
        table_counts = (
            ("opportunities", opportunities_deleted),
            ("tasks", tasks_deleted),
            ("contacts", contacts_deleted),
            ("households", households_deleted),
            ("leads", leads_deleted),
        )
        for tenant in TENANTS:
            for table_name, counts in table_counts:
                result = await session.execute(
                    text(
                        f"DELETE FROM {tenant.schema_name}.{table_name} "
                        "WHERE demo_session_id = ANY(:ids)"
                    ),
                    {"ids": session_ids},
                )
                counts[tenant.schema_name] = result.rowcount

        ledger_result = await session.execute(
            text(
                "DELETE FROM platform.demo_session_tenant_seed "
                "WHERE demo_session_id = ANY(:ids)"
            ),
            {"ids": session_ids},
        )
        ledger_deleted = ledger_result.rowcount

        session_rows_deleted = 0
        if delete_session_row:
            session_result = await session.execute(
                text(
                    "DELETE FROM platform.demo_sessions "
                    "WHERE id = ANY(:ids)"
                ),
                {"ids": session_ids},
            )
            session_rows_deleted = session_result.rowcount

        await session.commit()

    counts = PurgeCounts(
        session_ids=tuple(session_ids),
        leads_deleted=leads_deleted,
        households_deleted=households_deleted,
        contacts_deleted=contacts_deleted,
        opportunities_deleted=opportunities_deleted,
        tasks_deleted=tasks_deleted,
        ledger_deleted=ledger_deleted,
        session_rows_deleted=session_rows_deleted,
    )

    # One summary INFO line per run — even an empty/no-op run (the purge cadence is
    # slow, so "ran, deleted nothing" is a wanted signal). The in-scope ids stay at
    # DEBUG: an `All`/nightly run can name dozens.
    logger.info(
        "demo purge run: scope=%s sessions=%d leads_deleted=%s "
        "households_deleted=%s contacts_deleted=%s opportunities_deleted=%s "
        "tasks_deleted=%s ledger_deleted=%d session_rows_deleted=%d",
        type(scope).__name__,
        len(session_ids),
        leads_deleted,
        households_deleted,
        contacts_deleted,
        opportunities_deleted,
        tasks_deleted,
        ledger_deleted,
        session_rows_deleted,
    )
    logger.debug("demo purge in-scope session ids: %s", session_ids)

    return counts
