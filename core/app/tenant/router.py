"""The tenant HTTP surface: guarded reads of the caller's own tenant data.

This is the RBAC and isolation demonstrator — the routes that prove the earlier
epics' guarantees end-to-end over real HTTP. They add no new auth logic of their
own; they only compose the pieces the earlier epics built in isolation.

Endpoints under `/api/tenant`:

- `GET /config` returns the signed-in caller's tenant config, but only when the
  caller is a Tenant Admin. The guard raises 401 (no session) / 403 (a role that
  lacks `VIEW_TENANT_CONFIG`) for free, so the handler only ever runs for a Tenant
  Admin.
- `GET /settings` returns the caller's own `tenant_settings` row and nothing else.
  It takes **no tenant parameter** — isolation comes entirely from the Epic-5
  `get_tenant_db` scoping dependency, which points the session's `search_path` at
  the caller's own schema. That dependency chains through `require_authenticated`,
  so 401 (unauthenticated) and 400 (tenantless caller) are inherited for free.

The bodies use the `{"tenant": {...}}` / `{"settings": {...}}` envelope, mirroring
the auth router's `{"user": {...}}` style. Raw `UUID` values are returned as-is for
FastAPI's encoder to serialize, the style `router.py`/`health.py` use.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import require_capability
from ..auth.provider import Identity
from ..auth.rbac import Capability
from ..db import get_db
from ..models.tenant import Tenant
from ..models.tenant_settings import TenantSettings
from ..tenancy.scoping import get_tenant_db

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


@router.get("/settings")
async def get_tenant_settings(
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Return the caller's own tenant settings row, scoped by `get_tenant_db`.

    There is deliberately **no tenant parameter** — the caller can only ever read
    their own tenant. Isolation comes entirely from the `get_tenant_db` dependency,
    which sets the session's `search_path` to the caller's schema, so the schema-less
    `TenantSettings` query resolves to that one schema. The dependency chains through
    `require_authenticated`, so an unauthenticated caller gets 401 and a tenantless
    caller (a Platform Admin) gets `400 {"detail": "no tenant context"}`, both for
    free.

    The single per-tenant row is read with `scalar_one()` and returned under the
    `{"settings": {...}}` envelope. The raw `tenant_id` UUID is returned as-is for
    FastAPI's encoder, matching the `/config` style; `created_at` is omitted.
    """
    settings = (
        await db.execute(select(TenantSettings))
    ).scalar_one()

    return {
        "settings": {
            "tenant_id": settings.tenant_id,
            "brand_primary_color": settings.brand_primary_color,
            "brand_logo_url": settings.brand_logo_url,
            "welcome_message": settings.welcome_message,
        }
    }
