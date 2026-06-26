"""The quote-selection action — create a Draft Application from a chosen quote (P2.3).

`select_quote` is the request-side action behind `POST /api/opportunities/{id}/
applications`: it creates a `Draft` `Application` with the carrier / product /
coverage / premium **copied from the selected quote** (a frozen snapshot), sets the
opportunity's `estimated_annual_premium` to the quote's annual premium, advances the
opportunity to *Application Started* via the **internal stage-setter** (D6 — the
automation path drives this automation-owned stage directly, bypassing the manual
machine), and emits `application.started`.

Like the P2.2 stage action and the P2.3 quote request, it runs on the caller's
request session and **does not commit**, so the application write, the opportunity
move, and both events land or roll back together (the synchronous, in-transaction
coupling of D6). The endpoint owns the guards; this assumes an already-guarded,
already-loaded opportunity and quote.
"""

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from ..events.catalog import EventType
from ..events.envelope import build_envelope
from ..events.outbox import enqueue_event
from ..models.application import Application
from ..models.opportunity import Opportunity
from ..models.quote import Quote
from ..models.user import Role
from ..opportunities.service import set_stage_internal
from ..opportunities.state import OpportunityStage
from .state import ApplicationStatus


async def select_quote(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    opportunity: Opportunity,
    quote: Quote,
    actor_user_id: uuid.UUID | None,
    actor_role: Role | None,
    demo_session_id: uuid.UUID | None,
) -> Application:
    """Create the Draft Application, advance the opportunity, emit `application.started`.

    Copies the quote's carrier / product / coverage / premium onto a new `Draft`
    `Application`, sets the opportunity's `estimated_annual_premium` to the quote's
    annual premium, advances the opportunity to *Application Started* through the
    internal stage-setter, and emits `application.started` — all on the request
    transaction. Returns the new, flushed `Application`.
    """
    application = Application(
        id=uuid.uuid4(),
        opportunity_id=opportunity.id,
        contact_id=opportunity.contact_id,
        product_line=opportunity.product_line,
        selected_quote_id=quote.id,
        status=ApplicationStatus.DRAFT.value,
        carrier=quote.carrier,
        product_label=quote.product_label,
        coverage_amount=quote.coverage_amount,
        premium_monthly=quote.premium_monthly,
        premium_annual=quote.premium_annual,
        correlation_id=opportunity.correlation_id,
        demo_session_id=demo_session_id,
    )
    db.add(application)
    await db.flush()

    # The selection sets the opportunity's headline value (BRD §6.2) — the quote's
    # annual premium, as the opportunity's `Numeric` estimated premium.
    opportunity.estimated_annual_premium = Decimal(quote.premium_annual)

    # Advance the opportunity to the automation-owned *Application Started* stage via
    # the internal setter (bypassing the manual machine), in this same transaction.
    await set_stage_internal(
        db,
        tenant_id,
        opportunity=opportunity,
        target_stage=OpportunityStage.APPLICATION_STARTED,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        demo_session_id=demo_session_id,
    )

    await enqueue_event(
        db,
        build_envelope(
            event_type=EventType.APPLICATION_STARTED,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            payload={
                "entity_id": str(application.id),
                "opportunity_id": str(opportunity.id),
                "contact_id": str(opportunity.contact_id),
            },
            correlation_id=opportunity.correlation_id,
            causation_id=None,
            demo_session_id=demo_session_id,
        ),
    )
    return application


async def capture_application_step(
    db: AsyncSession,
    *,
    application: Application,
    beneficiary: dict | None = None,
    health_answers: dict | None = None,
) -> Application:
    """Record the captured product step on a Draft application (Epic 6).

    Sets whichever of `beneficiary` / `health_answers` the caller supplies onto the
    application's jsonb columns and flushes — the endpoint owns the validation that
    the right one is supplied for the product line's step. Runs on the caller's
    request session and does **not** commit. Returns the same application instance.
    """
    if beneficiary is not None:
        application.beneficiary = beneficiary
    if health_answers is not None:
        application.health_answers = health_answers
    await db.flush()
    return application
