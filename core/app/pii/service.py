"""The PII service seam: the single explicit write/read interface for personal data.

This is the one place the rest of the app calls to protect or read a personal-data
field. It does **no crypto of its own** — each function resolves the calling
tenant's subkeys via `get_tenant_keys` (Epic 4) and hands off to the pure
primitives in `crypto.py` (Epic 2):

    encrypt_field      -> aes_gcm_encrypt(encryption_key, plaintext, aad)
    decrypt_field      -> aes_gcm_decrypt(encryption_key, blob, aad)
    compute_blind_index -> hmac_blind_index(blind_index_key, normalized_value)

Without this seam every call site would have to know to resolve the tenant keys,
pick the right subkey, build the tenant-id associated data, and call the right
primitive — leaking crypto detail everywhere. The seam keeps that knowledge in
one module.

**Tenant-isolation note (the project's cross-cutting axis).** The tenant id is an
explicit argument (never hidden request state) and is bound as AES-GCM associated
data (AAD) on every encrypt and decrypt: `aad = tenant_id.bytes`. Because GCM
authenticates the AAD, a ciphertext written for one tenant fails to decrypt under
another — both the per-tenant encryption subkey and the tenant-id AAD must match.
The blind index uses the dedicated per-tenant blind-index subkey, so two tenants
can never fingerprint-match each other's values either. Tenants can therefore
neither read nor cross-reference each other's personal data.
"""

import uuid

from cryptography.exceptions import InvalidTag

from .crypto import aes_gcm_decrypt, aes_gcm_encrypt, hmac_blind_index
from .keys import get_tenant_keys


def _tenant_associated_data(tenant_id: uuid.UUID) -> bytes:
    """Return the AES-GCM associated data that binds a blob to its tenant.

    The 16 raw bytes of the tenant id are authenticated (but not encrypted) by
    AES-GCM on both encrypt and decrypt, so a blob written for one tenant cannot
    be read back under a different tenant id even with the right key.
    """
    return tenant_id.bytes


async def encrypt_field(tenant_id: uuid.UUID, plaintext: str) -> bytes:
    """Encrypt one personal-data field for a tenant and return the opaque blob.

    Resolves the tenant's encryption subkey, binds the tenant id as associated
    data, and delegates to `aes_gcm_encrypt`. The returned blob is what gets
    stored at rest; it never contains the plaintext in the clear.
    """
    tenant_keys = await get_tenant_keys(tenant_id)
    associated_data = _tenant_associated_data(tenant_id)
    return aes_gcm_encrypt(tenant_keys.encryption_key, plaintext, associated_data)


async def decrypt_field(tenant_id: uuid.UUID, blob: bytes) -> str:
    """Decrypt one stored field blob for a tenant back to its original string.

    Resolves the tenant's encryption subkey, binds the tenant id as associated
    data, and delegates to `aes_gcm_decrypt`. Raises `ValueError` if the blob was
    written for a different tenant (wrong key or wrong tenant-id AAD) or is
    otherwise tampered — there is no silent failure. The underlying AES-GCM
    authentication failure surfaces as `cryptography.exceptions.InvalidTag`, which
    is not a `ValueError`; the seam translates it so callers (and the tenant-
    isolation contract) see a single, uniform `ValueError` on any failed decrypt.
    """
    tenant_keys = await get_tenant_keys(tenant_id)
    associated_data = _tenant_associated_data(tenant_id)
    try:
        return aes_gcm_decrypt(tenant_keys.encryption_key, blob, associated_data)
    except InvalidTag as authentication_failure:
        raise ValueError(
            "could not decrypt field for this tenant: authentication failed "
            "(wrong tenant key or tenant-id associated data, or a tampered blob)"
        ) from authentication_failure


async def compute_blind_index(tenant_id: uuid.UUID, normalized_value: str) -> bytes:
    """Return the per-tenant blind-index fingerprint of an already-normalized value.

    Resolves the tenant's blind-index subkey and delegates to `hmac_blind_index`.
    This is a thin pass-through: the caller (the lookup router) normalizes the
    value first with `normalize_email` / `normalize_phone`, so the same logical
    value fingerprints identically and can be matched by equality without
    decryption.
    """
    tenant_keys = await get_tenant_keys(tenant_id)
    return hmac_blind_index(tenant_keys.blind_index_key, normalized_value)
