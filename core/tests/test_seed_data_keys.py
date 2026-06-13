"""DB tests for the seed step that mints per-tenant root keys (Epic 6).

These run against the real Postgres booted in Docker (the same `database_engine`
substrate as `test_tenant_keys.py`). They prove `app.seed.seed_tenant_data_keys`:

- it writes exactly one wrapped key per tenant, each unwrapping back to a fresh
  32-byte root key, and the per-tenant root keys differ (real randomness +
  correct master-key wrap);
- a re-seed is idempotent (insert-if-absent): a second run creates nothing and
  leaves the already-stored wrapped blobs byte-for-byte unchanged.

Each test uses **fresh `uuid4` tenant ids** so the session-scoped shared
container database is never polluted between tests.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.models import TenantDataKey
from app.pii.crypto import unwrap_key
from app.seed import ROOT_KEY_LENGTH_BYTES, seed_tenant_data_keys


@pytest.fixture
def container_session_factory(database_engine):
    """A sessionmaker bound to the migrated container database."""
    return async_sessionmaker(database_engine, expire_on_commit=False)


async def _stored_wrapped_keys(
    session_factory: async_sessionmaker, tenant_ids: list[uuid.UUID]
) -> dict[uuid.UUID, bytes]:
    """Read back the stored wrapped root key blob for each tenant id."""
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(
                    TenantDataKey.tenant_id, TenantDataKey.wrapped_root_key
                ).where(TenantDataKey.tenant_id.in_(tenant_ids))
            )
        ).all()
    return {tenant_id: wrapped for tenant_id, wrapped in rows}


@pytest.mark.asyncio
async def test_seed_writes_one_distinct_wrapped_key_per_tenant(
    container_session_factory,
):
    """Each tenant gets one wrapped key that unwraps to a distinct 32-byte root."""
    tenant_ids = [uuid.uuid4(), uuid.uuid4()]

    async with container_session_factory() as session:
        keys_created = await seed_tenant_data_keys(session, tenant_ids)
        await session.commit()

    assert keys_created == len(tenant_ids)

    stored = await _stored_wrapped_keys(container_session_factory, tenant_ids)
    assert set(stored) == set(tenant_ids)

    root_keys = [
        unwrap_key(settings.pii_master_key, stored[tenant_id])
        for tenant_id in tenant_ids
    ]
    # Every stored blob unwraps back to a full-length root key.
    assert all(len(root_key) == ROOT_KEY_LENGTH_BYTES for root_key in root_keys)
    # Each tenant's root key is independently random — never shared material.
    assert root_keys[0] != root_keys[1]


@pytest.mark.asyncio
async def test_re_seed_is_idempotent_and_never_overwrites(
    container_session_factory,
):
    """A second run creates nothing and leaves stored blobs byte-for-byte equal."""
    tenant_ids = [uuid.uuid4(), uuid.uuid4()]

    async with container_session_factory() as session:
        first_created = await seed_tenant_data_keys(session, tenant_ids)
        await session.commit()
    assert first_created == len(tenant_ids)

    blobs_after_first = await _stored_wrapped_keys(
        container_session_factory, tenant_ids
    )

    async with container_session_factory() as session:
        second_created = await seed_tenant_data_keys(session, tenant_ids)
        await session.commit()

    # Insert-if-absent: the re-seed creates no new keys...
    assert second_created == 0
    # ...and leaves the existing wrapped blobs untouched (never re-wrapped).
    blobs_after_second = await _stored_wrapped_keys(
        container_session_factory, tenant_ids
    )
    assert blobs_after_second == blobs_after_first
