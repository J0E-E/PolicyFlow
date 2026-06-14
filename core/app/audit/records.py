"""The audit vocabulary — the single source of truth for audit-record values.

Phase P1.4 builds an append-only audit spine. Before any migration, service, or
wiring epic can be written, the whole phase needs one agreed set of *event
types* (`auth.login`, `pii.revealed`, …) and *outcomes* (`success` / `failure`)
pinned down in one place. Centralising them means the `0007` migration (Epic 2)
and the audit-emit service (Epic 4) can never disagree on a spelling — the same
single-source-of-truth move already used for the RBAC `Capability` enum.

This module is **pure data — no database, no I/O**. Both enums are transcribed
verbatim from the TDD §5 *Interfaces*, so the values are frozen by the spec, not
invented. `tests/test_audit_records.py` asserts every member against an
independent hand-written expectation so the vocabulary can never silently drift.
"""

from enum import StrEnum

__all__ = ["EventType", "Outcome"]


class EventType(StrEnum):
    """One member per audited kind of sensitive action.

    Each string value is the dotted name the audit record stores in its
    `event_type` column. Transcribed verbatim from the TDD §5 *Interfaces*.
    """

    AUTH_LOGIN = "auth.login"
    AUTH_LOGOUT = "auth.logout"
    PII_REVEALED = "pii.revealed"
    RECORD_CREATED = "record.created"
    PLATFORM_CROSS_TENANT_READ = "platform.cross_tenant_read"
    AUDIT_VIEWED = "audit.viewed"


class Outcome(StrEnum):
    """The result an audit record stores in its `outcome` column.

    `denied` is reserved for a future RBAC-denial outcome but is **not** defined
    yet — auditing RBAC-denied (403) attempts is deferred per TDD Decision 6, so
    no speculative member is added until a real consumer needs it.
    """

    SUCCESS = "success"
    FAILURE = "failure"
    # DENIED = "denied"  # reserved — RBAC-denial auditing deferred (TDD Decision 6)
