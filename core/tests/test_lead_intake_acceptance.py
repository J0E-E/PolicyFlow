"""Lead-intake acceptance suite for P1.7 (Epic 22).

This is the phase's named acceptance proof: that the whole lead slice works
end-to-end on the real substrate — both intake routes create a lead in the
correct born state, the duplicate flag fires on the blind index with its events
and resolution, claim assigns and qualify/reject terminate (each with its
event), tenant A cannot reach tenant B, and the public abuse controls hold while
the response stays sanitized.

It is packaged **add-only** — it asserts only the genuinely-missing end-to-end
*lifecycle narrative* plus the one physical proof the lead path still lacks, and
deliberately does **not** re-run or duplicate the focused per-epic matrices.
Specifically, what stays owned elsewhere:

- **Each lead event** has its own dedicated DB-backed test: the create +
  `lead.created` (+ duplicate) in `test_lead_intake.py`, claim + `lead.assigned`
  in `test_lead_claim.py`, qualify/reject + `lead.qualified` / `lead.rejected`
  (`reason_kind = qualify_reject`) in `test_lead_qualify_reject.py`, and the
  three resolve-duplicate branches + the duplicate `lead.rejected` in
  `test_lead_resolve_duplicate.py`.
- **Blind-index match without decryption at the unit / DB-substrate level** stays
  in `test_lead_matching_db.py`; this file adds the complementary *endpoint*-level
  proof (the live public intake route flags a duplicate with `decrypt_field`
  patched to raise).
- **HTTP-list + matcher tenant isolation** stays in `test_lead_reads.py` /
  `test_lead_matching_db.py`; the thin A-vs-B re-statement here is a summary, not
  a re-run.
- **The full abuse-control + validation matrix + sanitized response** stays in
  `test_public_intake.py`; the summary here touches one honeypot, one rate-limit,
  and one validation case only.

The phases (simplest-first, each independently reviewable):

- **Phase 1 — physical lead-isolation proof (substrate, no HTTP):** under
  `SET LOCAL ROLE tenant_florida`, a raw SELECT / UPDATE / INSERT on
  `sunshine.leads` is each permission-denied by Postgres, while the same role
  still reads its own `florida.leads` — the one physical proof the lead path lacks
  (the `leads` analogue of `test_isolation_acceptance.py` Phase 1).
- **Phase 2 — full lifecycle (HTTP):** public intake → born `New` / unowned /
  `public_form` → it appears in the unassigned queue → claim (`Working`, owned,
  `lead.assigned`) → qualify (`Qualified`, `lead.qualified`).
- **Phase 3 — agent born state + reject thread (HTTP):** agent `POST /api/leads`
  → born `Working` / owned / `agent_entered` (`lead.created`) → reject
  (`Working → Rejected`, `lead.rejected` with `reason_kind = qualify_reject`).
- **Phase 4 — duplicate thread end-to-end, without decryption (HTTP):** two
  matching public posts; the second flags on the blind index alone (proven by
  patching `decrypt_field` to raise on the flagging post) and enqueues one
  `lead.duplicate_detected` sharing its `lead.created` correlation id; then
  resolve-duplicate `reject` moves the flagged `New` lead to `Rejected` with
  `duplicate_resolution = "rejected"` and a `lead.rejected` `reason_kind =
  "duplicate"`.
- **Phase 5 — abuse-control + HTTP-isolation summary (HTTP):** a filled honeypot
  drops silently, a sixth post from one IP is 429, one validation 422, and a thin
  A-vs-B isolation re-statement (a Sunshine lead is 404 / absent for a Florida
  Agent).

`pytest.ini` sets `asyncio_mode = auto`, so the Phase 2-5 async HTTP tests carry
no `@pytest.mark.asyncio` decorator; the Phase 1 substrate tests that drive the
`database_engine` directly keep it, matching `test_isolation_acceptance.py` /
`test_pii_acceptance.py`. Fixtures (`seeded` / `db_client` / `database_engine` /
`container_keys_session_factory`) and helpers are reused by import from the
per-epic suites — this file builds no new substrate.
"""

