"""Substrate proof for migration 0013 — demo_purge role, grants, index (Epic 9).

These assert the purge backbone after `upgrade head` against the real Postgres
booted in Docker (the same `database_engine` substrate as `test_tenant_schemas.py`
/ `test_event_bus_migration.py`). Every expected value is read from
`app.tenancy.registry`, so the assertions stay in lock-step with the single source
of truth:

- the `demo_purge` role exists (`pg_roles`) and the connected login role is a
  member of it (so the purge engine can `SET ROLE` into it);
- each tenant's `leads` has the `ix_leads_demo_session_id` index (`pg_indexes`);
- a `SET ROLE demo_purge` session can DELETE a `leads` row but is **denied**
  INSERT — the role purges, never writes.

The DELETE/INSERT capability check seeds one throwaway row as the login role, then
flips into `demo_purge` to prove the grant shape end-to-end (an INSERT under the
role must raise insufficient-privilege; a DELETE must succeed).
"""

import uuid

import pytest
from sqlalchemy import text

from app.tenancy.registry import DEMO_PURGE_ROLE, TENANTS


@pytest.mark.asyncio
async def test_demo_purge_role_exists_and_login_role_is_member(database_engine):
    """The `demo_purge` role exists and the login role can `SET ROLE` into it."""
    async with database_engine.connect() as connection:
        role_rows = await connection.execute(
            text("SELECT rolname FROM pg_roles")
        )
        role_names = {row[0] for row in role_rows}
        assert DEMO_PURGE_ROLE in role_names

        membership_rows = await connection.execute(
            text(
                "SELECT parent.rolname "
                "FROM pg_auth_members member "
                "JOIN pg_roles parent ON parent.oid = member.roleid "
                "JOIN pg_roles child ON child.oid = member.member "
                "WHERE child.rolname = CURRENT_USER"
            )
        )
        member_of_roles = {row[0] for row in membership_rows}
        assert DEMO_PURGE_ROLE in member_of_roles


@pytest.mark.asyncio
async def test_each_tenant_leads_has_demo_session_id_index(database_engine):
    """Every tenant's `leads` table carries `ix_leads_demo_session_id`."""
    async with database_engine.connect() as connection:
        for tenant in TENANTS:
            index_rows = await connection.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname = :schema AND tablename = 'leads'"
                ),
                {"schema": tenant.schema_name},
            )
            index_names = {row[0] for row in index_rows}
            assert "ix_leads_demo_session_id" in index_names


@pytest.mark.asyncio
async def test_demo_purge_role_can_delete_but_not_insert_leads(database_engine):
    """Under `SET ROLE demo_purge`, a leads DELETE succeeds and an INSERT is denied.

    Proves the tight grant shape end-to-end on one tenant's schema: the role is
    granted SELECT + DELETE (so it resolves ids and removes overlay rows) but never
    INSERT or UPDATE. A throwaway row is seeded as the login role; the role flip
    then proves INSERT raises insufficient-privilege and DELETE succeeds.
    """
    tenant = TENANTS[0]
    schema = tenant.schema_name
    row_id = uuid.uuid4()

    async with database_engine.connect() as connection:
        # Seed one minimal row as the login role (full CRUD via 0003 defaults).
        await connection.execute(
            text(
                f"INSERT INTO {schema}.leads "
                "(id, first_name, last_name, email_encrypted, email_blind_index, "
                "phone_encrypted, phone_blind_index, date_of_birth_encrypted, "
                "age_band, zip_code, product_lines_of_interest, "
                "preferred_contact_method, lead_source, status, correlation_id) "
                "VALUES (:id, 'Purge', 'Probe', 'x', 'x', 'x', 'x', 'x', "
                "'65-74', '00000', '{}', 'email', 'public_form', 'New', :cid)"
            ),
            {"id": row_id, "cid": uuid.uuid4()},
        )
        await connection.commit()

        # Flip into the purge role for the capability checks.
        await connection.execute(text(f"SET ROLE {DEMO_PURGE_ROLE}"))
        await connection.execute(text(f"SET search_path TO {schema}"))

        # INSERT must be denied — the role has no INSERT grant.
        with pytest.raises(Exception) as insert_error:
            await connection.execute(
                text(
                    f"INSERT INTO {schema}.leads "
                    "(id, first_name, last_name, email_encrypted, "
                    "email_blind_index, phone_encrypted, phone_blind_index, "
                    "date_of_birth_encrypted, age_band, zip_code, "
                    "product_lines_of_interest, preferred_contact_method, "
                    "lead_source, status, correlation_id) "
                    "VALUES (:id, 'No', 'Insert', 'x', 'x', 'x', 'x', 'x', "
                    "'65-74', '00000', '{}', 'email', 'public_form', 'New', :cid)"
                ),
                {"id": uuid.uuid4(), "cid": uuid.uuid4()},
            )
        assert "permission denied" in str(insert_error.value).lower()
        await connection.rollback()

        # DELETE must succeed — the role is granted DELETE on leads.
        await connection.execute(text(f"SET ROLE {DEMO_PURGE_ROLE}"))
        deleted = await connection.execute(
            text(f"DELETE FROM {schema}.leads WHERE id = :id"),
            {"id": row_id},
        )
        assert deleted.rowcount == 1
        await connection.execute(text("RESET ROLE"))
        await connection.commit()
