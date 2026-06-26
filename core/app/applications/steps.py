"""The product-specific application step contract (P2.3 Epic 6).

A Draft application captures one product-specific step before it can be submitted,
chosen by the product line's `application_step` (registry, Epic 2): ``"beneficiary"``
(the life-style lines), ``"health"`` (the health-style lines), or ``None`` (Medicare
/ dental — no extra step). This module pins the **content** of each step as data —
the beneficiary field keys and the health-question keys — so the capture endpoint
validates against the same contract the agent-workspace form renders, and a test can
cross-check both. Pure data, no DB / no framework.

The exact fields and questions are the epic-time **content** decision (TDD R4 / D10):
a single primary beneficiary (`full_name` / `relationship` / `date_of_birth`) and
five yes/no health questions. They are deliberately simple, mock underwriting input
— never used for a real decision (the carrier decision keys only off the contact
email, TDD §5.6).
"""

from ..tenancy.registry import TenantConfig

# The beneficiary step's fields (the life-style lines). A single primary
# beneficiary; all three are required when the step is captured.
BENEFICIARY_FIELDS: tuple[str, ...] = ("full_name", "relationship", "date_of_birth")

# The health step's questions (the health-style lines), as yes/no answer keys. All
# five are required when the step is captured; the agent-workspace form supplies the
# human-readable prompts.
HEALTH_QUESTION_KEYS: tuple[str, ...] = (
    "tobacco_use",
    "hospitalized_recently",
    "chronic_condition",
    "prescription_medications",
    "family_history",
)

# The valid `application_step` values (mirrors `ProductLine.application_step`).
BENEFICIARY_STEP = "beneficiary"
HEALTH_STEP = "health"


def application_step_for(
    product_line_key: str, tenant_config: TenantConfig
) -> str | None:
    """Return the `application_step` for a product line, or `None` if it has no step.

    Reads the registry — the single source of truth for which step a product line
    captures (D10). Returns `None` both for a line with no step (Medicare / dental)
    and for an unknown key, so the caller treats an unmapped line as step-less.
    """
    for product_line in tenant_config.product_lines:
        if product_line.key == product_line_key:
            return product_line.application_step
    return None
