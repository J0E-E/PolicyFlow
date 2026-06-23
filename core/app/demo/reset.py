"""The operator on-demand reset CLI — `python -m app.demo.reset [--all|--expired]`.

The by-hand trigger for the purge engine (TDD §5.5): an operator clears either every
demo session's overlay (`--all`, the canonical reset) or only the expired ones
(`--expired`, the gentle sweep) from a shell, reusing the **same** `purge_sessions`
engine the scheduler (Epic 10) and the session-scoped reset (Epic 11) call. Both
operator scopes purge the **whole** footprint — leads, ledger, **and** the
`demo_sessions` rows — so they pass `delete_session_row=True`.

This entry point is **not** reachable through the demo role switcher (`assume-persona`):
it is a deliberately out-of-band operator tool, run from a shell with database creds,
never from the public HTTP surface. Exactly one of `--all` / `--expired` is required
(an argparse mutually-exclusive required group), so neither a missing flag nor both at
once can run an ambiguous purge — argparse exits non-zero with a usage error.

The flag→scope mapping is a pure function (`scope_for`) kept separate from the
`asyncio.run` + `print` of `main`, so a test can prove the mapping (and the zero/both
flag errors) without driving the engine, then a single end-to-end test drives one
real run.
"""

import argparse
import asyncio

from app.demo.purge import All, Expired, PurgeCounts, PurgeScope, purge_sessions


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser: a required, mutually-exclusive `--all`/`--expired`.

    A `required=True` mutually-exclusive group means argparse itself enforces
    "exactly one" — zero flags or both flags exit non-zero with a usage error, so the
    CLI can never run an ambiguous purge. No other arguments: the scope is the whole
    interface.
    """
    parser = argparse.ArgumentParser(
        prog="python -m app.demo.reset",
        description=(
            "Purge demo-session data: --all clears every session, --expired clears "
            "only the expired ones. Reuses the demo_purge engine."
        ),
    )
    scope_group = parser.add_mutually_exclusive_group(required=True)
    scope_group.add_argument(
        "--all",
        action="store_true",
        help="purge every demo session's overlay (the canonical reset).",
    )
    scope_group.add_argument(
        "--expired",
        action="store_true",
        help="purge only sessions whose expiry has passed (the gentle sweep).",
    )
    return parser


def scope_for(arguments: argparse.Namespace) -> PurgeScope:
    """Map parsed flags to the purge scope — `--all` → `All()`, `--expired` → `Expired()`.

    A pure function (no I/O) so the flag→scope contract is unit-testable on its own.
    The parser guarantees exactly one flag is set, so this is a simple either/or.
    """
    if arguments.all:
        return All()
    return Expired()


async def run(scope: PurgeScope) -> PurgeCounts:
    """Run one purge for `scope` with `delete_session_row=True`, return the counts.

    Both operator scopes (`All` / `Expired`) remove the whole session footprint —
    including the `demo_sessions` rows — so this always passes
    `delete_session_row=True`, unlike Epic 11's session-scoped reset.
    """
    return await purge_sessions(scope, delete_session_row=True)


def format_counts(scope: PurgeScope, counts: PurgeCounts) -> str:
    """Render the run's counts as a human-readable operator summary line."""
    return (
        f"demo purge ({type(scope).__name__}): "
        f"sessions={len(counts.session_ids)} "
        f"leads_deleted={counts.total_leads_deleted} "
        f"ledger_deleted={counts.ledger_deleted} "
        f"session_rows_deleted={counts.session_rows_deleted}"
    )


def main(argv: list[str] | None = None) -> None:
    """Parse `argv`, run the chosen purge via `asyncio.run`, and print the counts.

    `argv` defaults to `sys.argv[1:]` (argparse's own default). The mapping and the
    engine call are factored into `scope_for` / `run`, so this thin shell only wires
    argparse → `asyncio.run` → `print`.
    """
    arguments = build_parser().parse_args(argv)
    scope = scope_for(arguments)
    counts = asyncio.run(run(scope))
    print(format_counts(scope, counts))


if __name__ == "__main__":  # pragma: no cover - module entry point
    main()
