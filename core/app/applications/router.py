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
from ..opportunities.pipeline import enabled_stages_for
from ..opportunities.state import OpportunityStage
from ..pii.reveal_seam import on_pii_revealed
from ..pii.service import decrypt_field, encrypt_field
from ..policies.read import serialize_policy
from ..tenancy.registry import TenantConfig, tenant_by_schema
from ..tenancy.scoping import get_tenant_db
from .read import mask_medicare_id, serialize_application
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
    """The step-capture body — the beneficiary / health step and/or the Medicare ID.

    The step payload (`beneficiary` **or** `health_answers`, matching the product
    line's step) and the Tenant-1 `medicare_id` are independent captures; a body may
    carry either or both. The endpoint validates the step shape and gates the Medicare
    ID on the tenant's `collects_medicare_id`.
    """

    beneficiary: dict | None = None
    health_answers: dict | None = None
    medicare_id: str | None = None


async def _active_tenant_config(db: AsyncSession) -> TenantConfig:
    """Resolve the caller's tenant config from the scoped session's schema."""
    active_schema = (await db.execute(text("SELECT current_schema()"))).scalar_one()
    return tenant_by_schema(active_schema)


async def _guard_application_for_session(
    application: Application,
    request: Request,
    db: AsyncSession,
    *,
    refuse_seed: bool = True,
) -> uuid.UUID | None:
    """Enforce demo-session isolation on an already-loaded application.

    Mirrors `opportunities.router._guard_opportunity_for_session`: a row owned by
    **another** session is a `404` (indistinguishable from not-found). A shared
    **seed** row (`demo_session_id IS NULL`) while the caller is in a live session is
    a `409` when `refuse_seed` (the write paths), but allowed when not — the reveal is
    a read, and revealing shared seed PII is fine (the leads-reveal precedent).
    Returns the resolved session id.
    """
    demo_session = await current_demo_session(request, db)
    demo_session_id = demo_session.id if demo_session is not None else None

    if (
        application.demo_session_id is not None
        and application.demo_session_id != demo_session_id
    ):
        raise HTTPException(status_code=404, detail="application not found")

    if refuse_seed and demo_session_id is not None and application.demo_session_id is None:
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
    """Capture the product step and/or the Tenant-1 Medicare ID on a Draft application.

    Guards in order: load / `404`, demo-session write-isolation (foreign `404`, seed
    `409`), holder / `403`, Draft-only (`409` — a submitted application is frozen),
    then the capture validation (`422`). The product step (`beneficiary` /
    `health_answers`) is validated against the line's step; the `medicare_id` is
    **encrypted on capture** (`encrypt_field`) and gated on the tenant's
    `collects_medicare_id` (Tenant-2 sending one is a `422`). At least one valid
    capture must be supplied. The updated application is returned (with the Medicare
    ID **masked**) under `{"application": …}`.
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

    beneficiary: dict | None = None
    health_answers: dict | None = None
    medicare_id_encrypted: bytes | None = None

    # The product step (only when a step payload is sent — validated against the line).
    if capture.beneficiary is not None or capture.health_answers is not None:
        beneficiary, health_answers = _validated_step_payload(application_step, capture)

    # The Tenant-1 Medicare ID — gated on the registry flag, encrypted on capture.
    if capture.medicare_id is not None:
        if not tenant_config.collects_medicare_id:
            raise HTTPException(
                status_code=422, detail="this tenant does not collect a Medicare ID"
            )
        medicare_id_encrypted = await encrypt_field(identity.tenant_id, capture.medicare_id)

    if beneficiary is None and health_answers is None and medicare_id_encrypted is None:
        # Nothing valid supplied: surface the precise step error (the line's step is
        # the primary thing to capture; a no-step line that collects no Medicare ID
        # has nothing to capture at all).
        _validated_step_payload(application_step, capture)

    await capture_application_step(
        db,
        application=application,
        beneficiary=beneficiary,
        health_answers=health_answers,
        medicare_id_encrypted=medicare_id_encrypted,
    )
    return {
        "application": serialize_application(
            application, application_step, tenant_config.collects_medicare_id
        )
    }


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

    # The policy number's tenant prefix is the first three letters of the schema name
    # (e.g. `sunshine` → `SUN`, `florida` → `FLO`) — a stable per-tenant token.
    policy_prefix = tenant_config.schema_name[:3].upper()
    # On a decline the opportunity returns to *Quoted* when the tenant enables it,
    # else *Qualified* (D11/C3) — so the agent can re-select a different quote.
    enabled_stages = enabled_stages_for(tenant_config)
    decline_return_stage = (
        OpportunityStage.QUOTED
        if OpportunityStage.QUOTED in enabled_stages
        else OpportunityStage.QUALIFIED
    )
    try:
        _, policy = await submit_application(
            db,
            identity.tenant_id,
            application=application,
            opportunity=opportunity,
            contact=contact,
            policy_prefix=policy_prefix,
            decline_return_stage=decline_return_stage,
            actor_user_id=identity.user_id,
            actor_role=identity.role,
            demo_session_id=demo_session_id,
        )
    except InvalidApplicationTransition:
        raise HTTPException(status_code=409, detail="application cannot be submitted")

    collects_medicare_id = tenant_config.collects_medicare_id
    medicare_id_masked = mask_medicare_id(application, collects_medicare_id)
    return {
        "application": serialize_application(
            application, application_step, collects_medicare_id
        ),
        "opportunity_stage": opportunity.stage,
        "policy": (
            serialize_policy(policy, medicare_id_masked) if policy is not None else None
        ),
    }


@router.post("/{application_id}/reveal-medicare-id")
async def reveal_medicare_id(
    application_id: uuid.UUID,
    request: Request,
    identity: Identity = Depends(require_capability(Capability.REVEAL_PII)),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Decrypt and return one application's Medicare ID — audited (D9).

    The application twin of the leads reveal: the only place the plaintext Medicare ID
    crosses the API boundary, so it is the most guarded route here. The guard hands the
    route an `Identity` only when the caller holds `REVEAL_PII` (Read-Only and Platform
    Admin → 403, anonymous → 401). The flow: load by id / `404`; demo-session read
    isolation (a foreign session's row is a `404`; seed rows reveal normally); require
    the tenant **collects** a Medicare ID (`422` for Tenant-2); decrypt the stored blob
    (an application with none returns `value: null`); **await the reveal seam**
    (`on_pii_revealed` with `entity_type="application"`) before returning, so the audit
    + `pii.revealed` event land before the value leaves; return `{"field", "value"}`.
    `decrypt_field` binds `tenant_id` as AES-GCM associated data, so a cross-tenant blob
    could not decrypt even if it were reached.
    """
    application = (
        await db.execute(select(Application).where(Application.id == application_id))
    ).scalar_one_or_none()
    if application is None:
        raise HTTPException(status_code=404, detail="application not found")

    await _guard_application_for_session(application, request, db, refuse_seed=False)

    tenant_config = await _active_tenant_config(db)
    if not tenant_config.collects_medicare_id:
        raise HTTPException(
            status_code=422, detail="this tenant does not collect a Medicare ID"
        )

    value = (
        await decrypt_field(identity.tenant_id, application.medicare_id_encrypted)
        if application.medicare_id_encrypted is not None
        else None
    )

    await on_pii_revealed(db, identity, "application", application_id, "medicare_id")

    return {"field": "medicare_id", "value": value}
