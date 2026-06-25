"""DB-backed proof of the "converted to" summary read (P2.1 Epic 7).

`GET /api/leads/{id}/conversion` returns the non-PII summary a frozen lead's
"Converted to" panel renders: the new Contact's name, its Household's name, and the
opportunities opened (product-line key + stage). It reuses `get_lead`'s visibility
guard (404 for missing / cross-tenant / cross-session) and adds a 409 for a lead that
exists but is not `Converted`.

These convert a real lead through the endpoint first (so the read is exercised over
genuinely-written rows), then read the summary back over the DB-backed client. Seams
reused by name from the sibling convert test.
"""

import uuid

from app.leads.state import LeadStatus
from app.tenancy.registry import SUNSHINE

from tests.test_endpoints_db import login_as, seeded  # noqa: F401
from tests.test_lead_convert import (
    SUNSHINE_PRODUCT_LINES,
    convert_body,
    login_agent_and_insert_qualified_lead,
)
from tests.test_lead_reads import (
    insert_lead,
    login_agent_for_slug,
    tenant_id_for_slug,
    unique_contact,
    unique_marker,
)


async def test_conversion_summary_for_a_converted_lead(
    seeded, db_client, database_engine
):
    """A converted lead's summary carries the contact, household, and opportunities."""
    _, lead_id, _ = await login_agent_and_insert_qualified_lead(
        db_client, database_engine
    )
    convert_response = await db_client.post(
        f"/api/leads/{lead_id}/convert", json=convert_body()
    )
    assert convert_response.status_code == 200

    response = await db_client.get(f"/api/leads/{lead_id}/conversion")
    assert response.status_code == 200
    summary = response.json()

    # The contact carries the lead's plaintext name (insert_lead fixes last name).
    assert summary["contact"]["last_name"] == "Reader"
    assert summary["household"]["name"] == "Reader Household"
    product_lines = {opp["product_line"] for opp in summary["opportunities"]}
    assert product_lines == set(SUNSHINE_PRODUCT_LINES)
    assert all(opp["stage"] == "New" for opp in summary["opportunities"])


async def test_conversion_404_for_a_missing_lead(seeded, db_client, database_engine):
    """An id that does not exist in the caller's tenant is a 404."""
    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    response = await db_client.get(f"/api/leads/{uuid.uuid4()}/conversion")
    assert response.status_code == 404


async def test_conversion_409_for_a_lead_that_is_not_converted(
    seeded, db_client, database_engine
):
    """A visible but non-`Converted` lead has nothing to summarize → 409."""
    login_response = await login_agent_for_slug(db_client, SUNSHINE.slug)
    assert login_response.status_code == 200
    agent_id = uuid.UUID(login_response.json()["user"]["id"])
    tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    email, phone = unique_contact()
    lead_id = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        tenant_id,
        first_name=unique_marker(),
        email=email,
        phone=phone,
        status=LeadStatus.QUALIFIED,
        owner_user_id=agent_id,
        owner_username="agent@sunshine.example",
    )

    response = await db_client.get(f"/api/leads/{lead_id}/conversion")
    assert response.status_code == 409
