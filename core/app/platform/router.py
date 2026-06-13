"""The platform HTTP surface: the sanctioned cross-tenant operational read.

This is the Platform-Admin carve-out's only route — the controlled exception to
tenant isolation. It adds no new auth logic of its own; it composes the pieces
the earlier epics built:

- `GET /tenant-settings` lists **every** tenant's settings as operational metadata
  (brand colour, logo URL, welcome message; **no PII** — never a user or lead
  field). Reachability is the whole point of the carve-out: the `get_platform_db`
  dependency chains through `require_platform_admin`, so only a signed-in Platform
  Admin reaches the handler (401 for the anonymous caller, 403 for any other role,
  both for free), and the session it yields runs as the read-only `platform_reader`
  role with cross-tenant `SELECT`.

The cross-schema list is assembled by **looping the registry** and running one
schema-qualified read per tenant — the clearest approach, matching the seed's
existing per-tenant loop. Every schema identifier interpolated into the SQL comes
verbatim from the registry whitelist (`tenant.schema_name`), never from the
request. Each item carries the four settings fields plus the registry `slug` as a
human-readable operational label, under the `{"tenants": [...]}` envelope.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..tenancy.registry import TENANTS
from ..tenancy.scoping import get_platform_db

router = APIRouter(prefix="/api/platform")


@router.get("/tenant-settings")
async def list_tenant_settings(
    db: AsyncSession = Depends(get_platform_db),
) -> dict:
    """List every tenant's settings (operational metadata, no PII).

    Runs only for a signed-in Platform Admin — `get_platform_db` inherits the
    401/403 gate via `require_platform_admin` and yields a session scoped to the
    read-only `platform_reader` role. The handler loops the registry whitelist and,
    for each tenant, reads that tenant's single `tenant_settings` row from its own
    schema with a schema-qualified `SELECT`. The schema name is interpolated from
    `tenant.schema_name` — a registry value, never user input — so the
    interpolation is safe.

    Each tenant's row is returned with its four settings fields plus the registry
    `slug` as a readable label, all under the `{"tenants": [...]}` envelope. The raw
    `tenant_id` UUID is returned as-is for FastAPI's encoder, matching the tenant
    router's style.
    """
    tenants = []
    for tenant in TENANTS:
        settings_row = (
            await db.execute(
                text(
                    "SELECT tenant_id, brand_primary_color, brand_logo_url, "
                    f"welcome_message FROM {tenant.schema_name}.tenant_settings"
                )
            )
        ).one()
        tenants.append(
            {
                "tenant_id": settings_row.tenant_id,
                "brand_primary_color": settings_row.brand_primary_color,
                "brand_logo_url": settings_row.brand_logo_url,
                "welcome_message": settings_row.welcome_message,
                "slug": tenant.slug,
            }
        )

    return {"tenants": tenants}
