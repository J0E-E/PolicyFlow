"""Application read serialization (P2.3) — the one shape every endpoint returns.

`serialize_application` is the single source of truth for an application's wire
shape, so the select endpoint (Epic 5), the step-capture PATCH (Epic 6), and later
the submit / decision / policy reads all return the **same** fields. It carries the
frozen carrier / product / coverage / premium snapshot, the lifecycle `status`, the
product line's `application_step` (so the agent-workspace knows which step form to
render), and the captured step content (`beneficiary` / `health_answers`). All
non-PII — the Tenant-1 Medicare ID is added masked by Epic 11, never raw here.
"""

from ..models.application import Application


def serialize_application(
    application: Application, application_step: str | None
) -> dict:
    """Return one application's non-PII wire shape, with its product step.

    `application_step` is resolved by the caller from the registry (the step the
    product line captures, or `None`). The `beneficiary` / `health_answers` jsonb are
    returned as-is — `None` until the step is captured.
    """
    return {
        "id": str(application.id),
        "opportunity_id": str(application.opportunity_id),
        "product_line": application.product_line,
        "selected_quote_id": str(application.selected_quote_id),
        "status": application.status,
        "carrier": application.carrier,
        "product_label": application.product_label,
        "coverage_amount": application.coverage_amount,
        "premium_monthly": application.premium_monthly,
        "premium_annual": application.premium_annual,
        "application_step": application_step,
        "beneficiary": application.beneficiary,
        "health_answers": application.health_answers,
        "decision": application.decision,
        "decided_at": (
            application.decided_at.isoformat()
            if application.decided_at is not None
            else None
        ),
    }
