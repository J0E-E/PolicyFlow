"""The RBAC capability matrix — the single source of truth for authorization.

A **capability** is one thing a user might be permitted to do (e.g. reveal PII,
view dashboards). A **role** is the kind of user (Agent, Tenant Admin, Read-Only,
Platform Admin). `CAPABILITIES` maps every role to the exact set of capabilities
it holds, transcribed verbatim from the Requirements §Authorization table in the
TDD. `has_capability(role, capability)` is the tiny lookup the auth dependencies
(Epic 7) build `require_capability(...)` on top of.

This dict is the authorization spec in code form. `tests/test_rbac.py` asserts it
cell-by-cell against an independent copy of the table, so the matrix can never
silently drift from the spec.

`Role` is **not** redefined here — it is imported from `models.user`, its single
source of truth, and re-exported for callers that want both names from one place.
"""

from enum import StrEnum

from ..models.user import Role

__all__ = ["Role", "Capability", "CAPABILITIES", "has_capability"]


class Capability(StrEnum):
    """One member per Requirements §Authorization row.

    Each string value is the lowercase snake-case of the member name. These are
    the discrete permissions the matrix grants to roles.
    """

    VIEW_TENANT_RECORDS = "view_tenant_records"
    CREATE_EDIT_RECORDS = "create_edit_records"
    CLAIM_LEADS_MANAGE_TASKS = "claim_leads_manage_tasks"
    REASSIGN_LEADS_TASKS = "reassign_leads_tasks"
    REVEAL_PII = "reveal_pii"
    REPLAY_DISCARD_DLQ = "replay_discard_dlq"
    VIEW_TENANT_CONFIG = "view_tenant_config"
    VIEW_AUDIT_LOGS = "view_audit_logs"
    VIEW_DASHBOARDS = "view_dashboards"
    PLATFORM_HEALTH_DEMO_CONTROLS = "platform_health_demo_controls"


# The normative role → capabilities matrix, transcribed verbatim from the
# Requirements §Authorization table in the TDD. Each value is a frozenset (the
# source of truth is immutable). This is asserted cell-by-cell in the tests.
CAPABILITIES: dict[Role, frozenset[Capability]] = {
    Role.AGENT: frozenset(
        {
            Capability.VIEW_TENANT_RECORDS,
            Capability.CREATE_EDIT_RECORDS,
            Capability.CLAIM_LEADS_MANAGE_TASKS,
            Capability.REVEAL_PII,
            Capability.VIEW_DASHBOARDS,
        }
    ),
    Role.TENANT_ADMIN: frozenset(
        {
            Capability.VIEW_TENANT_RECORDS,
            Capability.CREATE_EDIT_RECORDS,
            Capability.CLAIM_LEADS_MANAGE_TASKS,
            Capability.REASSIGN_LEADS_TASKS,
            Capability.REVEAL_PII,
            Capability.REPLAY_DISCARD_DLQ,
            Capability.VIEW_TENANT_CONFIG,
            Capability.VIEW_AUDIT_LOGS,
            Capability.VIEW_DASHBOARDS,
        }
    ),
    Role.READ_ONLY: frozenset(
        {
            Capability.VIEW_TENANT_RECORDS,
            Capability.VIEW_AUDIT_LOGS,
            Capability.VIEW_DASHBOARDS,
        }
    ),
    Role.PLATFORM_ADMIN: frozenset(
        {
            Capability.REPLAY_DISCARD_DLQ,
            Capability.PLATFORM_HEALTH_DEMO_CONTROLS,
        }
    ),
}


def has_capability(role: Role, capability: Capability) -> bool:
    """Return whether `role` holds `capability` per the `CAPABILITIES` matrix."""
    return capability in CAPABILITIES[role]
