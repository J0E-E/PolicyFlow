"""Policy read serialization (P2.3) — the issued-policy wire shape.

`serialize_policy` is the single source of truth for an issued policy's wire shape,
returned by the submit endpoint (on approval) and the agent-workspace policy view.
All non-PII — the Tenant-1 Medicare ID is added masked by Epic 11, never raw here.
"""

from ..models.policy import Policy


def serialize_policy(policy: Policy) -> dict:
    """Return one policy's non-PII wire shape."""
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
    }
