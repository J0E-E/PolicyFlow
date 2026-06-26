"""DB-backed proof of policy issuance on approval (P2.3 Epic 8).

An approved application auto-issues one `Policy` in the approve transaction: a
deterministic human-readable number (`POL-<PREFIX>-<YEAR>-<6HEX>` from the
application uuid), the carrier / product / coverage / premium copied from the
application, `status='Active'`, a `policy.created` event, and the opportunity at
*Policy Active*. A declined application issues no policy.

Builds a submit-ready Draft application (reusing `test_application_submit`'s seam),
submits it, and reads the issued policy back over the SELECT-capable superuser
engine.

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no decorator.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from app.events.catalog import EventType
from app.tenancy.registry import SUNSHINE

from tests.test_endpoints_db import login_as, seeded  # noqa: F401
from tests.test_lead_intake import read_outbox_rows_for_entity
from tests.test_lead_reads import unique_marker
from tests.test_application_submit import submit_ready_application
from tests.test_quote_round_trip import container_quotes_session_factory  # noqa: F401


async def read_policy_for_application(database_engine, application_id):
    """Read the issued policy for an application via the superuser engine, or None."""
    async with database_engine.connect() as connection:
        return (
            await connection.execute(
                text(
                    f"SELECT id, policy_number, status, carrier, coverage_amount, "
                    f"premium_annual FROM {SUNSHINE.schema_name}.policies "
                    "WHERE application_id = :id"
                ),
                {"id": application_id},
            )
        ).one_or_none()


async def test_approval_issues_a_policy_with_a_deterministic_number(
    db_client, database_engine, seeded, container_quotes_session_factory
):
    """Approving issues an Active policy whose number is derived from the application."""
    application_id, opportunity_id = await submit_ready_application(db_client, database_engine)
    submit = await db_client.post(f"/api/applications/{application_id}/submit")
    assert submit.status_code == 200
    policy_in_response = submit.json()["policy"]

    stored = await read_policy_for_application(database_engine, uuid.UUID(application_id))
    assert stored is not None
    assert stored.status == "Active"

    # The number is POL-<PREFIX>-<YEAR>-<6HEX>, deterministic from the application uuid.
    expected_year = datetime.now(timezone.utc).year
    expected_number = (
        f"POL-SUN-{expected_year}-{uuid.UUID(application_id).hex[:6].upper()}"
    )
    assert stored.policy_number == expected_number
    assert policy_in_response["policy_number"] == expected_number

    # `policy.created` fired for the issued policy.
    created_rows = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.POLICY_CREATED, stored.id
    )
    assert len(created_rows) == 1


async def test_a_decline_issues_no_policy(
    db_client, database_engine, seeded, container_quotes_session_factory
):
    """A declined application issues no policy row."""
    deny_email = f"deny.{unique_marker()}@{SUNSHINE.email_domain}"
    application_id, _ = await submit_ready_application(
        db_client, database_engine, email=deny_email
    )
    submit = await db_client.post(f"/api/applications/{application_id}/submit")
    assert submit.status_code == 200
    assert submit.json()["policy"] is None

    stored = await read_policy_for_application(database_engine, uuid.UUID(application_id))
    assert stored is None
