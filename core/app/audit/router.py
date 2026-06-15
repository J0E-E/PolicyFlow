"""The audit-read HTTP surface: one guarded, self-auditing list endpoint.

`GET /api/audit` is the read side of the P1.4 audit spine — the path that makes
"viewing audit logs is itself an audited sensitive operation" real and testable.
It returns the caller's own tenant audit records (names and metadata only, never
PII values) newest-first, and **records its own `audit.viewed` audit record before
it returns**. It is the only route here; the viewer/export UI and pagination are
deferred to M4.

**The guard chain (order is load-bearing).** The route depends on
`require_capability(VIEW_AUDIT_LOGS)` **first**, then `get_tenant_db`. Capability
comes before the tenant-scoped session on purpose: a tenantless Platform Admin
lacks `VIEW_AUDIT_LOGS`, so the capability gate rejects it with a **403** before
`get_tenant_db`'s tenantless **400** can fire. (`VIEW_AUDIT_LOGS` is held only by
Tenant Admin and Read-Only — see `auth.rbac`.) An anonymous caller inherits the
**401** from the same chain. This mirrors the `pii_demo` create's capability-first
ordering.

**Isolation comes from `search_path`, not a parameter.** There is deliberately
**no tenant parameter**: `get_tenant_db` points the session's `search_path` at the
caller's own schema, so the schema-less `AuditRecord` query resolves to that one
tenant's `audit_records` table. Another tenant's rows are physically out of reach,
exactly as Epic 5 proved — this endpoint simply inherits that guarantee.

**Names only, by construction.** The audit records themselves store field *names*
and metadata, never PII values (Epic 4's service writes them that way). The
response builder copies those columns through unchanged, so no decryption or
unmasking happens here and no PII can leak — there is nothing sensitive to leak.

**Read first, then self-audit, then return.** The handler reads the existing rows
**before** writing its own `audit.viewed` record, and `await`s that write **before**
the `return`. So a given view never includes its own `audit.viewed` row, but a
**later** view does see it — and "written before the response, not after" holds.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit.records import EventType, Outcome
from ..auth.dependencies import require_capability
from ..auth.provider import Identity
from ..auth.rbac import Capability
from ..models.audit_record import AuditRecord
from ..tenancy.scoping import get_tenant_db
from .service import record_audit_event

router = APIRouter(prefix="/api/audit")


def _audit_record_response(record: AuditRecord) -> dict:
    """Build the response body for one audit record — the single read shape.

    The one place the read shape lives (mirroring `pii_demo`'s `_masked_record`
    and auth's identity builder), so the audit-read contract is defined in exactly
    one place. Returns only references, names, and metadata — `field_names` carries
    field *names*, never their values — so the response can never expose PII; there
    is no encrypted column to decrypt here. The raw `UUID` / `datetime` values are
    returned as-is for FastAPI's encoder to serialize, the house style every other
    router uses.
    """
    return {
        "id": record.id,
        "occurred_at": record.occurred_at,
        "tenant_id": record.tenant_id,
        "actor_user_id": record.actor_user_id,
        "actor_role": record.actor_role,
        "event_type": record.event_type,
        "entity_type": record.entity_type,
        "entity_id": record.entity_id,
        "field_names": record.field_names,
        "outcome": record.outcome,
    }


@router.get("")
async def list_audit_records(
    identity: Identity = Depends(
        require_capability(Capability.VIEW_AUDIT_LOGS)
    ),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Return the caller's tenant audit records, newest-first; audit the view itself.

    The guard hands the route an `Identity` only when the caller holds
    `VIEW_AUDIT_LOGS` (Tenant Admin or Read-Only); every other role gets a 403, the
    anonymous caller a 401, and a tenantless Platform Admin a 403 (the capability
    gate fires before `get_tenant_db`'s tenantless 400). `get_tenant_db` scopes the
    read to the caller's own schema, so there is **no tenant parameter** and another
    tenant's rows are physically unreachable.

    The handler reads the caller's own `audit_records`, ordered `occurred_at DESC`
    (newest-first; all rows, no pagination — deferred to M4), through the
    schema-less `AuditRecord` model. It then writes one `audit.viewed` record via
    `record_audit_event`, routed to this tenant's store, and **awaits** that write
    **before** returning — so the response never includes its own `audit.viewed`
    row, but a later view does (the proof that viewing is itself audited). Each row
    is returned through `_audit_record_response` under the `{"records": [...]}`
    envelope.
    """
    records = (
        await db.execute(
            select(AuditRecord).order_by(AuditRecord.occurred_at.desc())
        )
    ).scalars().all()

    await record_audit_event(
        tenant_id=identity.tenant_id,
        actor_user_id=identity.user_id,
        actor_role=identity.role,
        event_type=EventType.AUDIT_VIEWED,
        outcome=Outcome.SUCCESS,
        entity_type="audit_records",
    )

    return {"records": [_audit_record_response(record) for record in records]}
