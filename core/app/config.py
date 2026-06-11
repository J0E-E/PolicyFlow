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


settings = Settings()
