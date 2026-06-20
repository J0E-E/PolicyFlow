"""DB-backed proof of the lead resolve-duplicate action (Epic 14, P1.7).

Intake flags a new lead when the matcher finds a prior matching lead — the new lead
carries a `duplicate_of_lead_id` linkage and an unresolved flag. Epic 14 adds the one
endpoint that clears that flag: `POST /api/leads/{id}/resolve-duplicate` with a body
`{"action": "link" | "new" | "reject"}`:

- `link` — confirm it is the same person: keep `duplicate_of_lead_id`, set
  `duplicate_resolution = "linked"`. No event.
- `new` — a genuinely different person: clear `duplicate_of_lead_id` to null, set
  `duplicate_resolution = "new"`. No event.
- `reject` — discard it as a duplicate: move the `New` lead to `Rejected`, set
  `duplicate_resolution = "rejected"` (keep the linkage), and publish `lead.rejected`
  with payload `{entity_id, reason_kind: "duplicate"}` (no `rejection_reason`). This
  path owns the `New → Rejected` move (Epic 13's `/reject` owns `Working → Rejected`),
  so a non-`New` lead is a 409.

Every action requires the lead to be **flagged** — an unflagged lead
(`duplicate_of_lead_id IS NULL`) is a `409 "lead is not flagged as a duplicate"`. The
endpoint gates on `CREATE_EDIT_RECORDS` and maps a missing / cross-tenant id to a
`404`, the anonymous caller to a `401`, and an unknown `action` to a `422`. It returns
`200` (no resource created).

These drive the real endpoint over the DB-backed client (the same `seeded` /
`db_client` / `database_engine` substrate the other endpoint tests use) and read back
over the SELECT-capable superuser `database_engine` connection. The controllable
flagged-duplicate start state (which the create endpoint can produce only as a side
effect of a real match) is inserted directly into the tenant schema through the
**normal encryption path** via the shared `insert_lead` seam, which Epic 14 extended
with a `duplicate_of_lead_id` keyword.

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no
`@pytest.mark.asyncio` decorator. The seams are reused by name from the sibling test
files: `insert_lead` / `login_agent_for_slug` / `tenant_id_for_slug` /
`unique_marker` / `unique_contact` from `test_lead_reads.py`; `read_lead_row` /
`read_outbox_rows_for_entity` from `test_lead_intake.py`; `login_as` / `seeded` from
`test_endpoints_db.py`; the `db_client` / `database_engine` fixtures come via
`conftest.py`.
"""

import uuid

from app.events.catalog import EventType
from app.leads.state import LeadStatus
from app.models.user import Role
from app.tenancy.registry import FLORIDA, SUNSHINE

from tests.test_endpoints_db import login_as, seeded  # noqa: F401
from tests.test_lead_intake import read_lead_row, read_outbox_rows_for_entity
from tests.test_lead_reads import (
    insert_lead,
    login_agent_for_slug,
    tenant_id_for_slug,
    unique_marker,
)


def unique_contact() -> tuple[str, str]:
    """Return an (email, phone) pair unique to one insert, collision-proof on both keys.

    The container DB is **session-scoped and shared**, so every lead these tests insert
    must own contact details no other test's (or the seed's) lead fingerprints the same
    on — the matcher matches on the email **or** phone blind index. The sibling
    `unique_contact` helpers build the phone as `+1 (415) 555-{token[:4]}`, whose digits
    after `normalize_phone` (it drops the hex *letters*) are only a few characters wide —
    enough rows in the shared table and a phone collision becomes likely. This generator
    avoids that: the phone is a distinct `+1999`-prefixed number whose 10 trailing digits
    come from the full uuid's integer (high entropy, all decimal so none are dropped),
    and the email carries a `resolve-`-prefixed full-hex token.
    """
    token = uuid.uuid4().hex
    phone_digits = f"{uuid.uuid4().int % 10**10:010d}"
    return (f"resolve-{token}@example.com", f"+1999{phone_digits}")


async def insert_flagged_new_lead(database_engine, schema_name, tenant_id, **kwargs):
    """Insert one flagged `New` lead, returning `(target_lead_id, flagged_lead_id)`.

    The common setup these tests share: a flagged duplicate is a lead whose
    `duplicate_of_lead_id` points at a prior "target" lead. This inserts the target
    first (a plain lead), then the flagged lead linked to it — both with unique markers
    and contacts so the shared container's accumulated rows can't collide. Extra keyword
    arguments (e.g. `status`) pass through to the flagged lead's `insert_lead`.
    """
    target_email, target_phone = unique_contact()
    target_lead_id = await insert_lead(
        database_engine,
        schema_name,
        tenant_id,
        first_name=unique_marker(),
        email=target_email,
        phone=target_phone,
    )

    flagged_email, flagged_phone = unique_contact()
    flagged_lead_id = await insert_lead(
        database_engine,
        schema_name,
        tenant_id,
        first_name=unique_marker(),
        email=flagged_email,
        phone=flagged_phone,
        status=kwargs.pop("status", LeadStatus.NEW),
        duplicate_of_lead_id=target_lead_id,
        **kwargs,
    )
    return target_lead_id, flagged_lead_id


