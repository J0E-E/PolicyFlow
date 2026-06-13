"""Pure crypto primitives for protecting personal data (PII).

Every function here takes its inputs and returns its outputs with no database,
no tenant logic, and no global state, so each one is trivially testable and safe
to build the rest of the phase on. The toolkit is small on purpose:

- **Authenticated field encryption** (`aes_gcm_encrypt` / `aes_gcm_decrypt`) —
  AES-256-GCM with a fresh random nonce per call. GCM authenticates both the
  ciphertext and the caller-supplied associated data, so any tampering — a wrong
  key, the wrong associated data, or a flipped byte — fails loudly with a
  `ValueError` instead of returning garbage plaintext.
- **Envelope key wrap/unwrap** (`wrap_key` / `unwrap_key`) — the same AEAD core,
  used to wrap one set of raw key bytes under a master key. This is the shape a
  managed KMS produces (a wrapped data-key blob), so the swap to KMS later is
  one-for-one.
- **Subkey derivation** (`hkdf_subkey`) — HKDF-SHA256 turning one stored root key
  into independent 32-byte subkeys. Distinct `info` labels keep the encryption
  subkey and the blind-index (MAC) subkey from ever sharing key material.
- **Blind index** (`hmac_blind_index`) — a deterministic HMAC-SHA256 fingerprint
  of a normalized value, so duplicates can be found by equality without ever
  decrypting.
- **Normalization** (`normalize_email` / `normalize_phone`) — fold a value to a
  canonical form before fingerprinting so trivially-different inputs (case,
  surrounding whitespace, phone punctuation) match.

**Blob layout.** Every encrypted blob carries a leading version byte:

    version(1) ‖ nonce(12) ‖ ciphertext ‖ tag(16)

The one byte of overhead buys clean future migration if the cipher or layout
ever changes; `aes_gcm_decrypt` rejects any blob whose version byte it does not
recognise. The same versioned layout is shared by field encryption and key
wrap/unwrap through one private bytes-level core, so the two can never drift
apart.
"""

import hmac
import os
from hashlib import sha256

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# The single current blob version. A future cipher/layout change ships a new
# version byte; `aes_gcm_decrypt` refuses any version it does not know.
BLOB_VERSION = 0x01

# AES-GCM's standard nonce length. A fresh random nonce is generated per call.
_NONCE_LENGTH_BYTES = 12

# HKDF-derived subkeys (and thus encryption/MAC keys) are 32 bytes (AES-256).
SUBKEY_LENGTH_BYTES = 32

# HKDF `info` labels keep the two subkeys independent: the field-encryption
# subkey and the blind-index (MAC) subkey are derived from the same root key but
# never share material, because their labels differ.
FIELD_ENCRYPTION_INFO_LABEL = b"policyflow/field-encryption/v1"
BLIND_INDEX_INFO_LABEL = b"policyflow/blind-index/v1"


def _aes_gcm_encrypt_bytes(key: bytes, plaintext: bytes, associated_data: bytes) -> bytes:
    """Encrypt raw bytes with AES-256-GCM and return the versioned blob.

    Generates a fresh random 12-byte nonce, encrypts, and assembles
    `version(1) ‖ nonce(12) ‖ ciphertext ‖ tag(16)` (the cipher appends the
    16-byte authentication tag to the ciphertext). This private core is shared by
    both the string-facing field encryption and the raw-bytes key wrap, so the
    blob layout is defined in exactly one place.
    """
    aes_gcm = AESGCM(key)
    nonce = _random_nonce()
    ciphertext_with_tag = aes_gcm.encrypt(nonce, plaintext, associated_data)
    return bytes([BLOB_VERSION]) + nonce + ciphertext_with_tag


def _aes_gcm_decrypt_bytes(key: bytes, blob: bytes, associated_data: bytes) -> bytes:
    """Decrypt a versioned blob produced by `_aes_gcm_encrypt_bytes`.

    Checks the leading version byte, splits off the nonce, and decrypts the rest.
    Raises `ValueError` on an unknown version byte, and AES-GCM raises on any
    authentication failure (wrong key, wrong associated data, or a tampered
    blob), so a bad blob never returns garbage plaintext.
    """
    if len(blob) == 0 or blob[0] != BLOB_VERSION:
        raise ValueError("unknown or missing crypto blob version byte")
    nonce = blob[1 : 1 + _NONCE_LENGTH_BYTES]
    ciphertext_with_tag = blob[1 + _NONCE_LENGTH_BYTES :]
    aes_gcm = AESGCM(key)
    return aes_gcm.decrypt(nonce, ciphertext_with_tag, associated_data)


