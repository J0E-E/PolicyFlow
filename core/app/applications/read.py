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

# The fixed mask shown for a present-but-unrevealed Medicare ID (D9). A constant, not
# derived from the plaintext — the masked read never decrypts, so no PII is exposed.
MEDICARE_ID_MASK = "•••-••-••••"


def mask_medicare_id(application: Application, collects_medicare_id: bool) -> str | None:
    """Return the masked Medicare ID, or `None` when there is nothing to mask.

    `None` both when the tenant does not collect a Medicare ID (Tenant-2 never renders
    the field, D9) and when the application has not captured one yet. Otherwise the
    fixed `MEDICARE_ID_MASK` — the real value is only ever returned by the audited
    reveal endpoint.
    """
    if not collects_medicare_id or application.medicare_id_encrypted is None:
        return None
    return MEDICARE_ID_MASK


def serialize_application(
    application: Application,
    application_step: str | None,
    collects_medicare_id: bool = False,
) -> dict:
    """Return one application's non-PII wire shape, with its product step.

    `application_step` is resolved by the caller from the registry (the step the
    product line captures, or `None`). The `beneficiary` / `health_answers` jsonb are
    returned as-is — `None` until the step is captured. `collects_medicare_id` (the
    tenant's registry flag) tells the workspace whether to render the Medicare-ID
    field at all; `medicare_id_masked` is the masked value (or `None`) — never the
    plaintext, which only the reveal endpoint returns.
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
        "collects_medicare_id": collects_medicare_id,
        "medicare_id_masked": mask_medicare_id(application, collects_medicare_id),
    }