# --- Phase 1: link — keep linkage, mark linked, no event ---------------------


async def test_link_keeps_linkage_and_marks_linked(seeded, db_client, database_engine):
    """`link` → 200 with `duplicate_resolution = "linked"`, the linkage kept.

    A Sunshine Agent links a flagged lead: the response is the masked read shape with
    `duplicate_resolution = "linked"` and `duplicate_of_lead_id` still set to the
    target, and the stored row agrees. No `lead.rejected` event is enqueued.
    """
    tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    target_lead_id, flagged_lead_id = await insert_flagged_new_lead(
        database_engine, SUNSHINE.schema_name, tenant_id
    )

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    response = await db_client.post(
        f"/api/leads/{flagged_lead_id}/resolve-duplicate", json={"action": "link"}
    )

    assert response.status_code == 200
    lead = response.json()["lead"]
    assert lead["duplicate_resolution"] == "linked"
    assert lead["duplicate_of_lead_id"] == str(target_lead_id)
    assert lead["status"] == "New"

    row = await read_lead_row(database_engine, SUNSHINE.schema_name, flagged_lead_id)
    assert row.duplicate_resolution == "linked"
    assert row.duplicate_of_lead_id == target_lead_id

    # No event on the link path.
    rows = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.LEAD_REJECTED, flagged_lead_id
    )
    assert rows == []


# --- Phase 2: new — clear the flag, mark new, no event -----------------------


async def test_new_clears_the_flag_and_marks_new(seeded, db_client, database_engine):
    """`new` → 200 with `duplicate_resolution = "new"`, the linkage cleared to null.

    A Sunshine Agent marks a flagged lead as a genuinely different person: the response
    has `duplicate_resolution = "new"` and a null `duplicate_of_lead_id`, and the stored
    row agrees. No event.
    """
    tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    _, flagged_lead_id = await insert_flagged_new_lead(
        database_engine, SUNSHINE.schema_name, tenant_id
    )

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    response = await db_client.post(
        f"/api/leads/{flagged_lead_id}/resolve-duplicate", json={"action": "new"}
    )

    assert response.status_code == 200
    lead = response.json()["lead"]
    assert lead["duplicate_resolution"] == "new"
    assert lead["duplicate_of_lead_id"] is None
    assert lead["status"] == "New"

    row = await read_lead_row(database_engine, SUNSHINE.schema_name, flagged_lead_id)
    assert row.duplicate_resolution == "new"
    assert row.duplicate_of_lead_id is None

    rows = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.LEAD_REJECTED, flagged_lead_id
    )
    assert rows == []


# --- Phase 3: reject — New → Rejected, keep linkage, event -------------------


async def test_reject_moves_new_to_rejected_keeping_linkage(
    seeded, db_client, database_engine
):
    """`reject` on a flagged `New` lead → 200 `Rejected`, `rejected` resolution, linkage kept.

    A Sunshine Agent discards a flagged `New` lead as a duplicate: the response is
    `Rejected` with `duplicate_resolution = "rejected"` and the `duplicate_of_lead_id`
    linkage **kept** (unlike `new`). The stored row agrees, and no free-text
    `rejection_reason` is set (that column is the qualify/reject path's).
    """
    tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    target_lead_id, flagged_lead_id = await insert_flagged_new_lead(
        database_engine, SUNSHINE.schema_name, tenant_id
    )

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    response = await db_client.post(
        f"/api/leads/{flagged_lead_id}/resolve-duplicate", json={"action": "reject"}
    )

    assert response.status_code == 200
    lead = response.json()["lead"]
    assert lead["status"] == "Rejected"
    assert lead["duplicate_resolution"] == "rejected"
    assert lead["duplicate_of_lead_id"] == str(target_lead_id)
    assert lead["rejection_reason"] is None

    row = await read_lead_row(database_engine, SUNSHINE.schema_name, flagged_lead_id)
    assert row.status == "Rejected"
    assert row.duplicate_resolution == "rejected"
    assert row.duplicate_of_lead_id == target_lead_id


async def test_reject_enqueues_one_lead_rejected_event_with_duplicate_reason(
    seeded, db_client, database_engine
):
    """A duplicate-reject enqueues one `lead.rejected` row with `reason_kind = "duplicate"`.

    Exactly one `lead.rejected` row lands in the tenant `outbox`; its payload is the
    entity reference plus `reason_kind = "duplicate"` (this path, not the qualify/reject
    path's `"qualify_reject"`). The actor is the Agent and its `correlation_id` equals
    the lead's own — one lead, one trace id.
    """
    tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    _, flagged_lead_id = await insert_flagged_new_lead(
        database_engine, SUNSHINE.schema_name, tenant_id
    )

    login_response = await login_agent_for_slug(db_client, SUNSHINE.slug)
    assert login_response.status_code == 200
    agent_id = login_response.json()["user"]["id"]

    response = await db_client.post(
        f"/api/leads/{flagged_lead_id}/resolve-duplicate", json={"action": "reject"}
    )
    assert response.status_code == 200

    rows = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.LEAD_REJECTED, flagged_lead_id
    )
    assert len(rows) == 1
    rejected = rows[0]
    assert rejected.payload == {
        "entity_id": str(flagged_lead_id),
        "reason_kind": "duplicate",
    }
    assert rejected.actor_user_id == uuid.UUID(agent_id)
    assert rejected.actor_role == Role.AGENT

    row = await read_lead_row(database_engine, SUNSHINE.schema_name, flagged_lead_id)
    assert rejected.correlation_id == row.correlation_id


