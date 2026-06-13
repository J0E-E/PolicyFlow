"""DB tests for the PII service seam (Epic 5).

These run against the real Postgres booted in Docker (the same `database_engine`
substrate as `test_tenant_keys.py`). They prove the `app.pii.service` seam:

- a field encrypted under tenant A decrypts back to the original under tenant A,
  and the stored blob is opaque (does not contain the plaintext bytes);
- the blind index is deterministic across calls and equals a direct
  `hmac_blind_index` over the tenant's resolved blind-index subkey;
- a blob encrypted under tenant A cannot be decrypted under tenant B — the
  per-tenant key + tenant-id AAD isolation guarantee fails loudly with a
  `ValueError`.

The service composes Epic 4's `get_tenant_keys`, which reads the wrapped root key
through the module-global `session_factory`. As in `test_tenant_keys.py`, each
test inserts its own wrapped row directly (the Epic 6 seed does not exist yet),
using a **fresh `uuid4` tenant id per test** so the process-lifetime key cache
never collides between tests. The `container_session_factory` fixture points
`app.pii.keys.session_factory` at the migrated container database.
"""

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.pii import keys as keys_module
from app.pii.crypto import hmac_blind_index, wrap_key
from app.pii.keys import get_tenant_keys
from app.pii.service import compute_blind_index, decrypt_field, encrypt_field


@pytest.fixture
def container_session_factory(database_engine, monkeypatch):
    """Point `app.pii.keys.session_factory` at the migrated container database.

    `get_tenant_keys` reads the wrapped root key through the module-global
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
async def test_encrypt_then_decrypt_round_trips_under_same_tenant(
    container_session_factory,
):
    """A field encrypted under a tenant decrypts back, and the blob is opaque."""
    tenant_id = uuid.uuid4()
    await _insert_wrapped_root_key(container_session_factory, tenant_id, os.urandom(32))

    plaintext = "jane.doe@example.com"
    blob = await encrypt_field(tenant_id, plaintext)

    # The stored blob is opaque: it does not contain the plaintext in the clear.
    assert plaintext.encode("utf-8") not in blob

    assert await decrypt_field(tenant_id, blob) == plaintext


@pytest.mark.asyncio
async def test_compute_blind_index_is_deterministic_and_matches_primitive(
    container_session_factory,
):
    """The blind index is stable across calls and equals the direct primitive."""
    tenant_id = uuid.uuid4()
    await _insert_wrapped_root_key(container_session_factory, tenant_id, os.urandom(32))

    normalized_value = "jane.doe@example.com"

    first_index = await compute_blind_index(tenant_id, normalized_value)
    second_index = await compute_blind_index(tenant_id, normalized_value)
    assert first_index == second_index

    tenant_keys = await get_tenant_keys(tenant_id)
    assert first_index == hmac_blind_index(
        tenant_keys.blind_index_key, normalized_value
    )


@pytest.mark.asyncio
async def test_decrypt_under_other_tenant_raises_value_error(
    container_session_factory,
):
    """A blob made for tenant A cannot be decrypted under tenant B."""
    tenant_id_a = uuid.uuid4()
    tenant_id_b = uuid.uuid4()
    await _insert_wrapped_root_key(
        container_session_factory, tenant_id_a, os.urandom(32)
    )
    await _insert_wrapped_root_key(
        container_session_factory, tenant_id_b, os.urandom(32)
    )

    blob = await encrypt_field(tenant_id_a, "jane.doe@example.com")

    with pytest.raises(ValueError):
        await decrypt_field(tenant_id_b, blob)
