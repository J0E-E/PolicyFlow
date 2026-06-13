"""Per-tenant key resolution + a process-lifetime in-memory cache.

This module is the seam that turns a stored, master-key-wrapped root key into the
two usable subkeys a running request needs: the AES-256-GCM field-encryption key
and the HMAC blind-index key. The flow on a cache miss is:

    read the wrapped blob (login-role session)
        -> unwrap it with the master key
        -> HKDF-derive the encryption and blind-index subkeys
        -> cache the pair, keyed by tenant id

so a given tenant's root key is unwrapped at most once per process. The pure
crypto (`unwrap_key`, `hkdf_subkey`) and the wrapped-key store (`TenantDataKey`)
already exist; this module only composes them and adds the cache.

**Tenant-isolation note (the project's cross-cutting axis).** The wrapped blob
lives in the shared ``platform`` schema, readable **only** by the default login
role (migration ``0005``). A tenant-scoped request session (``SET ROLE
tenant_x``) is blind to ``platform`` by design, so `_read_wrapped_root_key`
opens its **own** short-lived login-role session via `app.db.session_factory`
(the `app.seed` pattern), independent of any request's tenant session. The
request's tenant scoping is never weakened, and the tenant role can never read
key material — only the already-in-memory master key unlocks a blob.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select

from ..config import settings
from ..db import session_factory
from ..models import TenantDataKey
from .crypto import (
    BLIND_INDEX_INFO_LABEL,
    FIELD_ENCRYPTION_INFO_LABEL,
    hkdf_subkey,
    unwrap_key,
)


@dataclass(frozen=True)
class TenantKeys:
    """The two derived subkeys for one tenant, ready for the PII service to use.

    Frozen because the keys never change once derived: the wrapped blob is static
    and HKDF is deterministic, so a tenant's subkeys are fixed for the life of the
    process. `encryption_key` drives AES-256-GCM field encryption; `blind_index_key`
    drives the HMAC blind index.
    """

    encryption_key: bytes
    blind_index_key: bytes


class TenantDataKeyNotFound(LookupError):
    """Raised when no wrapped root key row exists for a tenant id.

    A missing row is a misconfiguration (the Epic 6 seed should have written one),
    not a routine miss, so the seam fails loud and names the tenant id rather than
    returning silently.
    """

    def __init__(self, tenant_id: uuid.UUID) -> None:
        self.tenant_id = tenant_id
        super().__init__(
            f"no wrapped root key found for tenant {tenant_id} in "
            "platform.tenant_data_keys"
        )


# Process-lifetime in-memory cache, keyed by tenant id. Bounded in practice by the
# fixed tenant registry, so no LRU/TTL is needed (deferred per the TDD). No lock is
# needed: derivation is deterministic and the wrapped blob is static, so a
# cold-start race at worst unwraps the same blob twice and can never return a wrong
# key for a tenant.
_tenant_keys_cache: dict[uuid.UUID, TenantKeys] = {}


async def get_tenant_keys(tenant_id: uuid.UUID) -> TenantKeys:
    """Return the derived subkeys for a tenant, unwrapping at most once per process.

    A cache hit returns immediately and touches no database. On a miss, the wrapped
    root key is loaded, unwrapped, and split into the two subkeys, then the result
    is cached before being returned. Raises `TenantDataKeyNotFound` if the tenant
    has no wrapped key row.
    """
    cached_keys = _tenant_keys_cache.get(tenant_id)
    if cached_keys is not None:
        return cached_keys

    tenant_keys = await _load_and_derive_tenant_keys(tenant_id)
    _tenant_keys_cache[tenant_id] = tenant_keys
    return tenant_keys


async def _load_and_derive_tenant_keys(tenant_id: uuid.UUID) -> TenantKeys:
    """Load the wrapped root key, unwrap it, and derive both subkeys.

    Reads the wrapped blob via `_read_wrapped_root_key`, unwraps it with the master
    key, then HKDF-derives the field-encryption and blind-index subkeys with the two
    existing info labels. The unwrapped root key stays local to this function and is
    never cached or returned.
    """
    wrapped_root_key = await _read_wrapped_root_key(tenant_id)
    root_key = unwrap_key(settings.pii_master_key, wrapped_root_key)
    return TenantKeys(
        encryption_key=hkdf_subkey(root_key, FIELD_ENCRYPTION_INFO_LABEL),
        blind_index_key=hkdf_subkey(root_key, BLIND_INDEX_INFO_LABEL),
    )


async def _read_wrapped_root_key(tenant_id: uuid.UUID) -> bytes:
    """Return the wrapped root key bytes for a tenant from the key store.

    Opens its own short-lived session from the module-level `session_factory`,
    running as the default login role (no `SET ROLE`) so it can read the
    ``platform``-schema key store a tenant role cannot see. Raises
    `TenantDataKeyNotFound` if no row exists for the tenant id.
    """
    async with session_factory() as session:
        wrapped_root_key = (
            await session.execute(
                select(TenantDataKey.wrapped_root_key).where(
                    TenantDataKey.tenant_id == tenant_id
                )
            )
        ).scalar_one_or_none()

    if wrapped_root_key is None:
        raise TenantDataKeyNotFound(tenant_id)
    return wrapped_root_key
