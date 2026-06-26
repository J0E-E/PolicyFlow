"""The applications API — the product-step capture (P2.3 Epic 6) and later actions.

`PATCH /api/applications/{id}` records the product-specific step on a Draft
application — the beneficiary details (life lines) or the health answers (health
lines), chosen by the product line's `application_step` (D10). Later P2.3 epics add
the submit action and the Medicare-ID reveal under this same router.

The endpoint rides `get_tenant_db`, so isolation is automatic (the caller's schema
scopes every query). It guards in the same order as the opportunity mutations: load
/ `404`, demo-session write-isolation (foreign `404`, seed `409`), holder (the
owning agent or a Tenant Admin, via the application's opportunity) / `403`, then the
Draft-only and step-shape checks.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import require_capability
from ..auth.provider import Identity
from ..auth.rbac import Capability
from ..demo.session import current_demo_session
from ..models.application import Application
from ..models.contact import Contact
from ..models.opportunity import Opportunity
from ..models.user import Role
from ..tenancy.registry import TenantConfig, tenant_by_schema
from ..tenancy.scoping import get_tenant_db
from .read import serialize_application
from .service import capture_application_step, submit_application
from .state import ApplicationStatus, InvalidApplicationTransition
from .steps import (
    BENEFICIARY_FIELDS,
    BENEFICIARY_STEP,
    HEALTH_QUESTION_KEYS,
    HEALTH_STEP,
    application_step_for,
)

router = APIRouter(prefix="/api/applications", tags=["applications"])


class CaptureStepRequest(BaseModel):
    """The step-capture body — the beneficiary details or the health answers.

    Exactly one is supplied, matching the product line's step; the endpoint rejects
    a body that does not match (or one missing required keys).
    """

    beneficiary: dict | None = None
    health_answers: dict | None = None


async def _active_tenant_config(db: AsyncSession) -> TenantConfig:
    """Resolve the caller's tenant config from the scoped session's schema."""
    active_schema = (await db.execute(text("SELECT current_schema()"))).scalar_one()
    return tenant_by_schema(active_schema)


async def _guard_application_for_session(
    application: Application, request: Request, db: AsyncSession
) -> uuid.UUID | None:
    """Enforce demo-session write-isolation on an already-loaded application.

    Mirrors `opportunities.router._guard_opportunity_for_session`: a row owned by
    **another** session is a `404` (indistinguishable from not-found), and a shared
    **seed** row (`demo_session_id IS NULL`) while the caller is in a live session is
    a `409`. Returns the resolved session id.
    """
    demo_session = await current_demo_session(request, db)
    demo_session_id = demo_session.id if demo_session is not None else None

    if (
        application.demo_session_id is not None
        and application.demo_session_id != demo_session_id
    ):
        raise HTTPException(status_code=404, detail="application not found")

    if demo_session_id is not None and application.demo_session_id is None:
        raise HTTPException(
            status_code=409, detail="seed applications cannot be modified"
        )

    return demo_session_id


async def _assert_holder(
    application: Application, identity: Identity, db: AsyncSession
) -> None:
    """Allow only the owning agent or a Tenant Admin to act on the application.

    The application has no owner of its own; the holder is the owner of its
    opportunity (the same rule the select endpoint applied). A non-holder is a `403`.
    """
    opportunity = (
        await db.execute(
            select(Opportunity).where(Opportunity.id == application.opportunity_id)
        )
    ).scalar_one_or_none()
    is_owner = (
        opportunity is not None and opportunity.owner_user_id == identity.user_id
    )
    is_tenant_admin = identity.role == Role.TENANT_ADMIN
    if not (is_owner or is_tenant_admin):
        raise HTTPException(
            status_code=403,
            detail="only the opportunity's owner or a tenant admin can edit the application",
        )


def _validated_step_payload(
    application_step: str | None, capture: CaptureStepRequest
) -> tuple[dict | None, dict | None]:
    """Validate the body matches the product line's step; return `(beneficiary, health)`.

    Raises a `422` when the line has no step, when the wrong field is supplied for
    the step, or when the supplied object is missing a required key. The health
    answers must each be a boolean (a yes/no question). Returns exactly the one
    object to store, the other `None`.
    """
    if application_step is None:
        raise HTTPException(
            status_code=422, detail="this product line has no application step"
        )

    if application_step == BENEFICIARY_STEP:
        if capture.beneficiary is None:
            raise HTTPException(
                status_code=422, detail="beneficiary details are required for this line"
            )
        missing = [field for field in BENEFICIARY_FIELDS if not capture.beneficiary.get(field)]
        if missing:
            raise HTTPException(
                status_code=422, detail=f"missing beneficiary fields: {', '.join(missing)}"
            )
        return {field: capture.beneficiary[field] for field in BENEFICIARY_FIELDS}, None

    # The health step.
    if capture.health_answers is None:
        raise HTTPException(
            status_code=422, detail="health answers are required for this line"
        )
    missing = [key for key in HEALTH_QUESTION_KEYS if key not in capture.health_answers]
    if missing:
        raise HTTPException(
            status_code=422, detail=f"missing health answers: {', '.join(missing)}"
        )
    if any(not isinstance(capture.health_answers[key], bool) for key in HEALTH_QUESTION_KEYS):
        raise HTTPException(
            status_code=422, detail="each health answer must be true or false"
        )
    return None, {key: capture.health_answers[key] for key in HEALTH_QUESTION_KEYS}


@router.patch("/{application_id}")
async def capture_step(
    application_id: uuid.UUID,
    capture: CaptureStepRequest,
    request: Request,
    identity: Identity = Depends(require_capability(Capability.CREATE_EDIT_RECORDS)),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Capture the product-specific step on a Draft application.

    Guards in order: load / `404`, demo-session write-isolation (foreign `404`, seed
    `409`), holder / `403`, Draft-only (`409` — a submitted application is frozen),
    then the step-shape validation (`422`). On success the captured `beneficiary` /
    `health_answers` are stored and the updated application is returned under
    `{"application": …}`.
    """
    application = (
        await db.execute(select(Application).where(Application.id == application_id))
    ).scalar_one_or_none()
    if application is None:
        raise HTTPException(status_code=404, detail="application not found")

    await _guard_application_for_session(application, request, db)
    await _assert_holder(application, identity, db)

    if ApplicationStatus(application.status) != ApplicationStatus.DRAFT:
        raise HTTPException(
            status_code=409, detail="only a draft application can capture its step"
        )

    tenant_config = await _active_tenant_config(db)
    application_step = application_step_for(application.product_line, tenant_config)
    beneficiary, health_answers = _validated_step_payload(application_step, capture)

    await capture_application_step(
        db, application=application, beneficiary=beneficiary, health_answers=health_answers
    )
    return {"application": serialize_application(application, application_step)}