import uuid
from unittest import mock

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.events.catalog import EventType
from app.models.user import Role
from app.seed import seed
from app.tenancy.registry import FLORIDA, SUNSHINE, TENANTS

from tests.test_endpoints_db import login_as, seeded  # noqa: F401 — `seeded` used by name
from tests.test_lead_intake import read_lead_row, read_outbox_rows_for_entity
from tests.test_lead_reads import (
    insert_lead,
    login_agent_for_slug,
    tenant_id_for_slug,
    unique_marker,
)
from tests.test_public_intake import (
    _only_lead_id_for_email,
    _two_lead_ids_for_email_oldest_first,
    public_body_with,
)


def unique_public_contact() -> tuple[str, str]:
    """Return an (email, phone) pair unique to one run and **strictly route-valid**.

    The container DB is session-scoped and shared, so a lifecycle that controls
    whether a duplicate is found must own match targets no other test's (or the
    seed's) lead fingerprints the same on — the matcher matches on the email *or*
    phone blind index. The phone is a high-entropy, all-decimal number (so
    `normalize_phone` drops nothing) whose digit fold lands in the public route's
    strict 10-15-digit range, combining `test_public_intake.unique_contact`'s
    route-validity with `test_lead_resolve_duplicate.unique_contact`'s collision
    resistance. The email carries an `acceptance-`-prefixed full-hex token.
    """
    token = uuid.uuid4().hex
    phone_digits = f"{uuid.uuid4().int % 10**10:010d}"
    return (f"acceptance-{token}@example.com", f"+1999{phone_digits}")


# --- Phase 1: physical lead-isolation proof (substrate, no HTTP) -------------


def _tenant_pairs():
    """Yield every ordered (acting, other) tenant pair from the registry.

    The acting tenant's role is switched on; the other tenant's `leads` table is
    the one that must be physically out of reach.
    """
    for acting in TENANTS:
        for other in TENANTS:
            if other is not acting:
                yield acting, other


# Each denied statement aborts its own transaction, so every attempt runs in its
# own `engine.begin()` block: `SET LOCAL ROLE` resets when that transaction rolls
# back, exactly matching the production `SET LOCAL` pattern. Identifiers come only
# from the registry (never request input), interpolated verbatim — the same way
# the migrations build them.
def _denied_statements_against(other_schema: str) -> dict[str, str]:
    """Return the cross-tenant `leads` statements that must each be permission-denied.

    A minimal INSERT is enough: Postgres checks table privileges before it
    evaluates `NOT NULL` constraints, so the statement is denied before the
    (incomplete) row would ever be validated.
    """
    qualified_table = f"{other_schema}.leads"
    return {
        "SELECT": f"SELECT * FROM {qualified_table}",
        "UPDATE": f"UPDATE {qualified_table} SET first_name = 'breach attempt'",
        "INSERT": (
            f"INSERT INTO {qualified_table} (id, first_name, last_name) "
            "VALUES (gen_random_uuid(), 'breach', 'attempt')"
        ),
    }


