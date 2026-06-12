"""Shared test factories for the real-database (substrate) test suite.

One async helper, `insert_active_user`, seeds a committed `User` (and the
`Tenant` it belongs to) into the migrated container database so the session and
provider lifecycle tests (Epic 12) have a real row to authenticate against.

Isolation is by **unique keys**, not rollback: every call suffixes the username,
email, and tenant slug with a fresh `uuid` so no two tests collide in the shared
session-scoped container. Rows accumulate harmlessly in the throwaway database.
Mirrors the unique-key idiom `test_substrate.py` already uses.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import hash_password
from app.models.tenant import Tenant
from app.models.user import Role, User


async def insert_active_user(
    db_session: AsyncSession,
    *,
    role: Role = Role.AGENT,
    password: str = "correct horse battery staple",
    is_active: bool = True,
    username: str | None = None,
) -> User:
    """Insert one committed `User` with a real bcrypt hash and return it.

    Creates a fresh `Tenant` and a `User` whose `username`/`email` are
    `uuid`-suffixed so the row is unique across the shared container. The
    plaintext `password` is hashed with the real `hash_password` so provider
    tests verify against a genuine bcrypt digest; the caller keeps the plaintext.

    The `platform_admin_tenantless` CHECK constraint requires a platform admin to
    have no tenant and every other role to have one, so the user gets a real
    tenant unless its role is `PLATFORM_ADMIN`.
    """
    unique_suffix = uuid.uuid4().hex
    if username is None:
        username = f"user-{unique_suffix}"

    tenant_id = None
    if role is not Role.PLATFORM_ADMIN:
        tenant = Tenant(
            name=f"Tenant {unique_suffix}",
            slug=f"tenant-{unique_suffix}",
        )
        db_session.add(tenant)
        await db_session.flush()
        tenant_id = tenant.id

    user = User(
        tenant_id=tenant_id,
        username=username,
        email=f"{username}@example.test",
        password_hash=hash_password(password),
        role=role,
        is_active=is_active,
    )
    db_session.add(user)
    await db_session.commit()

    return user
