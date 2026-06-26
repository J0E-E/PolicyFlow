"""The stage-change action — the one mutation that moves an opportunity forward.

`change_opportunity_stage` validates a stage move against the pure machine
(`app.opportunities.state`), records the new stage on an already-loaded
opportunity, and emits the pipeline event(s) onto the request transaction — the
P2.2 sibling of the P2.1 `convert_lead` action. Like that action it runs on the
caller's request session and **does not commit**, so the row write and the event
enqueue land or roll back together (the transactional outbox).

The endpoint owns the guards (capability → load → holder → transition); this core
assumes an already-guarded, already-loaded opportunity and a tenant `enabled_stages`
set computed by the caller, so the machine stays pure and tenant-agnostic.

This is the **tracer slice**: it advances one stage and emits
`opportunity.stage_changed`. The Medicare eligibility gate (Epic 5) and the
`Lost` branch that also emits `opportunity.lost` (Epic 6) layer on here later.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from ..events.catalog import EventType as EventBusEventType
from ..events.envelope import build_envelope
from ..events.outbox import enqueue_event
from ..models.opportunity import Opportunity
from ..models.user import Role
from .state import OpportunityStage, assert_transition


async def _emit(
    db: AsyncSession,
    *,
    event_type: EventBusEventType,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    actor_role: Role | None,
    payload: dict,
    correlation_id: uuid.UUID,
    demo_session_id: uuid.UUID | None,
) -> None:
    """Enqueue one pipeline event onto this tenant's outbox on the request session.

    A thin wrapper over `build_envelope` + `enqueue_event` that pins the P2.2
    invariants in one place (mirrors the conversion `_emit`): every pipeline event
    reuses the opportunity's `correlation_id`, carries `causation_id=None`, and
    rides the caller's request transaction so it lands or rolls back with the
    stage write.
    """
    await enqueue_event(
        db,
        build_envelope(
            event_type=event_type,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            payload=payload,
            correlation_id=correlation_id,
            causation_id=None,
            demo_session_id=demo_session_id,
        ),
    )


async def change_opportunity_stage(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    opportunity: Opportunity,
    target_stage: OpportunityStage,
    enabled_stages: frozenset[OpportunityStage],
    actor_user_id: uuid.UUID | None,
    actor_role: Role | None,
    demo_session_id: uuid.UUID | None,
) -> Opportunity:
    """Move `opportunity` to `target_stage`, validated, and emit the change event.

    Asserts the move is legal for the tenant's `enabled_stages` (raising
    `InvalidStageTransition`, which the endpoint maps to 409), sets the new stage,
    flushes, and emits `opportunity.stage_changed` on the request transaction.
    Returns the same opportunity instance, now at the new stage. Does **not**
    commit — the caller's `get_tenant_db` transaction owns that.
    """
    current_stage = OpportunityStage(opportunity.stage)
    assert_transition(current_stage, target_stage, enabled_stages)

    opportunity.stage = target_stage.value
    await db.flush()

    await _emit(
        db,
        event_type=EventBusEventType.OPPORTUNITY_STAGE_CHANGED,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        payload={
            "entity_id": str(opportunity.id),
            "from_stage": current_stage.value,
            "to_stage": target_stage.value,
            "contact_id": str(opportunity.contact_id),
            "household_id": str(opportunity.household_id),
        },
        correlation_id=opportunity.correlation_id,
        demo_session_id=demo_session_id,
    )

    return opportunity