async def test_reject_on_flagged_working_lead_is_409(
    seeded, db_client, database_engine
):
    """`reject` on a flagged non-`New` (`Working`) lead → 409 (start-state partition).

    This path owns `New → Rejected`; a flagged `Working` lead is rejected via Epic 13's
    `/reject` instead. So a `Working` lead here is a 409 even though it is flagged — the
    guard partitions the start state before the formal transition.
    """
    tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    _, flagged_lead_id = await insert_flagged_new_lead(
        database_engine,
        SUNSHINE.schema_name,
        tenant_id,
        status=LeadStatus.WORKING,
        owner_user_id=uuid.uuid4(),
        owner_username="owner@sunshine.example",
    )

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    response = await db_client.post(
        f"/api/leads/{flagged_lead_id}/resolve-duplicate", json={"action": "reject"}
    )

    assert response.status_code == 409


# --- Phase 4: flag precondition — unflagged lead → 409 -----------------------


async def test_resolving_an_unflagged_lead_is_409(seeded, db_client, database_engine):
    """Any action on an unflagged lead → 409 `"lead is not flagged as a duplicate"`.

    The endpoint exists only to resolve a flag, so a lead with a null
    `duplicate_of_lead_id` has nothing to resolve — a 409 with the dedicated message,
    before any action-specific logic runs.
    """
    tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    email, phone = unique_contact()
    unflagged_lead_id = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        tenant_id,
        first_name=unique_marker(),
        email=email,
        phone=phone,
        status=LeadStatus.NEW,
    )

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    response = await db_client.post(
        f"/api/leads/{unflagged_lead_id}/resolve-duplicate", json={"action": "link"}
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "lead is not flagged as a duplicate"}


# --- Phase 5: validation — unknown action → 422 ------------------------------


async def test_unknown_action_is_422(seeded, db_client, database_engine):
    """An `action` outside {link, new, reject} → 422 (the strict `Literal`)."""
    tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    _, flagged_lead_id = await insert_flagged_new_lead(
        database_engine, SUNSHINE.schema_name, tenant_id
    )

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    response = await db_client.post(
        f"/api/leads/{flagged_lead_id}/resolve-duplicate", json={"action": "merge"}
    )

    assert response.status_code == 422


# --- Phase 6: RBAC -----------------------------------------------------------


async def test_resolve_forbidden_for_read_only(seeded, db_client, database_engine):
    """A Read-Only user lacks `CREATE_EDIT_RECORDS` → 403 on resolve-duplicate."""
    tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    _, flagged_lead_id = await insert_flagged_new_lead(
        database_engine, SUNSHINE.schema_name, tenant_id
    )

    assert (await login_as(db_client, Role.READ_ONLY)).status_code == 200
    response = await db_client.post(
        f"/api/leads/{flagged_lead_id}/resolve-duplicate", json={"action": "link"}
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "insufficient permissions"}


async def test_resolve_unauthenticated_is_401(seeded, db_client):
    """A fresh client with no session cookie → 401 on resolve-duplicate."""
    response = await db_client.post(
        f"/api/leads/{uuid.uuid4()}/resolve-duplicate", json={"action": "link"}
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}


# --- Phase 7: not found → 404 (missing + cross-tenant) -----------------------


async def test_resolve_unknown_id_is_404(seeded, db_client):
    """A resolve on a lead id that exists nowhere → 404 `"lead not found"`."""
    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200

    response = await db_client.post(
        f"/api/leads/{uuid.uuid4()}/resolve-duplicate", json={"action": "link"}
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "lead not found"}


async def test_resolve_cross_tenant_id_is_404(seeded, db_client, database_engine):
    """A Florida flagged lead a Sunshine Agent tries to resolve → 404, identical to missing.

    `get_tenant_db` scopes the lookup to Sunshine's schema, so Florida's row is
    physically out of reach — a caller can neither act on nor probe for another tenant's
    leads.
    """
    florida_tenant_id = await tenant_id_for_slug(database_engine, FLORIDA.slug)
    _, florida_flagged_lead_id = await insert_flagged_new_lead(
        database_engine, FLORIDA.schema_name, florida_tenant_id
    )

    assert (await login_agent_for_slug(db_client, SUNSHINE.slug)).status_code == 200
    response = await db_client.post(
        f"/api/leads/{florida_flagged_lead_id}/resolve-duplicate",
        json={"action": "link"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "lead not found"}
