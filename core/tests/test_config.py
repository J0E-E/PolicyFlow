"""Unit tests for the PII master-key decode/validation helper and setting.

Pure unit tests — no DB, no Docker — matching the no-Docker style of
`test_passwords.py`. They prove a valid base64-of-32-bytes decodes to those
exact bytes, that an undecodable string raises, that a value decoding to the
wrong length (too short / too long) raises, that the shipped dev default
decodes cleanly to 32 bytes (the loud guard against a typo'd default), and that
the live `settings.pii_master_key` is 32 `bytes`.
"""

import base64

import pytest

from app.config import (
    DEV_THROWAWAY_MASTER_KEY_BASE64,
    decode_master_key,
    settings,
)


def test_valid_base64_of_32_bytes_decodes_to_those_bytes():
    """A base64 value of 32 bytes decodes back to the same 32 raw bytes."""
    original_key = bytes(range(32))
    encoded_key = base64.b64encode(original_key).decode("ascii")

    decoded_key = decode_master_key(encoded_key)

    assert decoded_key == original_key
    assert len(decoded_key) == 32


def test_undecodable_base64_raises_value_error():
    """A string that is not valid base64 raises `ValueError`."""
    with pytest.raises(ValueError):
        decode_master_key("not valid base64 !!!")


def test_too_short_key_raises_value_error():
    """A base64 value that decodes to fewer than 32 bytes raises `ValueError`."""
    too_short = base64.b64encode(b"only-16-bytes!!!").decode("ascii")

    with pytest.raises(ValueError):
        decode_master_key(too_short)


def test_too_long_key_raises_value_error():
    """A base64 value that decodes to more than 32 bytes raises `ValueError`."""
    too_long = base64.b64encode(bytes(33)).decode("ascii")

    with pytest.raises(ValueError):
        decode_master_key(too_long)


def test_dev_default_decodes_cleanly_to_32_bytes():
    """The shipped dev default decodes without error to exactly 32 bytes.

    This is the loud guard against a typo'd default: a malformed default fails
    here instead of only failing at boot in a fresh environment.
    """
    decoded_default = decode_master_key(DEV_THROWAWAY_MASTER_KEY_BASE64)

    assert len(decoded_default) == 32


def test_settings_pii_master_key_is_32_bytes():
    """The live setting is the decoded 32 raw bytes, ready for crypto use."""
    assert isinstance(settings.pii_master_key, bytes)
    assert len(settings.pii_master_key) == 32
