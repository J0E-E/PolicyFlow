"""DB-backed proof of the Tenant-1 Medicare ID (P2.3 Epic 11).

For Tenant-1 (Sunshine, `collects_medicare_id=True`) the agent enters a Medicare ID
during the application step; it is encrypted at rest, masked by default on reads, and
revealed only through the audited capability-gated endpoint. Tenant-2 (Florida) never
collects the field — a capture or reveal is refused.

Builds Draft applications the honest way (reusing the submit / step seams) and reads
the stored row back over the SELECT-capable superuser engine.

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no decorator.
"""

import uuid

from sqlalchemy import text

from app.events.catalog import EventType
from app.tenancy.registry import FLORIDA, SUNSHINE

from tests.test_endpoints_db import login_as, seeded  # noqa: F401
from tests.test_lead_intake import read_outbox_rows_for_entity
from tests.test_application_step import draft_application
from tests.test_application_submit import submit_ready_application
from tests.test_quote_round_trip import container_quotes_session_factory  # noqa: F401

MEDICARE_ID = "1EG4TE5MK73"


async def read_medicare_blob(database_engine, schema_name, application_id):
    """Read the stored encrypted Medicare blob via the superuser engine."""
    async with database_engine.connect() as connection:
        return (
            await connection.execute(
                text(
                    "SELECT medicare_id_encrypted "
                    f"FROM {schema_name}.applications WHERE id = :id"
                ),
                {"id": application_id},
            )
        ).scalar_one()


async def test_medicare_id_is_captured_encrypted_and_masked_for_tenant_1(
    db_client, database_engine, seeded, container_quotes_session_factory
):
    """Sunshine captures a Medicare ID, stores it encrypted, and masks it on reads."""
    application_id, _ = await submit_ready_application(db_client, database_engine)

    capture = await db_client.patch(
        f"/api/applications/{application_id}", json={"medicare_id": MEDICARE_ID}
    )
    assert capture.status_code == 200
    application = capture.json()["application"]
    assert application["collects_medicare_id"] is True
    # The read is masked — never the plaintext.
    assert application["medicare_id_masked"] is not None
    assert MEDICARE_ID not in capture.text

    # The stored blob is real ciphertext, not the plaintext.
    blob = await read_medicare_blob(
        database_engine, SUNSHINE.schema_name, uuid.UUID(application_id)
    )
    assert blob is not None
    assert MEDICARE_ID.encode() not in bytes(blob)


async def test_reveal_returns_the_plaintext_and_audits_for_tenant_1(
    db_client, database_engine, seeded, container_quotes_session_factory
):
    """The reveal endpoint decrypts the Medicare ID and records the audited reveal."""
    application_id, _ = await submit_ready_application(db_client, database_engine)
    await db_client.patch(
        f"/api/applications/{application_id}", json={"medicare_id": MEDICARE_ID}
    )

    reveal = await db_client.post(
        f"/api/applications/{application_id}/reveal-medicare-id"
    )
    assert reveal.status_code == 200
    assert reveal.json() == {"field": "medicare_id", "value": MEDICARE_ID}

    # The reveal emitted a `pii.revealed` event keyed on the application (audit seam).
    revealed_rows = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.PII_REVEALED, uuid.UUID(application_id)
    )
    assert len(revealed_rows) == 1
    assert revealed_rows[0].payload["field"] == "medicare_id"


async def test_tenant_2_neither_collects_nor_reveals_a_medicare_id(
    db_client, database_engine, seeded, container_quotes_session_factory
):
    """Florida does not collect a Medicare ID — capture and reveal are both refused."""
    application = await draft_application(db_client, database_engine, FLORIDA, "term_life")
    application_id = application["id"]
    # The serialized application tells the workspace not to render the field.
    assert application["collects_medicare_id"] is False
    assert application["medicare_id_masked"] is None

    # Capturing a Medicare ID for Tenant-2 is a 422.
    capture = await db_client.patch(
        f"/api/applications/{application_id}", json={"medicare_id": MEDICARE_ID}
    )
    assert capture.status_code == 422

    # Revealing for Tenant-2 is a 422.
    reveal = await db_client.post(
        f"/api/applications/{application_id}/reveal-medicare-id"
    )
    assert reveal.status_code == 422