@pytest.mark.asyncio
async def test_switched_tenant_role_is_denied_other_schema_leads(
    database_engine, container_keys_session_factory
):
    """Under `SET LOCAL ROLE tenant_<A>`, every write/read on `<B>.leads` is denied.

    For each ordered tenant pair, switch to the acting tenant's role and attempt a
    SELECT / UPDATE / INSERT against the *other* tenant's `leads` table. Each must
    raise a Postgres insufficient-privilege error (a SQLAlchemy `ProgrammingError`
    wrapping asyncpg's `InsufficientPrivilegeError`, surfacing as "permission
    denied"). This is the physical proof that the connection drops privileges under
    a switched role for the lead table — the `leads` analogue of
    `test_isolation_acceptance.py` Phase 1.
    """
    # `container_keys_session_factory` (requested as a fixture above) repoints the
    # `app.pii.keys` own-session global at the container, so `seed()`'s PII
    # encryption resolves per-tenant keys there rather than the unreachable eager
    # engine — without it this test fails when the file runs in isolation.
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    async with session_factory() as session:
        await seed(session)

    for acting, other in _tenant_pairs():
        for operation, statement in _denied_statements_against(
            other.schema_name
        ).items():
            # Each attempt gets its own transaction: the denial aborts it, and the
            # `SET LOCAL ROLE` resets as the block rolls back on the raised error.
            with pytest.raises(ProgrammingError) as denial:
                async with database_engine.begin() as connection:
                    await connection.execute(
                        text(f"SET LOCAL ROLE {acting.db_role}")
                    )
                    await connection.execute(text(statement))

            message = str(denial.value).lower()
            assert "permission denied" in message, (
                f"expected {acting.db_role} to be denied {operation} on "
                f"{other.schema_name}.leads, got: {message}"
            )


@pytest.mark.asyncio
async def test_switched_tenant_role_still_reads_own_schema_leads(
    database_engine, container_keys_session_factory
):
    """The same switched role reads its *own* `leads` — denial is isolation.

    Proves the per-tenant role is denied the other schema's `leads` because of
    isolation, not because the role is broken: under `SET LOCAL ROLE tenant_<A>`,
    a SELECT on `<A>.leads` succeeds (the seed inserts four leads per tenant, so a
    non-negative count comes back without error).
    """
    # `container_keys_session_factory` repoints the `app.pii.keys` own-session
    # global at the container so `seed()`'s PII encryption resolves keys there.
    session_factory = async_sessionmaker(database_engine, expire_on_commit=False)
    async with session_factory() as session:
        await seed(session)

    for tenant in TENANTS:
        async with database_engine.begin() as connection:
            await connection.execute(text(f"SET LOCAL ROLE {tenant.db_role}"))
            own_count = (
                await connection.execute(
                    text(f"SELECT count(*) FROM {tenant.schema_name}.leads")
                )
            ).scalar_one()
            assert own_count >= 0


# --- Phase 2: full lifecycle — public intake -> queue -> claim -> qualify -----


async def test_public_intake_through_claim_and_qualify_lifecycle(
    seeded, db_client, database_engine
):
    """ACCEPTANCE: a public lead is born `New`, queued, claimed, and qualified end-to-end.

    One thread on the real substrate: a public `POST /api/public/intake` returns
    the sanitized `{"ok": true}` and the stored row is born `New` / unowned /
    `public_form`. A Sunshine Agent sees that lead in the unassigned queue
    (`?unassigned=true`), claims it (→ `Working`, owned by the Agent, one
    `lead.assigned` outbox row), then qualifies it (→ `Qualified`, one
    `lead.qualified` outbox row). No supplied plaintext leaks into any masked
    response along the way.
    """
    email, phone = unique_public_contact()
    # Only the *encrypted*-PII plaintext must never appear unmasked: the email and
    # phone (both masked) and the street-address value (masked to `***`). `notes`,
    # names, `zip_code`, and the product-line keys are plaintext, non-PII columns
    # the masked read surfaces by design, so they are not leak candidates.
    encrypted_pii_plaintext = (email, phone, "200 Shopper Lane")

    intake_response = await db_client.post(
        "/api/public/intake", json=public_body_with(email=email, phone=phone)
    )
    assert intake_response.status_code == 200
    assert intake_response.json() == {"ok": True}

    # Born state (the sanitized response hides the id, so find the row by its email
    # blind index — exactly one Sunshine lead carries it).
    lead_id = await _only_lead_id_for_email(database_engine, email)
    born = await read_lead_row(database_engine, SUNSHINE.schema_name, lead_id)
    assert born.status == "New"
    assert born.lead_source == "public_form"
    assert born.owner_user_id is None
    assert born.owner_username is None

    login_response = await login_agent_for_slug(db_client, SUNSHINE.slug)
    assert login_response.status_code == 200
    agent = login_response.json()["user"]

    # The lead is on the unassigned queue (unowned + `New`).
    queue_response = await db_client.get(
        "/api/leads", params={"unassigned": "true"}
    )
    assert queue_response.status_code == 200
    queue_ids = {lead["id"] for lead in queue_response.json()["leads"]}
    assert str(lead_id) in queue_ids

    # Claim: New -> Working, owned by the Agent; one `lead.assigned` event.
    claim_response = await db_client.post(f"/api/leads/{lead_id}/claim")
    assert claim_response.status_code == 200
    claimed = claim_response.json()["lead"]
    assert claimed["status"] == "Working"
    assert claimed["owner_user_id"] == agent["id"]
    _assert_no_plaintext_leak(claim_response.text, encrypted_pii_plaintext)

    assigned_rows = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.LEAD_ASSIGNED, lead_id
    )
    assert len(assigned_rows) == 1

    # Qualify: Working -> Qualified; one `lead.qualified` event.
    qualify_response = await db_client.post(f"/api/leads/{lead_id}/qualify")
    assert qualify_response.status_code == 200
    assert qualify_response.json()["lead"]["status"] == "Qualified"
    _assert_no_plaintext_leak(qualify_response.text, encrypted_pii_plaintext)

    qualified_rows = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.LEAD_QUALIFIED, lead_id
    )
    assert len(qualified_rows) == 1


