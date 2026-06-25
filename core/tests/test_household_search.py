"""DB-backed proof of the household search read (P2.1 Epic 8).

`GET /api/households?q=` backs the convert "link an existing household" picker: a
tenant-scoped, session-visible name search returning each household with its members'
plaintext names. These convert a real lead first (so a household + contact exist),
then read the search back over the DB-backed client. Seams reused from the convert
test.
"""

import uuid

from app.tenancy.registry import SUNSHINE

from tests.test_endpoints_db import login_as, seeded  # noqa: F401
from tests.test_lead_convert import (
    convert_body,
    login_agent_and_insert_qualified_lead,
    read_one,
)
from tests.test_lead_reads import login_agent_for_slug


async def convert_one_lead(db_client, database_engine):
    """Convert a fresh Sunshine lead and return its new household id."""
    _, lead_id, _ = await login_agent_and_insert_qualified_lead(
        db_client, database_engine
    )
    response = await db_client.post(
        f"/api/leads/{lead_id}/convert", json=convert_body()
    )
    assert response.status_code == 200
    contact_id = uuid.UUID(response.json()["lead"]["converted_contact_id"])
    row = await read_one(
        database_engine,
        f"SELECT household_id FROM {SUNSHINE.schema_name}.contacts WHERE id = :id",
        {"id": contact_id},
    )
    return row.household_id


async def test_household_search_returns_matches_with_members(
    seeded, db_client, database_engine
):
    """A name search returns the matching household and its contacts as members."""
    household_id = await convert_one_lead(db_client, database_engine)

    # Every converted household is named "<last> Household"; the seam fixes the last
    # name to "Reader", so a "Reader" query matches.
    response = await db_client.get("/api/households", params={"q": "Reader"})
    assert response.status_code == 200
    households = response.json()["households"]

    matched = next(
        (h for h in households if h["id"] == str(household_id)), None
    )
    assert matched is not None
    assert matched["name"] == "Reader Household"
    # The contact carried the lead's plaintext last name onto the household member.
    assert any(member["last_name"] == "Reader" for member in matched["members"])


async def test_household_search_excludes_non_matching_names(
    seeded, db_client, database_engine
):
    """A query that matches no household name returns an empty list."""
    await convert_one_lead(db_client, database_engine)

    response = await db_client.get(
        "/api/households", params={"q": "no-such-household-xyz"}
    )
    assert response.status_code == 200
    assert response.json()["households"] == []


async def test_household_search_requires_authentication(
    seeded, db_client, database_engine
):
    """An anonymous caller (no session) cannot search households (401)."""
    response = await db_client.get("/api/households", params={"q": "Reader"})
    assert response.status_code == 401
