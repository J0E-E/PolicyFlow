"""Environment-sourced settings for the core service.

All values come from the process environment, which docker-compose composes
from the existing POSTGRES_* / RABBITMQ_* credential variables.
"""

import base64
import os

# Self-documenting 32-byte throwaway phrase used as the dev/test master key when
# no PII_MASTER_KEY is set. It is exactly 32 ASCII bytes and visibly screams
# "not for prod"; production injects a real key via the PII_MASTER_KEY env var.
DEV_THROWAWAY_MASTER_KEY_PHRASE = "policyflow-dev-throwaway-key!!!!"
DEV_THROWAWAY_MASTER_KEY_BASE64 = base64.b64encode(
    DEV_THROWAWAY_MASTER_KEY_PHRASE.encode("ascii")
).decode("ascii")


def decode_master_key(raw_base64: str) -> bytes:
    """Base64-decode a master key and confirm it is exactly 32 bytes.

    The PII master key wraps every tenant's data key, so a malformed key must
    fail loudly at boot rather than silently degrade. Any base64 decode error
    or a wrong length raises ``ValueError`` with a clear message; on success the
    32 raw bytes are returned.
    """
    try:
        decoded_key = base64.b64decode(raw_base64, validate=True)
    except (ValueError, base64.binascii.Error) as error:
        raise ValueError(
            "PII master key is not valid base64; "
            "set PII_MASTER_KEY to a base64-encoded 32-byte key."
        ) from error

    if len(decoded_key) != 32:
        raise ValueError(
            "PII master key must decode to exactly 32 bytes, "
            f"but decoded to {len(decoded_key)} bytes."
        )

    return decoded_key


class Settings:
    """Settings read once from the environment at import time."""

    def __init__(self) -> None:
        # Short commit SHA baked in at build time (ARG GIT_SHA -> ENV APP_VERSION).
        # Defaults to "dev" for local runs where no SHA is injected.
        self.app_version: str = os.environ.get("APP_VERSION", "dev")

        # asyncpg connection URL for the Postgres reachability probe.
        self.database_url: str = os.environ.get("DATABASE_URL", "")

        # aio-pika (AMQP) connection URL for the RabbitMQ reachability probe.
        self.rabbitmq_url: str = os.environ.get("RABBITMQ_URL", "")

        # The durable topic exchange every event envelope is published to. This is
        # the single source of truth for the name; broker.py reads it. Defaults to
        # the TDD §5.4 literal; override via EVENT_EXCHANGE.
        self.event_exchange: str = os.environ.get("EVENT_EXCHANGE", "policyflow.events")

        # How long the outbox relay sleeps between sweeps, in seconds. Defaults to
        # 1.0 (the TDD's ~1s suggestion); override via OUTBOX_POLL_INTERVAL_SECONDS.
        self.outbox_poll_interval_seconds: float = float(
            os.environ.get("OUTBOX_POLL_INTERVAL_SECONDS", "1.0")
        )

        # How long a login session stays valid, in seconds. Defaults to 8 hours
        # (28800s); override via SESSION_LIFETIME_SECONDS.
        self.session_lifetime_seconds: int = int(
            os.environ.get("SESSION_LIFETIME_SECONDS", "28800")
        )

        # How long a demo *visit* session stays valid, in seconds — the 24-hour
        # window the masthead counts down and the purge sweeps once expired.
        # Defaults to 86400 (24h); override via DEMO_SESSION_LIFETIME_SECONDS.
        # Set once at mint onto `expires_at` and the cookie's max_age; not slid.
        self.demo_session_lifetime_seconds: int = int(
            os.environ.get("DEMO_SESSION_LIFETIME_SECONDS", "86400")
        )

        # How long the in-process demo-lifecycle scheduler sleeps between expiry
        # sweeps, in seconds. Each tick runs `purge(Expired())` so expired demo
        # sessions self-clean. Defaults to 300 (5 minutes); override via
        # DEMO_PURGE_INTERVAL_SECONDS.
        self.demo_purge_interval_seconds: int = int(
            os.environ.get("DEMO_PURGE_INTERVAL_SECONDS", "300")
        )

        # The UTC hour (0-23) at which the demo-lifecycle scheduler fires its once-
        # a-night canonical wipe (`purge(All())`), resetting the demo to seed state.
        # Defaults to 4 (a quiet hour); override via DEMO_NIGHTLY_RESET_HOUR_UTC.
        self.demo_nightly_reset_hour_utc: int = int(
            os.environ.get("DEMO_NIGHTLY_RESET_HOUR_UTC", "4")
        )

        # Public-intake rate limit: how many requests one IP may make per window
        # before the limiter blocks it. Defaults to 5; override via
        # PUBLIC_INTAKE_RATE_LIMIT. Read by app/leads/rate_limit.py.
        self.public_intake_rate_limit: int = int(
            os.environ.get("PUBLIC_INTAKE_RATE_LIMIT", "5")
        )

        # The public-intake rate-limit window length, in seconds. Defaults to 60.0;
        # override via PUBLIC_INTAKE_RATE_LIMIT_WINDOW_SECONDS. Read by
        # app/leads/rate_limit.py.
        self.public_intake_rate_limit_window_seconds: float = float(
            os.environ.get("PUBLIC_INTAKE_RATE_LIMIT_WINDOW_SECONDS", "60.0")
        )

        # Whether the session cookie carries the Secure flag (HTTPS-only).
        # Default off for local HTTP; prod sets SESSION_COOKIE_SECURE=true.
        self.session_cookie_secure: bool = os.environ.get(
            "SESSION_COOKIE_SECURE", "false"
        ).strip().lower() in ("true", "1", "yes")

        # Whether the passwordless demo login (assume-persona) is enabled. Default
        # on, since this build is the demo; the off-switch is for a hypothetical
        # non-demo deployment, where DEMO_LOGIN_ENABLED=false makes the endpoint
        # refuse with 403. Mirrors the session_cookie_secure truthy-set idiom.
        self.demo_login_enabled: bool = os.environ.get(
            "DEMO_LOGIN_ENABLED", "true"
        ).strip().lower() in ("true", "1", "yes")

        # The password every seeded demo persona is created with. The dev/test
        # default is a throwaway value; prod injects the real password via SSM
        # (Terraform sets SEED_USER_PASSWORD in the container environment).
        self.seed_user_password: str = os.environ.get(
            "SEED_USER_PASSWORD", "demo-password-change-me"
        )

        # The master key that wraps each tenant's data key, exposed as the
        # decoded 32 raw bytes. The dev/test default is a throwaway value; prod
        # injects a real base64-encoded 32-byte key via SSM (Terraform sets
        # PII_MASTER_KEY in the container environment). Decoding happens here at
        # import time, so a malformed key fails boot loudly (fail-fast).
        self.pii_master_key: bytes = decode_master_key(
            os.environ.get("PII_MASTER_KEY", DEV_THROWAWAY_MASTER_KEY_BASE64)
        )


settings = Settings()
