"""Policy read serialization (P2.3) — the issued-policy wire shape.

`serialize_policy` is the single source of truth for an issued policy's wire shape,
returned by the submit endpoint (on approval) and the agent-workspace policy view.
All non-PII — the Tenant-1 Medicare ID is added masked by Epic 11, never raw here.
"""

from ..models.policy import Policy


def serialize_policy(policy: Policy, medicare_id_masked: str | None = None) -> dict:
    """Return one policy's non-PII wire shape.

    `medicare_id_masked` is the masked Medicare ID of the policy's application (D9 —
    masked on Policy reads too), or `None` when the tenant does not collect one or the
    application captured none. The policy itself stores no Medicare ID; the reveal
    rides the linked `application_id`. Never the plaintext.
    """
    return {
        "id": str(policy.id),
        "opportunity_id": str(policy.opportunity_id),
        "application_id": str(policy.application_id),
        "policy_number": policy.policy_number,
        "status": policy.status,
        "carrier": policy.carrier,
        "product_label": policy.product_label,
        "coverage_amount": policy.coverage_amount,
        "premium_monthly": policy.premium_monthly,
        "premium_annual": policy.premium_annual,
        "issued_at": policy.issued_at.isoformat() if policy.issued_at is not None else None,
        "medicare_id_masked": medicare_id_masked,
    }