def _step_is_incomplete(application: Application, application_step: str | None) -> bool:
    """Return whether a line with a step has not yet captured it.

    A line with no step is always complete; a beneficiary / health line is complete
    only once its jsonb column is filled. Submit requires a complete step so an
    application is never decided without the content the product line needs.
    """
    if application_step == BENEFICIARY_STEP:
        return application.beneficiary is None
    if application_step == HEALTH_STEP:
        return application.health_answers is None
    return False


@router.post("/{application_id}/submit")
async def submit(
    application_id: uuid.UUID,
    request: Request,
    identity: Identity = Depends(require_capability(Capability.CREATE_EDIT_RECORDS)),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Submit a Draft application and run the inline carrier decision.

    Guards in order: load / `404`, demo-session write-isolation (foreign `404`, seed
    `409`), holder / `403`, Draft-only (`409`), and a complete product step (`409` —
    a line with a step must have captured it). On success `submit_application` moves
    the application to *Submitted*, runs the deterministic carrier decision (the
    decrypted contact email's `deny` substring → declined, else approved — never
    logged or returned), couples the outcome to the opportunity, and emits the
    lifecycle events. The decided application and the opportunity's new stage are
    returned.
    """
    application = (
        await db.execute(select(Application).where(Application.id == application_id))
    ).scalar_one_or_none()
    if application is None:
        raise HTTPException(status_code=404, detail="application not found")

    demo_session_id = await _guard_application_for_session(application, request, db)
    await _assert_holder(application, identity, db)

    if ApplicationStatus(application.status) != ApplicationStatus.DRAFT:
        raise HTTPException(
            status_code=409, detail="only a draft application can be submitted"
        )

    tenant_config = await _active_tenant_config(db)
    application_step = application_step_for(application.product_line, tenant_config)
    if _step_is_incomplete(application, application_step):
        raise HTTPException(
            status_code=409, detail="complete the application step before submitting"
        )

    opportunity = (
        await db.execute(
            select(Opportunity).where(Opportunity.id == application.opportunity_id)
        )
    ).scalar_one_or_none()
    contact = (
        await db.execute(select(Contact).where(Contact.id == application.contact_id))
    ).scalar_one_or_none()
    if opportunity is None or contact is None:
        raise HTTPException(status_code=409, detail="application is missing its links")

    try:
        await submit_application(
            db,
            identity.tenant_id,
            application=application,
            opportunity=opportunity,
            contact=contact,
            actor_user_id=identity.user_id,
            actor_role=identity.role,
            demo_session_id=demo_session_id,
        )
    except InvalidApplicationTransition:
        raise HTTPException(status_code=409, detail="application cannot be submitted")

    return {
        "application": serialize_application(application, application_step),
        "opportunity_stage": opportunity.stage,
    }
