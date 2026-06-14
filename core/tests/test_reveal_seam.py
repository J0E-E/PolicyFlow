"""Unit tests for the named PII reveal seam.

Pure unit tests — no DB, no Docker — matching the no-Docker style of
`test_masking.py`. The seam is a deliberate no-op today (P1.4 audit + P1.5
`pii.revealed` event fill it later), so these prove only its two load-bearing
properties: calling it returns `None`, and it is an async (awaitable) function so
Epic 12's reveal endpoint can `await` it.
"""

import inspect
import uuid

import pytest

from app.auth.provider import Identity
from app.models.user import Role
from app.pii.reveal_seam import on_pii_revealed


@pytest.mark.asyncio
async def test_on_pii_revealed_returns_none():
    """Awaiting the seam with a real identity and sample arguments returns `None`."""
    identity = Identity(
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        role=Role.AGENT,
        username="agent.one@example",
    )

    result = await on_pii_revealed(
        identity,
        entity_type="pii_demo",
        entity_id=uuid.uuid4(),
        field_name="email",
    )

    assert result is None


def test_on_pii_revealed_is_an_async_function():
    """The seam is a coroutine function, so Epic 12 can `await` it."""
    assert inspect.iscoroutinefunction(on_pii_revealed) is True