# --- Phase 3: agent born state + reject thread -------------------------------


async def test_agent_intake_born_working_then_reject_lifecycle(
    seeded, db_client, database_engine
):
    """ACCEPTANCE: an agent lead is born `Working`/owned, then rejected end-to-end.

    A Sunshine Agent's `POST /api/leads` returns 201 with the masked lead born
    `Working` / owned by the Agent / `agent_entered`, and one `lead.created` outbox
    row lands. Rejecting it (`Working → Rejected`) returns the masked `Rejected`
    lead and enqueues exactly one `lead.rejected` outbox row whose `reason_kind` is
    `qualify_reject` (this is the qualify/reject path, distinct from the
    duplicate-reject in Phase 4).
    """
    login_response = await login_as(db_client, Role.AGENT)
    assert login_response.status_code == 200
    agent = login_response.json()["user"]

    email, phone = unique_public_contact()
    create_response = await db_client.post(
        "/api/leads",
        json={
            "first_name": "Agent",
            "last_name": "Born",
            "email": email,
            "phone": phone,
            "date_of_birth": "1950-03-15",
            "zip_code": "33101",
            "product_lines_of_interest": ["medicare_advantage"],
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()["lead"]
    assert created["status"] == "Working"
    assert created["lead_source"] == "agent_entered"
    assert created["owner_user_id"] == agent["id"]
    lead_id = uuid.UUID(created["id"])

    created_rows = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.LEAD_CREATED, lead_id
    )
    assert len(created_rows) == 1

    # Reject: Working -> Rejected; one `lead.rejected` event, `qualify_reject`.
    reject_response = await db_client.post(
        f"/api/leads/{lead_id}/reject", json={"reason": "Not a fit after the call."}
    )
    assert reject_response.status_code == 200
    assert reject_response.json()["lead"]["status"] == "Rejected"

    rejected_rows = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.LEAD_REJECTED, lead_id
    )
    assert len(rejected_rows) == 1
    assert rejected_rows[0].payload == {
        "entity_id": str(lead_id),
        "reason_kind": "qualify_reject",
    }


# --- Phase 4: duplicate thread end-to-end, without decryption ----------------


