"""The shared identity response body — built once, returned by every auth path.

Login, `GET /me`, and the demo assume-persona endpoint all hand the client the
**identical** identity shape: the signed-in user's public fields plus a flat,
sorted array of the capability strings the role holds (per the RBAC matrix). This
module holds the single definition of that body so the three callers can never
drift. Raw `UUID`/`StrEnum` values are returned as-is for FastAPI's encoder to
serialize, the style `health.py` uses.

The body deliberately carries **no PII** — only the user id, username, role,
tenant id, and the tenant's display slug + name, never the email, password hash,
or any person-level field. The tenant `slug` and `name` are read from the
`Tenant` row by `tenant_id` so a signed-in surface can show "signed in as
<role> · <tenant name>" without a second round trip; both are `null` for the
tenantless Platform Admin.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from ..models.tenant import Tenant
from .provider import Identity
from .rbac import CAPABILITIES


async def build_identity_response(db: AsyncSession, identity: Identity) -> dict:
    """Build the shared response body returned by login, `me`, and assume-persona.

    Returns the signed-in user's public fields plus a flat, sorted array of the
    capability strings the role holds (per the RBAC matrix). When the identity is
    tenant-scoped, the tenant's `slug` and `name` are read from the `Tenant` row by
    `tenant_id` (a cheap primary-key fetch); both are `null` for the tenantless
    Platform Admin. Raw `UUID`/`StrEnum` values are left as-is for FastAPI's
    encoder to serialize.
    """
    capabilities = sorted(
        capability.value for capability in CAPABILITIES[identity.role]
    )
    tenant_slug = None
    tenant_name = None
    if identity.tenant_id is not None:
        tenant = await db.get(Tenant, identity.tenant_id)
        if tenant is not None:
            tenant_slug = tenant.slug
            tenant_name = tenant.name
    return {
        "user": {
            "id": identity.user_id,
            "username": identity.username,
            "role": identity.role,
            "tenant_id": identity.tenant_id,
            "tenant_slug": tenant_slug,
            "tenant_name": tenant_name,
        },
        "capabilities": capabilities,
    }
