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
    Settings,
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


def test_event_exchange_default_is_the_tdd_literal():
    """The live setting defaults to the TDD §5.4 events-exchange name."""
    assert settings.event_exchange == "policyflow.events"


def test_outbox_poll_interval_default_is_one_second():
    """The live setting defaults to the ~1s poll interval as a float."""
    assert settings.outbox_poll_interval_seconds == 1.0


def test_public_intake_rate_limit_default_is_five():
    """The live setting defaults to 5 requests per window as an int."""
    assert settings.public_intake_rate_limit == 5


def test_public_intake_rate_limit_window_default_is_sixty_seconds():
    """The live setting defaults to a 60-second window as a float."""
    assert settings.public_intake_rate_limit_window_seconds == 60.0


def test_event_exchange_honors_environment_override(monkeypatch):
    """A fresh `Settings()` reads a custom exchange name from the environment."""
    monkeypatch.setenv("EVENT_EXCHANGE", "custom.events")

    fresh_settings = Settings()

    assert fresh_settings.event_exchange == "custom.events"


def test_outbox_poll_interval_honors_environment_override(monkeypatch):
    """A fresh `Settings()` reads a non-default poll interval as a float."""
    monkeypatch.setenv("OUTBOX_POLL_INTERVAL_SECONDS", "2.5")

    fresh_settings = Settings()

    assert fresh_settings.outbox_poll_interval_seconds == 2.5


def test_public_intake_rate_limit_honors_environment_override(monkeypatch):
    """A fresh `Settings()` reads a non-default request limit as an int."""
    monkeypatch.setenv("PUBLIC_INTAKE_RATE_LIMIT", "20")

    fresh_settings = Settings()

    assert fresh_settings.public_intake_rate_limit == 20


def test_public_intake_rate_limit_window_honors_environment_override(monkeypatch):
    """A fresh `Settings()` reads a non-default window length as a float."""
    monkeypatch.setenv("PUBLIC_INTAKE_RATE_LIMIT_WINDOW_SECONDS", "30.0")

    fresh_settings = Settings()

    assert fresh_settings.public_intake_rate_limit_window_seconds == 30.0


def test_demo_login_enabled_defaults_on(monkeypatch):
    """With no env var set, the demo login is enabled — this build is the demo."""
    monkeypatch.delenv("DEMO_LOGIN_ENABLED", raising=False)

    fresh_settings = Settings()

    assert fresh_settings.demo_login_enabled is True


def test_demo_login_enabled_honors_environment_override_off(monkeypatch):
    """`DEMO_LOGIN_ENABLED=false` turns the flag off (the non-demo off-switch)."""
    monkeypatch.setenv("DEMO_LOGIN_ENABLED", "false")

    fresh_settings = Settings()

    assert fresh_settings.demo_login_enabled is False


def test_demo_login_enabled_truthy_values_turn_it_on(monkeypatch):
    """`true` / `1` / `yes` all read as on; anything else reads as off."""
    for truthy_value in ("true", "1", "yes", "TRUE", "Yes"):
        monkeypatch.setenv("DEMO_LOGIN_ENABLED", truthy_value)
        assert Settings().demo_login_enabled is True

    for falsy_value in ("false", "0", "no", "off", ""):
        monkeypatch.setenv("DEMO_LOGIN_ENABLED", falsy_value)
        assert Settings().demo_login_enabled is False
