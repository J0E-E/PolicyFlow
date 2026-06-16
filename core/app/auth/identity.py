"""The shared identity response body — built once, returned by every auth path.

Login, `GET /me`, and the demo assume-persona endpoint all hand the client the
**identical** identity shape: the signed-in user's public fields plus a flat,
sorted array of the capability strings the role holds (per the RBAC matrix). This
module holds the single definition of that body so the three callers can never
drift. Raw `UUID`/`StrEnum` values are returned as-is for FastAPI's encoder to
serialize, the style `health.py` uses.

The body deliberately carries **no PII** — only the user id, username, role, and
tenant id, never the email, password hash, or any person-level field.
"""

from .provider import Identity
from .rbac import CAPABILITIES


def build_identity_response(identity: Identity) -> dict:
    """Build the shared response body returned by login, `me`, and assume-persona.

    Returns the signed-in user's public fields plus a flat, sorted array of the
    capability strings the role holds (per the RBAC matrix). Raw `UUID`/`StrEnum`
    values are left as-is for FastAPI's encoder to serialize.
    """
    capabilities = sorted(
        capability.value for capability in CAPABILITIES[identity.role]
    )
    return {
        "user": {
            "id": identity.user_id,
            "username": identity.username,
            "role": identity.role,
            "tenant_id": identity.tenant_id,
        },
        "capabilities": capabilities,
    }
