"""DB tests for per-tenant key resolution + the in-process cache (Epic 4).

These run against the real Postgres booted in Docker (the same `database_engine`
substrate as `test_tenant_data_keys.py`). They prove the `app.pii.keys` seam:

- a load yields the expected, stable subkeys for both HKDF labels;
- a second `get_tenant_keys` call is a cache hit that re-reads nothing;
- an absent tenant id raises `TenantDataKeyNotFound`.

Because the Epic 6 seed that writes wrapped root keys does not exist yet, each
test inserts its own wrapped row directly, using a **fresh `uuid4` tenant id per
test** so the process-lifetime module cache never collides between tests (no
cache-clearing hook needed).

Test seam for the login-role session: `_read_wrapped_root_key` reads the
module-global `session_factory`, so each test points it at the container with
`monkeypatch.setattr("app.pii.keys.session_factory", <container sessionmaker>)`
built from the `database_engine` fixture.
"""

import os
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.pii import keys as keys_module
from app.pii.crypto import (
    BLIND_INDEX_INFO_LABEL,
    FIELD_ENCRYPTION_INFO_LABEL,
    hkdf_subkey,
    wrap_key,
)
from app.pii.keys import TenantDataKeyNotFound, get_tenant_keys


@pytest.fixture
def container_session_factory(database_engine, monkeypatch):
    """Point `app.pii.keys.session_factory` at the migrated container database.

    `_read_wrapped_root_key` opens its own session from the module-global
    `session_factory`; this fixture swaps that global for a sessionmaker bound to
    the container engine so the key-load reads the real, migrated key store.
    `monkeypatch` restores the real factory after each test.
    """
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    monkeypatch.setattr(keys_module, "session_factory", session_factory)
    return session_factory


async def _insert_wrapped_root_key(
    session_factory: async_sessionmaker, tenant_id: uuid.UUID, root_key: bytes
) -> None:
    """Wrap a root key with the master key and INSERT it for a tenant id.

    Stands in for the not-yet-built Epic 6 seed: produces the exact wrapped blob
    `keys.py` expects to read back and unwrap.
    """
    wrapped_root_key = wrap_key(settings.pii_master_key, root_key)
    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO platform.tenant_data_keys "
                "(tenant_id, wrapped_root_key) VALUES (:tenant_id, :wrapped)"
            ),
            {"tenant_id": tenant_id, "wrapped": wrapped_root_key},
        )
        await session.commit()


@pytest.mark.asyncio
async def test_get_tenant_keys_derives_expected_stable_subkeys(
    container_session_factory,
):
    """Loaded subkeys match HKDF over the unwrapped root key, and are stable."""
    tenant_id = uuid.uuid4()
    root_key = os.urandom(32)
    await _insert_wrapped_root_key(container_session_factory, tenant_id, root_key)

    tenant_keys = await get_tenant_keys(tenant_id)

    assert tenant_keys.encryption_key == hkdf_subkey(
        root_key, FIELD_ENCRYPTION_INFO_LABEL
    )
    assert tenant_keys.blind_index_key == hkdf_subkey(
        root_key, BLIND_INDEX_INFO_LABEL
    )
    # The two subkeys are derived from the same root key but never share material.
    assert tenant_keys.encryption_key != tenant_keys.blind_index_key

    # A second call returns identical keys (stable across calls).
    tenant_keys_again = await get_tenant_keys(tenant_id)
    assert tenant_keys_again == tenant_keys


@pytest.mark.asyncio
async def test_get_tenant_keys_second_call_is_a_cache_hit(
    container_session_factory, monkeypatch
):
    """A second call serves from cache — the wrapped blob is read exactly once."""
    tenant_id = uuid.uuid4()
    root_key = os.urandom(32)
    await _insert_wrapped_root_key(container_session_factory, tenant_id, root_key)

    real_read_wrapped_root_key = keys_module._read_wrapped_root_key
    read_spy = AsyncMock(side_effect=real_read_wrapped_root_key)
    monkeypatch.setattr(keys_module, "_read_wrapped_root_key", read_spy)

    first_keys = await get_tenant_keys(tenant_id)
    second_keys = await get_tenant_keys(tenant_id)

    assert first_keys == second_keys
    assert read_spy.call_count == 1


@pytest.mark.asyncio
async def test_get_tenant_keys_missing_row_raises_not_found(
    container_session_factory,
):
    """A tenant id with no wrapped key row raises `TenantDataKeyNotFound`."""
    missing_tenant_id = uuid.uuid4()

    with pytest.raises(TenantDataKeyNotFound) as raised:
        await get_tenant_keys(missing_tenant_id)

    assert raised.value.tenant_id == missing_tenant_id
    assert str(missing_tenant_id) in str(raised.value)
