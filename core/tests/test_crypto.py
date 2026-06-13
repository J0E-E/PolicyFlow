"""Unit tests for the pure PII crypto primitives.

Pure unit tests — no DB, no Docker — matching the no-Docker style of
`test_config.py` / `test_passwords.py`. They cover all three phases of the
module: the authenticated encryption + key wrap/unwrap core, HKDF subkey
derivation + the HMAC blind index, and value normalization. Every failure path
(wrong key, wrong associated data, an unknown/tampered version byte) is asserted
to raise rather than silently return garbage.
"""

import os

import pytest

from app.pii.crypto import (
    BLIND_INDEX_INFO_LABEL,
    BLOB_VERSION,
    FIELD_ENCRYPTION_INFO_LABEL,
    SUBKEY_LENGTH_BYTES,
    aes_gcm_decrypt,
    aes_gcm_encrypt,
    hkdf_subkey,
    hmac_blind_index,
    normalize_email,
    normalize_phone,
    unwrap_key,
    wrap_key,
)

# A fixed 32-byte key (AES-256) reused across the encryption tests.
A_KEY = bytes(range(32))
ANOTHER_KEY = bytes(range(32, 64))
TENANT_A_ASSOCIATED_DATA = b"tenant-a"
TENANT_B_ASSOCIATED_DATA = b"tenant-b"


# --- Phase 1: AEAD field encrypt/decrypt + key wrap/unwrap ---


def test_encrypt_then_decrypt_round_trips_to_the_original_string():
    """A field encrypted with a key and associated data decrypts back exactly."""
    plaintext = "jane@example.com"

    blob = aes_gcm_encrypt(A_KEY, plaintext, TENANT_A_ASSOCIATED_DATA)
    decrypted = aes_gcm_decrypt(A_KEY, blob, TENANT_A_ASSOCIATED_DATA)

    assert decrypted == plaintext


def test_blob_begins_with_the_version_byte():
    """The blob layout leads with the known version byte."""
    blob = aes_gcm_encrypt(A_KEY, "value", TENANT_A_ASSOCIATED_DATA)

    assert blob[0] == BLOB_VERSION


def test_decrypt_with_a_wrong_key_raises():
    """Decrypting with the wrong key fails AES-GCM authentication."""
    blob = aes_gcm_encrypt(A_KEY, "value", TENANT_A_ASSOCIATED_DATA)

    with pytest.raises(Exception):
        aes_gcm_decrypt(ANOTHER_KEY, blob, TENANT_A_ASSOCIATED_DATA)


def test_decrypt_with_wrong_associated_data_raises():
    """A ciphertext made for Tenant A fails to decrypt under Tenant B's data."""
    blob = aes_gcm_encrypt(A_KEY, "value", TENANT_A_ASSOCIATED_DATA)

    with pytest.raises(Exception):
        aes_gcm_decrypt(A_KEY, blob, TENANT_B_ASSOCIATED_DATA)


def test_decrypt_with_unknown_version_byte_raises_value_error():
    """A blob whose leading version byte is unknown is rejected with ValueError."""
    blob = aes_gcm_encrypt(A_KEY, "value", TENANT_A_ASSOCIATED_DATA)
    tampered_version = bytes([BLOB_VERSION + 1]) + blob[1:]

    with pytest.raises(ValueError):
        aes_gcm_decrypt(A_KEY, tampered_version, TENANT_A_ASSOCIATED_DATA)


def test_decrypt_with_tampered_ciphertext_raises():
    """Flipping a ciphertext byte fails authentication and raises."""
    blob = bytearray(aes_gcm_encrypt(A_KEY, "value", TENANT_A_ASSOCIATED_DATA))
    blob[-1] ^= 0x01

    with pytest.raises(Exception):
        aes_gcm_decrypt(A_KEY, bytes(blob), TENANT_A_ASSOCIATED_DATA)


def test_wrap_then_unwrap_round_trips_to_the_original_root_key():
    """A root key wrapped under a master key unwraps back to the same bytes."""
    master_key = os.urandom(32)
    root_key = os.urandom(32)

    wrapped = wrap_key(master_key, root_key)
    unwrapped = unwrap_key(master_key, wrapped)

    assert unwrapped == root_key


def test_unwrap_with_a_wrong_master_key_raises():
    """Unwrapping with the wrong master key fails authentication."""
    master_key = os.urandom(32)
    wrong_master_key = os.urandom(32)
    wrapped = wrap_key(master_key, os.urandom(32))

    with pytest.raises(Exception):
        unwrap_key(wrong_master_key, wrapped)


# --- Phase 2: HKDF subkeys + HMAC blind index ---


def test_the_two_info_labels_derive_different_subkeys_each_differing_from_root():
    """The encryption and blind-index labels derive independent 32-byte subkeys."""
    root_key = os.urandom(32)

    encryption_subkey = hkdf_subkey(root_key, FIELD_ENCRYPTION_INFO_LABEL)
    blind_index_subkey = hkdf_subkey(root_key, BLIND_INDEX_INFO_LABEL)

    assert len(encryption_subkey) == SUBKEY_LENGTH_BYTES
    assert len(blind_index_subkey) == SUBKEY_LENGTH_BYTES
    assert encryption_subkey != blind_index_subkey
    assert encryption_subkey != root_key
    assert blind_index_subkey != root_key


def test_hkdf_is_deterministic_for_the_same_root_and_label():
    """The same root key and same label always derive the same subkey."""
    root_key = os.urandom(32)

    first = hkdf_subkey(root_key, FIELD_ENCRYPTION_INFO_LABEL)
    second = hkdf_subkey(root_key, FIELD_ENCRYPTION_INFO_LABEL)

    assert first == second


def test_blind_index_is_deterministic_and_32_bytes():
    """The same key and value always fingerprint to the same 32 bytes."""
    index_key = os.urandom(32)

    first = hmac_blind_index(index_key, "jane@example.com")
    second = hmac_blind_index(index_key, "jane@example.com")

    assert first == second
    assert len(first) == 32


def test_blind_index_differs_under_a_different_key():
    """A different key fingerprints the same value differently."""
    value = "jane@example.com"

    first = hmac_blind_index(os.urandom(32), value)
    second = hmac_blind_index(os.urandom(32), value)

    assert first != second


# --- Phase 3: normalization ---


def test_normalize_email_trims_and_lowercases():
    """Surrounding whitespace is stripped and the address is lowercased."""
    assert normalize_email("  Jane@Example.COM  ") == "jane@example.com"


def test_normalize_email_keeps_plus_addressing():
    """Plus-addressing is preserved so tagged addresses stay distinct."""
    assert normalize_email("Jane+News@Example.com") == "jane+news@example.com"
    assert normalize_email("jane+tag@x.com") != normalize_email("jane@x.com")


def test_normalize_phone_keeps_only_digits():
    """Spaces, punctuation, and a leading plus are all dropped."""
    assert normalize_phone("+1 (555) 123-4567") == "15551234567"
    assert normalize_phone("555.123.4567") == "5551234567"