async def test_duplicate_flagged_without_decryption_then_rejected(
    seeded, db_client, database_engine
):
    """ACCEPTANCE: the live intake endpoint flags a duplicate blindly, then resolves it.

    Two matching public posts share one identity. The first lands clean. For the
    second (flagging) post, `app.pii.service.decrypt_field` is patched to raise if
    called, so the post succeeding *and* the duplicate being flagged proves the
    endpoint matched on the blind index alone — endpoint-level, distinct from
    `test_lead_matching_db.py`'s unit-level proof. The second lead's
    `duplicate_of_lead_id` points at the first, exactly one
    `lead.duplicate_detected` event shares the second lead's `lead.created`
    correlation id, and resolving with `reject` (the flagged lead is `New` /
    `public_form`, so `New → Rejected` is legal) moves it to `Rejected` with
    `duplicate_resolution = "rejected"` and a `lead.rejected` `reason_kind =
    "duplicate"`.
    """
    email, phone = unique_public_contact()

    first = await db_client.post(
        "/api/public/intake", json=public_body_with(email=email, phone=phone)
    )
    assert first.status_code == 200
    assert first.json() == {"ok": True}

    # The flagging post must never decrypt: the matcher works on the blind index
    # alone, so a decrypt on the create path would be a regression. Patch the
    # canonical `decrypt_field` to raise (the create path imports nothing that
    # decrypts — `intake.py`/`matching.py` use only `compute_blind_index` /
    # `encrypt_field`), scoped to *just* the flagging post so any stray decrypt is
    # a loud failure. `mock.patch` (not the `monkeypatch` fixture) is used on
    # purpose: the conftest key/audit fixtures set their patches on the shared
    # per-test `monkeypatch`, so a `monkeypatch.undo()` here would also revert
    # those and break the later authenticated calls — `mock.patch`'s context
    # manager restores only this one patch on exit.
    async def _decrypt_is_forbidden(*args, **kwargs):
        raise AssertionError(
            "decrypt_field must not be called on the duplicate-flagging intake path"
        )

    with mock.patch(
        "app.pii.service.decrypt_field", new=_decrypt_is_forbidden
    ):
        second = await db_client.post(
            "/api/public/intake", json=public_body_with(email=email, phone=phone)
        )
    assert second.status_code == 200
    assert second.json() == {"ok": True}

    # The second (newer) lead carries the linkage to the first (older) — oldest wins.
    first_id, second_id = await _two_lead_ids_for_email_oldest_first(
        database_engine, email
    )
    second_row = await read_lead_row(
        database_engine, SUNSHINE.schema_name, second_id
    )
    assert second_row.duplicate_of_lead_id == first_id

    # Exactly one `lead.duplicate_detected`, sharing the `lead.created` trace id.
    duplicate_rows = await read_outbox_rows_for_entity(
        database_engine,
        SUNSHINE.schema_name,
        EventType.LEAD_DUPLICATE_DETECTED,
        second_id,
    )
    assert len(duplicate_rows) == 1
    assert duplicate_rows[0].payload == {
        "entity_id": str(second_id),
        "duplicate_of_lead_id": str(first_id),
    }
    created_rows = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.LEAD_CREATED, second_id
    )
    assert len(created_rows) == 1
    assert duplicate_rows[0].correlation_id == created_rows[0].correlation_id

    # Resolve the flag: reject the flagged `New` lead (the route owns New -> Rejected).
    login_response = await login_agent_for_slug(db_client, SUNSHINE.slug)
    assert login_response.status_code == 200

    resolve_response = await db_client.post(
        f"/api/leads/{second_id}/resolve-duplicate", json={"action": "reject"}
    )
    assert resolve_response.status_code == 200
    resolved = resolve_response.json()["lead"]
    assert resolved["status"] == "Rejected"
    assert resolved["duplicate_resolution"] == "rejected"

    rejected_rows = await read_outbox_rows_for_entity(
        database_engine, SUNSHINE.schema_name, EventType.LEAD_REJECTED, second_id
    )
    assert len(rejected_rows) == 1
    assert rejected_rows[0].payload == {
        "entity_id": str(second_id),
        "reason_kind": "duplicate",
    }


# --- Phase 5: abuse-control + HTTP-isolation summary -------------------------


