"""Shared pytest fixtures for the core backend test suite.

Provides an async HTTP client wired directly to the FastAPI app in-process via
`httpx.ASGITransport`, so tests exercise the real async request path without
binding a network port or running a server.
"""

import os

# Importing the app (and, through it, `app.db` / `app.models`) builds the async
# engine eagerly at import time, which needs a well-formed DATABASE_URL. Default
# one here so a bare test run never fails on an unset URL. `setdefault` means a
# real CI or dev URL already in the environment still wins.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://user:secret@localhost:5432/policyflow"
)

import httpx
import pytest_asyncio

from app.main import app


@pytest_asyncio.fixture
async def client():
    """Yield an async HTTP client bound to the core FastAPI app.

    Requests go straight to the app through an in-process ASGI transport — no
    live server or open socket. This is the foundation later backend tests
    (e.g. the health ok/degraded tests) build on.
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        yield client
