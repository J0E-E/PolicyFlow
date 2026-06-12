"""The tenant HTTP surface: a guarded read of the caller's tenant config.

This is the RBAC demonstrator — the first route that proves the capability matrix
end-to-end over real HTTP. It adds no new auth logic of its own; it only composes
the pieces the earlier epics built in isolation: `require_capability` over the RBAC
matrix (Epics 6–7) guarding a read of the `Tenant` model (Epic 2), exactly as the
auth router composed its own ingredients.

One endpoint under `/api/tenant`:

- `GET /config` returns the signed-in caller's tenant config, but only when the
  caller is a Tenant Admin. The guard raises 401 (no session) / 403 (a role that
  lacks `VIEW_TENANT_CONFIG`) for free, so the handler only ever runs for a Tenant
  Admin.

The body is the `{"tenant": {...}}` envelope, mirroring the auth router's
`{"user": {...}}` style. Raw `UUID` values are returned as-is for FastAPI's encoder
to serialize, the style `router.py`/`health.py` use.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import require_capability
from ..auth.provider import Identity
from ..auth.rbac import Capability
from ..db import get_db
from ..models.tenant import Tenant

router = APIRouter(prefix="/api/tenant")


@router.get("/config")
async def get_tenant_config(
    identity: Identity = Depends(
        require_capability(Capability.VIEW_TENANT_CONFIG)
    ),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the signed-in Tenant Admin's tenant config.

    The guard hands the route an `Identity` only when the caller is a Tenant Admin
    (every other role gets a 403, the anonymous caller a 401, both for free). It
    then reads that caller's own tenant row by `identity.tenant_id` and returns its
    public fields under the `{"tenant": {...}}` envelope.

    A `None` row is effectively impossible — only a Tenant Admin reaches here, and
    the `tenant_id` FK plus the tenantless-platform-admin CHECK guarantee that
    caller's tenant exists — but it is still handled defensively with a 404 rather
    than falling through to a 500.
    """
    tenant = (
        await db.execute(
            select(Tenant).where(Tenant.id == identity.tenant_id)
        )
    ).scalar_one_or_none()

    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")

    return {
        "tenant": {
            "id": tenant.id,
            "name": tenant.name,
            "slug": tenant.slug,
        }
    }
