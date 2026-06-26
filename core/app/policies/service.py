"""Policy issuance (P2.3 §5.5 / D8) — auto-issue on approval, in the approve txn.

`issue_policy` runs inside the approve transaction (called by
`applications.service.submit_application` when the carrier decision approves): it
creates one `Policy` row with the carrier / product / coverage / premium **copied
from the application**, a deterministic human-readable `policy_number`, emits
`policy.created`, and advances the opportunity to *Policy Active* via the internal
stage-setter — the customer-visible end of the happy path. Like the rest of the
money path it runs on the caller's request session and does **not** commit, so the
policy row, the opportunity move, and the event land or roll back together.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ..events.catalog import EventType
from ..events.envelope import build_envelope
from ..events.outbox import enqueue_event
from ..models.application import Application
from ..models.opportunity import Opportunity
from ..models.policy import Policy
from ..models.user import Role
from ..opportunities.service import set_stage_internal
from ..opportunities.state import OpportunityStage

# The issued-policy status — every issued policy lands Active (no lapse/cancel this
# phase).
POLICY_STATUS_ACTIVE = "Active"


def policy_number(prefix: str, application_id: uuid.UUID, year: int) -> str:
    """Return the human-readable policy number `POL-<PREFIX>-<YEAR>-<6HEX>` (D8).

    The six hex characters are the first of the application's uuid, so the number is
    **deterministic given the application** (no random suffix) — re-issuing the same
    application yields the same number within a year. It is not byte-identical across
    re-seeds (a fresh application uuid, possibly a different year), which the
    repeatable demo does not require (C6).
    """
    return f"POL-{prefix}-{year}-{application_id.hex[:6].upper()}"


async def issue_policy(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    application: Application,
    opportunity: Opportunity,
    policy_prefix: str,
    actor_user_id: uuid.UUID | None,
    actor_role: Role | None,
    demo_session_id: uuid.UUID | None,
) -> Policy:
    """Issue the policy for an approved application; advance the opportunity.

    Creates the `Policy` row (terms copied from the application, a deterministic
    number from `policy_prefix` + the application uuid + the current year), emits
    `policy.created`, and advances the opportunity to *Policy Active* via the internal
    stage-setter — all on the request transaction. Returns the new, flushed `Policy`.
    """
    issued_year = datetime.now(timezone.utc).year
    policy = Policy(
        id=uuid.uuid4(),
        opportunity_id=opportunity.id,
        application_id=application.id,
        contact_id=application.contact_id,
        policy_number=policy_number(policy_prefix, application.id, issued_year),
        carrier=application.carrier,
        product_label=application.product_label,
        coverage_amount=application.coverage_amount,
        premium_monthly=application.premium_monthly,
        premium_annual=application.premium_annual,
        status=POLICY_STATUS_ACTIVE,
        correlation_id=application.correlation_id,
        demo_session_id=demo_session_id,
    )
    db.add(policy)
    await db.flush()

    await enqueue_event(
        db,
        build_envelope(
            event_type=EventType.POLICY_CREATED,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            payload={
                "entity_id": str(policy.id),
                "opportunity_id": str(opportunity.id),
                "application_id": str(application.id),
            },
            correlation_id=application.correlation_id,
            causation_id=None,
            demo_session_id=demo_session_id,
        ),
    )

    await set_stage_internal(
        db,
        tenant_id,
        opportunity=opportunity,
        target_stage=OpportunityStage.POLICY_ACTIVE,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        demo_session_id=demo_session_id,
    )
    return policy
