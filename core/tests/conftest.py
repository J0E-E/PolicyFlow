"""Shared pytest fixtures for the core backend test suite.

Provides an async HTTP client wired directly to the FastAPI app in-process via
`httpx.ASGITransport`, so tests exercise the real async request path without
binding a network port or running a server.
"""

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