async def test_public_abuse_controls_and_tenant_isolation_summary(
    seeded, db_client, database_engine
):
    """ACCEPTANCE (thin narrative): the public guards hold and tenants stay isolated.

    A compact summary, not the full `test_public_intake.py` matrix: a filled
    honeypot (`website`) → 200 `{"ok": true}` with nothing persisted; a sixth post
    from one IP within the window → 429; one validation 422 (a malformed email);
    and a thin A-vs-B re-statement — a known Sunshine lead is 404 on
    `GET /api/leads/{id}` and absent from `GET /api/leads` for a Florida Agent.
    """
    # Honeypot: a filled `website` evaporates — success-shaped, nothing persisted.
    honeypot_email, honeypot_phone = unique_public_contact()
    honeypot_response = await db_client.post(
        "/api/public/intake",
        json=public_body_with(
            email=honeypot_email,
            phone=honeypot_phone,
            website="http://spam.example",
        ),
    )
    assert honeypot_response.status_code == 200
    assert honeypot_response.json() == {"ok": True}
    assert await _only_or_zero_count(database_engine, honeypot_email) == 0

    # Rate limit: the sixth post from one IP within the window is 429. Key on an IP
    # unique to this test (the limiter is a shared module-level singleton).
    unique_ip = f"198.51.100.{uuid.uuid4().int % 200 + 1}"
    headers = {"X-Forwarded-For": unique_ip}
    for _ in range(5):
        email, phone = unique_public_contact()
        allowed = await db_client.post(
            "/api/public/intake",
            json=public_body_with(email=email, phone=phone),
            headers=headers,
        )
        assert allowed.status_code == 200
    email, phone = unique_public_contact()
    blocked = await db_client.post(
        "/api/public/intake",
        json=public_body_with(email=email, phone=phone),
        headers=headers,
    )
    assert blocked.status_code == 429

    # Validation: a malformed email → 422.
    _, valid_phone = unique_public_contact()
    malformed = await db_client.post(
        "/api/public/intake",
        json=public_body_with(email="not-an-email", phone=valid_phone),
    )
    assert malformed.status_code == 422

    # Tenant isolation: a Sunshine lead is invisible to a Florida Agent.
    sunshine_tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    sunshine_email, sunshine_phone = unique_public_contact()
    sunshine_lead_id = await insert_lead(
        database_engine,
        SUNSHINE.schema_name,
        sunshine_tenant_id,
        first_name=unique_marker(),
        email=sunshine_email,
        phone=sunshine_phone,
    )

    assert (await login_agent_for_slug(db_client, FLORIDA.slug)).status_code == 200
    detail_response = await db_client.get(f"/api/leads/{sunshine_lead_id}")
    assert detail_response.status_code == 404

    list_response = await db_client.get("/api/leads")
    assert list_response.status_code == 200
    florida_ids = {lead["id"] for lead in list_response.json()["leads"]}
    assert str(sunshine_lead_id) not in florida_ids


# --- Shared helpers -----------------------------------------------------------


def _assert_no_plaintext_leak(response_text: str, plaintext_values) -> None:
    """Assert no supplied plaintext value appears in a masked response body."""
    for plaintext in plaintext_values:
        assert plaintext not in response_text


async def _only_or_zero_count(database_engine, email) -> int:
    """Return how many Sunshine lead rows carry `email`'s blind index (0 expected).

    Reuses the public-intake suite's blind-index count idiom inline so the honeypot
    drop can prove **nothing** persisted without depending on a private helper's
    one-row assertion.
    """
    from app.pii.crypto import normalize_email
    from app.pii.service import compute_blind_index

    tenant_id = await tenant_id_for_slug(database_engine, SUNSHINE.slug)
    blind_index = await compute_blind_index(tenant_id, normalize_email(email))
    async with database_engine.connect() as connection:
        return (
            await connection.execute(
                text(
                    f"SELECT count(*) FROM {SUNSHINE.schema_name}.leads "
                    "WHERE email_blind_index = :blind_index"
                ),
                {"blind_index": blind_index},
            )
        ).scalar_one()
