"""Environment-sourced settings for the core service.

All values come from the process environment, which docker-compose composes
from the existing POSTGRES_* / RABBITMQ_* credential variables.
"""

import os


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

        # How long a login session stays valid, in seconds. Defaults to 8 hours
        # (28800s); override via SESSION_LIFETIME_SECONDS.
        self.session_lifetime_seconds: int = int(
            os.environ.get("SESSION_LIFETIME_SECONDS", "28800")
        )

        # Whether the session cookie carries the Secure flag (HTTPS-only).
        # Default off for local HTTP; prod sets SESSION_COOKIE_SECURE=true.
        self.session_cookie_secure: bool = os.environ.get(
            "SESSION_COOKIE_SECURE", "false"
        ).strip().lower() in ("true", "1", "yes")


settings = Settings()
