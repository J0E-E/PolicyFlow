"""The pipeline resolver — turn a tenant's registry config into board columns.

`resolve_pipeline` reads a tenant's `stage_labels` + `enabled_optional_stages`
(from the frozen `TenantConfig`, P2.2 D1) and returns the stages that tenant's
board shows: the canonical forward spine in order, with any disabled optional
stage dropped, each carrying the tenant's display label. It is **pure logic — no
database, no I/O, no framework** — the board endpoint serializes its result and
later epics feed the same enabled set into the stage machine.

The stage *machine* (`state.py`) stays tenant-agnostic and takes an enabled set as
an argument; this module is the one place that derives that tenant view from the
registry, mirroring how `brand_primary_color` is registry config served to the FE.
"""

from dataclasses import dataclass

from ..tenancy.registry import TenantConfig
from .state import CANONICAL_FORWARD_ORDER, OPTIONAL_STAGES


@dataclass(frozen=True)
class StageView:
    """One enabled stage as the board shows it (P2.2 §5.2).

    `key` is the canonical `OpportunityStage` value (the stored, tenant-agnostic
    spelling — what events and transitions use); `label` is this tenant's display
    string (the override, or the canonical value when none); `is_optional` marks a
    toggleable stage (`Quoted` / `Approved`) so the board can style it distinctly.
    """

    key: str
    label: str
    is_optional: bool


def resolve_pipeline(tenant_config: TenantConfig) -> list[StageView]:
    """Return the tenant's enabled stages in canonical order, with its labels.

    Walks `CANONICAL_FORWARD_ORDER` and keeps every stage except an optional one
    the tenant has not switched on (`enabled_optional_stages`), so a tenant with
    `Approved` disabled simply omits that column (its `Submitted` is followed by
    `Policy Active`). Each kept stage carries the tenant's `stage_labels` override
    or, absent one, its canonical value. `Lost` is off-spine and never a column.
    """
    views: list[StageView] = []
    for stage in CANONICAL_FORWARD_ORDER:
        is_optional = stage in OPTIONAL_STAGES
        if is_optional and stage.value not in tenant_config.enabled_optional_stages:
            continue
        label = tenant_config.stage_labels.get(stage.value, stage.value)
        views.append(StageView(key=stage.value, label=label, is_optional=is_optional))
    return views