def _random_nonce() -> bytes:
    """Return a fresh cryptographically random 12-byte AES-GCM nonce."""
    return os.urandom(_NONCE_LENGTH_BYTES)


def aes_gcm_encrypt(key: bytes, plaintext: str, associated_data: bytes) -> bytes:
    """Encrypt a string field with AES-256-GCM and return the versioned blob.

    The plaintext is UTF-8 encoded before encryption. `associated_data` is
    authenticated but not encrypted — callers bind the tenant id here so a
    ciphertext made for one tenant fails to decrypt under another. Returns
    `version(1) ‖ nonce(12) ‖ ciphertext ‖ tag(16)` with a fresh random nonce.
    """
    return _aes_gcm_encrypt_bytes(key, plaintext.encode("utf-8"), associated_data)


def aes_gcm_decrypt(key: bytes, blob: bytes, associated_data: bytes) -> str:
    """Decrypt a field blob back to its original string.

    Raises `ValueError` if the blob's version byte is unknown, and AES-GCM raises
    if authentication fails (wrong key, wrong associated data, or a tampered
    blob) — there is no silent failure. The decrypted bytes are UTF-8 decoded.
    """
    return _aes_gcm_decrypt_bytes(key, blob, associated_data).decode("utf-8")


def wrap_key(master_key: bytes, root_key: bytes) -> bytes:
    """Wrap (encrypt) a raw root key under the master key.

    Uses the same AES-256-GCM core as field encryption with empty associated
    data, operating on raw key bytes directly so there is no lossy string
    round-trip. Returns the versioned blob; the wrapped blob is inert without the
    master key. This is the envelope shape a managed KMS produces.
    """
    return _aes_gcm_encrypt_bytes(master_key, root_key, b"")


def unwrap_key(master_key: bytes, wrapped: bytes) -> bytes:
    """Unwrap (decrypt) a wrapped root key with the master key.

    Raises if the master key is wrong, the blob is tampered, or the version byte
    is unknown — the same loud-failure guarantees as `aes_gcm_decrypt`. Returns
    the original raw root-key bytes.
    """
    return _aes_gcm_decrypt_bytes(master_key, wrapped, b"")


def hkdf_subkey(root_key: bytes, info: bytes) -> bytes:
    """Derive a 32-byte subkey from a root key with HKDF-SHA256.

    The `info` label binds the subkey to a purpose: different labels derive
    independent subkeys from the same root key, which is how the encryption
    subkey and the blind-index (MAC) subkey are kept from ever sharing material.
    Same root key and same label always derive the same subkey.
    """
    key_derivation = HKDF(
        algorithm=hashes.SHA256(),
        length=SUBKEY_LENGTH_BYTES,
        salt=None,
        info=info,
    )
    return key_derivation.derive(root_key)


def hmac_blind_index(index_key: bytes, normalized_value: str) -> bytes:
    """Return a deterministic HMAC-SHA256 fingerprint of a normalized value.

    The same key and same normalized value always produce the same 32 bytes,
    which is exactly what enables exact-match duplicate detection by equality
    without decryption. A different key produces a different fingerprint, so the
    index reveals nothing without the key. Normalize the value first
    (`normalize_email` / `normalize_phone`) so trivially-different inputs match.
    """
    return hmac.new(index_key, normalized_value.encode("utf-8"), sha256).digest()


def normalize_email(value: str) -> str:
    """Fold an email to its canonical form for fingerprinting: trim + lowercase.

    Surrounding whitespace is stripped and the address is lowercased.
    Plus-addressing is preserved on purpose — `jane+tag@example.com` and
    `jane@example.com` stay distinct, because they are different mailboxes for
    some providers and stripping the tag would over-merge.
    """
    return value.strip().lower()


def normalize_phone(value: str) -> str:
    """Fold a phone number to its canonical form: keep ASCII digits only.

    Spaces, dashes, parentheses, dots, and a leading `+` are all dropped, so the
    same number written in different styles fingerprints the same.
    """
    return "".join(
        character
        for character in value
        if character.isascii() and character.isdigit()
    )
