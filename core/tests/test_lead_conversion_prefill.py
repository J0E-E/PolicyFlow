"""DB-backed proof of the duplicate pre-select read (P2.1 Epic 9).

`GET /api/leads/{id}/conversion-prefill` resolves, server-side, the household to
pre-select on the convert screen: when the lead is flagged a duplicate of a
**converted** prior, that prior's household. It reuses `get_lead`'s visibility guard
(404) and never 409s — a non-duplicate (or a duplicate of a non-converted prior) is a
normal `{"preselected_household": null}`.

These convert a prior lead through the endpoint (so a real converted household
exists), then insert a second lead flagged as its duplicate and read the prefill back.
Seams reused from the convert test.
"""

import uuid

from app.tenancy.registry import SUNSHINE

from tests.test_endpoints_db import login_as, seeded  # noqa: F401
from tests.test_lead_convert import (
    convert_body,
    login_agent_and_insert_qualified_lead,
    read_one,
)
from tests.test_lead_reads import (
    insert_lead,
    login_agent_for_slug,
    tenant_id_for_slug,
    unique_contact,
    unique_marker,
)


async def convert_a_prior_lead(db_client, database_engine):
    """Convert a fresh lead and return `(prior_lead_id, household_id, household_name)`."""
    _, prior_lead_id, _ = await login_agent_and_insert_qualified_lead(
        db_client, database_engine
    )
    response = await db_client.post(
        f"/api/leads/{prior_lead_id}/convert", json=convert_body()
    )
    assert response.status_code == 200
    contact_id = uuid.UUID(response.json()["lead"]["converted_contact_id"])
    row = await read_one(
        database_engine,
        f"SELECT household_id, "
        f"(SELECT name FROM {SUNSHINE.schema_name}.households h "
        f" WHERE h.id = c.household_id) AS household_name "
        f"FROM {SUNSHINE.schema_name}.contacts c WHERE c.id = :id",
        {"id": contact_id},
    )
    return prior_lead_id, row.household_id, row.household_name


async def insert_duplicate_lead(database_engine, duplicate_of_lead_id):
    """Insert a Sunshine lead flagged as a duplicate of `duplicate_of_lead_id`."""
    tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    email, phone = unique_contact()
    return await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        tenant_id,
        first_name=unique_marker(),
        email=email,
        phone=phone,
        duplicate_of_lead_id=duplicate_of_lead_id,
    )


async def test_prefill_pre_selects_a_converted_priors_household(
    seeded, db_client, database_engine
):
    """A lead flagged as a duplicate of a converted prior pre-selects its household."""
    prior_lead_id, household_id, household_name = await convert_a_prior_lead(
        db_client, database_engine
    )
    duplicate_lead_id = await insert_duplicate_lead(database_engine, prior_lead_id)

    response = await db_client.get(
        f"/api/leads/{duplicate_lead_id}/conversion-prefill"
    )
    assert response.status_code == 200
    preselected = response.json()["preselected_household"]
    assert preselected is not None
    assert preselected["id"] == str(household_id)
    assert preselected["name"] == household_name


async def test_prefill_is_null_for_a_lead_that_is_not_a_duplicate(
    seeded, db_client, database_engine
):
    """A lead with no duplicate flag pre-selects nothing (null)."""
    _, lead_id, _ = await login_agent_and_insert_qualified_lead(
        db_client, database_engine
    )
    response = await db_client.get(f"/api/leads/{lead_id}/conversion-prefill")
    assert response.status_code == 200
    assert response.json()["preselected_household"] is None


async def test_prefill_is_null_when_the_prior_is_not_converted(
    seeded, db_client, database_engine
):
    """A duplicate of a prior that hasn't been converted pre-selects nothing (null)."""
    # The prior is a plain (un-converted) lead.
    tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    email, phone = unique_contact()
    prior_lead_id = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        tenant_id,
        first_name=unique_marker(),
        email=email,
        phone=phone,
    )
    duplicate_lead_id = await insert_duplicate_lead(database_engine, prior_lead_id)

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    response = await db_client.get(
        f"/api/leads/{duplicate_lead_id}/conversion-prefill"
    )
    assert response.status_code == 200
    assert response.json()["preselected_household"] is None


async def test_prefill_404_for_a_missing_lead(seeded, db_client, database_engine):
    """An id that does not exist in the caller's tenant is a 404."""
    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    response = await db_client.get(f"/api/leads/{uuid.uuid4()}/conversion-prefill")
    assert response.status_code == 404
