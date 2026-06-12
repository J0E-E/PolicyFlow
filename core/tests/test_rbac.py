"""Exhaustive unit test for the RBAC capability matrix.

Pure logic, no DB / no Docker / no async (sync functions, matching the suite's
style for non-async tests; see `test_models.py`).

The expected mapping below is built **independently** from the production
`CAPABILITIES` dict — it transcribes the same normative Requirements
§Authorization table by hand. That makes every cell assertion a genuine
cross-check against the spec rather than a tautology over the dict under test.
"""

from app.auth.rbac import CAPABILITIES, Capability, Role, has_capability

# Independent transcription of the normative matrix (one row per capability,
# the four roles in column order: Agent, Tenant Admin, Read-Only, Platform
# Admin). `True` == the cell is marked ✓ in the table. Hand-built here on
# purpose, separate from the production `CAPABILITIES` dict.
EXPECTED_CELLS: dict[Capability, dict[Role, bool]] = {
    #                                  Agent  T.Admin  R.Only  P.Admin
    Capability.VIEW_TENANT_RECORDS: {
        Role.AGENT: True,
        Role.TENANT_ADMIN: True,
        Role.READ_ONLY: True,
        Role.PLATFORM_ADMIN: False,
    },
    Capability.CREATE_EDIT_RECORDS: {
        Role.AGENT: True,
        Role.TENANT_ADMIN: True,
        Role.READ_ONLY: False,
        Role.PLATFORM_ADMIN: False,
    },
    Capability.CLAIM_LEADS_MANAGE_TASKS: {
        Role.AGENT: True,
        Role.TENANT_ADMIN: True,
        Role.READ_ONLY: False,
        Role.PLATFORM_ADMIN: False,
    },
    Capability.REASSIGN_LEADS_TASKS: {
        Role.AGENT: False,
        Role.TENANT_ADMIN: True,
        Role.READ_ONLY: False,
        Role.PLATFORM_ADMIN: False,
    },
    Capability.REVEAL_PII: {
        Role.AGENT: True,
        Role.TENANT_ADMIN: True,
        Role.READ_ONLY: False,
        Role.PLATFORM_ADMIN: False,
    },
    Capability.REPLAY_DISCARD_DLQ: {
        Role.AGENT: False,
        Role.TENANT_ADMIN: True,
        Role.READ_ONLY: False,
        Role.PLATFORM_ADMIN: True,
    },
    Capability.VIEW_TENANT_CONFIG: {
        Role.AGENT: False,
        Role.TENANT_ADMIN: True,
        Role.READ_ONLY: False,
        Role.PLATFORM_ADMIN: False,
    },
    Capability.VIEW_AUDIT_LOGS: {
        Role.AGENT: False,
        Role.TENANT_ADMIN: True,
        Role.READ_ONLY: True,
        Role.PLATFORM_ADMIN: False,
    },
    Capability.VIEW_DASHBOARDS: {
        Role.AGENT: True,
        Role.TENANT_ADMIN: True,
        Role.READ_ONLY: True,
        Role.PLATFORM_ADMIN: False,
    },
    Capability.PLATFORM_HEALTH_DEMO_CONTROLS: {
        Role.AGENT: False,
        Role.TENANT_ADMIN: False,
        Role.READ_ONLY: False,
        Role.PLATFORM_ADMIN: True,
    },
}


def test_has_capability_matches_the_matrix_for_every_cell():
    """`has_capability` agrees with the spec for all 40 (role, capability) cells."""
    for capability, expected_by_role in EXPECTED_CELLS.items():
        for role, is_allowed in expected_by_role.items():
            assert has_capability(role, capability) is is_allowed, (
                f"{role} / {capability} expected {is_allowed}"
            )


def test_every_role_is_keyed_in_the_matrix():
    """`CAPABILITIES` has an entry for all four roles."""
    assert set(CAPABILITIES.keys()) == set(Role)


def test_every_capability_is_covered_by_the_expectation():
    """The expectation table accounts for every `Capability` member."""
    assert set(EXPECTED_CELLS.keys()) == set(Capability)


def test_each_matrix_value_is_a_frozenset():
    """Every role's capability set is an immutable `frozenset`."""
    for role, capabilities in CAPABILITIES.items():
        assert isinstance(capabilities, frozenset), role
