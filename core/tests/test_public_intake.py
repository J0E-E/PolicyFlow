"""DB-backed proof of the unauthenticated public lead-intake route (Epic 10, P1.7).

Epic 7 built the authenticated agent intake and the shared `create_lead` core;
Epics 8/9 added the public tenant-scoping seam and the per-IP rate limiter. Epic 10
is the public front door: the **unauthenticated** `POST /api/public/intake` that
rate-limits and honeypot-checks, validates strictly, scopes to a tenant by slug,
creates a lead (born `New`, unowned, `public_form`), runs the matcher, publishes
`lead.created` (plus `lead.duplicate_detected` on a match), and returns a sanitized
`{"ok": true}` that never leaks the lead or any matched-lead data.

This drives that create over the same `seeded` + `db_client` substrate the agent
intake test uses, but **without logging in** — the route has no session. It reads
the stored row back through the SELECT-capable superuser `database_engine`
(schema-qualified — the tenant role is INSERT-only on its own `outbox`), reusing the
read/body helpers from `test_lead_intake.py` by import so the two intake suites share
one source of truth for how a lead row and outbox row are read. It proves:

- **Happy path** — a valid post → 200 with the body **exactly** `{"ok": true}`; the
  stored row is born `New` / `public_form` / unowned, with a non-null `correlation_id`.
- **Sanitized response** — the 200 body carries no lead id and no masked fields,
  even when a duplicate is matched.
- **Honeypot drop** — a filled `website` → 200 `{"ok": true}` with **nothing**
  persisted and **no** outbox row (the submission silently evaporated).
- **Rate-limit 429** — the sixth post from one IP within the window → 429.
- **Validation 422s** — a representative spread of malformed bodies.
- **Unknown slug 404** — a slug that maps to no tenant → 404.
- **Duplicate still fires** — two matching posts flag `duplicate_of_lead_id` and
  enqueue `lead.duplicate_detected`, yet the response is still `{"ok": true}`.

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no
`@pytest.mark.asyncio` decorator. The `seeded` fixture is reused by name from
`test_endpoints_db.py`; the row/outbox read helpers and `unique_contact` from
`test_lead_intake.py`.
"""

import uuid

from sqlalchemy import text

from app.events.catalog import EventType
from app.tenancy.registry import SUNSHINE

from tests.test_endpoints_db import seeded  # noqa: F401
from tests.test_lead_intake import (
    read_lead_row,
    read_outbox_rows_for_entity,
)


def unique_contact() -> tuple[str, str]:
    """Return an (email, phone) pair unique to one test and **strictly valid**.

    The container database is shared across the session, so a test that controls
    whether a duplicate is found owns its match targets by suffixing both fields with
    a random token — no other test's (or the seed's) leads can fingerprint the same.

    Unlike `test_lead_intake.unique_contact`, the phone is built from a **numeric**
    token so its digit-only fold lands in the public route's strict 10–15-digit range
    (`+1 (415) 555-XXXX` → eleven digits). The agent route's lenient `CreateLeadRequest`
    tolerates a non-numeric suffix; the public route's `PublicIntakeRequest` does not.
    """
    token = uuid.uuid4().hex[:12]
    digits = f"{uuid.uuid4().int % 10000:04d}"
    return (f"intake-{token}@example.com", f"+1 (415) 555-{digits}")

# A full valid public-intake body the happy-path tests reuse. The product-line keys
# are real Sunshine keys, the zip is US-shaped, the date of birth lands in the `65+`
# band, and there is **no** `website` (the honeypot is left blank, as a human would).
# Per-test runs override `email` / `phone` with `unique_contact()` so the shared,
# never-reset container DB cannot cross-match between tests.
FULL_PUBLIC_BODY = {
    "tenant_slug": SUNSHINE.slug,
    "first_name": "Pat",
    "last_name": "Shopper",
    "email": "pat.shopper@example.com",
    "phone": "+1 (415) 555-9876",
    "date_of_birth": "1950-03-15",
    "zip_code": "33101",
    "product_lines_of_interest": ["medicare_advantage", "final_expense"],
    "street_address": "200 Shopper Lane",
    "preferred_contact_method": "email",
    "notes": "Saw the ad online.",
}


def public_body_with(**overrides) -> dict:
    """Return a copy of `FULL_PUBLIC_BODY` with `overrides` applied.

    A fresh dict per call so a test never mutates the shared body. Tests that need a
    distinct lead (so the shared container DB cannot cross-match) pass a unique
    `email` / `phone`; tests of a specific failure override the offending field.
    """
    body = dict(FULL_PUBLIC_BODY)
    body.update(overrides)
    return body


# --- Phase 1: happy path — sanitized body + born state -----------------------


async def test_public_intake_returns_ok_and_persists_new_public_lead(
    seeded, db_client, database_engine
):
    """A valid public post → 200 `{"ok": true}`, a born-`New` row, and an auto-mint.

    The post carries no `pf_demo_session` cookie, so the route auto-mints a demo
    session (Epic 3): the response sets the cookie and the stored row is tagged with
    the minted session id. The body is still **exactly** `{"ok": true}` — never the
    masked lead. The stored row is born `New` / `public_form` / unowned
    (`owner_user_id` and `owner_username` both NULL) with a non-null `correlation_id`.
    """
    email, phone = unique_contact()
    response = await db_client.post(
        "/api/public/intake", json=public_body_with(email=email, phone=phone)
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}

    # The no-cookie post auto-minted a session: the response set the cookie to the
    # raw id, and that id names a real `platform.demo_sessions` row.
    minted_id = uuid.UUID(response.cookies["pf_demo_session"])
    assert await _demo_session_exists(database_engine, minted_id)

    # The sanitized response carries no id, so find the new row by its unique blind
    # index via the email — read the single Sunshine lead matching this test's email.
    created_id = await _only_lead_id_for_email(database_engine, email)
    row = await read_lead_row(database_engine, SUNSHINE.schema_name, created_id)
    assert row.status == "New"
    assert row.lead_source == "public_form"
    assert row.owner_user_id is None
    assert row.owner_username is None
    assert row.correlation_id is not None
    # The lead carries the session the response just minted.
    assert row.demo_session_id == minted_id


async def test_second_public_post_carrying_the_cookie_reuses_the_session(
    seeded, db_client, database_engine
):
    """A second post carrying the first's cookie reuses the session — no new mint.

    `db_client`'s cookie jar persists the `pf_demo_session` the first post set, so the
    second post arrives with it. The route reuses that live session: no new
    `platform.demo_sessions` row is minted and the second lead carries the **same**
    `demo_session_id` as the first.
    """
    first_email, first_phone = unique_contact()
    first = await db_client.post(
        "/api/public/intake",
        json=public_body_with(email=first_email, phone=first_phone),
    )
    assert first.status_code == 200
    session_id = uuid.UUID(first.cookies["pf_demo_session"])
    sessions_before = await _demo_session_count(database_engine)

    # The jar carries the cookie into the second post automatically.
    second_email, second_phone = unique_contact()
    second = await db_client.post(
        "/api/public/intake",
        json=public_body_with(email=second_email, phone=second_phone),
    )
    assert second.status_code == 200

    # Reuse, not re-mint: the row count is unchanged, and the jar still names the
    # same session.
    assert await _demo_session_count(database_engine) == sessions_before
    assert uuid.UUID(db_client.cookies["pf_demo_session"]) == session_id

    # Both leads carry the one shared session id.
    first_id = await _only_lead_id_for_email(database_engine, first_email)
    second_id = await _only_lead_id_for_email(database_engine, second_email)
    first_row = await read_lead_row(database_engine, SUNSHINE.schema_name, first_id)
    second_row = await read_lead_row(database_engine, SUNSHINE.schema_name, second_id)
    assert first_row.demo_session_id == session_id
    assert second_row.demo_session_id == session_id


async def test_public_intake_response_is_sanitized_even_on_a_duplicate(
    seeded, db_client
):
    """The 200 body is exactly `{"ok": true}` — no lead id, no masked fields.

    Two matching public posts: the second is matched as a duplicate, yet its response
    body is still the flat sanitized shape — no `lead`, no `id`, no masked PII, no
    `duplicate_of_lead_id`. The public surface leaks nothing about the lead or its match.
    """
    email, phone = unique_contact()
    first = await db_client.post(
        "/api/public/intake", json=public_body_with(email=email, phone=phone)
    )
    assert first.status_code == 200
    assert first.json() == {"ok": True}

    second = await db_client.post(
        "/api/public/intake", json=public_body_with(email=email, phone=phone)
    )
    assert second.status_code == 200
    # Exactly the sanitized shape — and nothing else — even though a match was found.
    assert second.json() == {"ok": True}


# --- Phase 2: the honeypot drop ----------------------------------------------


async def test_filled_honeypot_drops_silently_with_no_lead_or_event(
    seeded, db_client, database_engine
):
    """A filled `website` → 200 `{"ok": true}`, with no lead row and no outbox row.

    The honeypot: a hidden field a human leaves blank but a bot fills. A non-empty
    `website` drops the submission with the same success-shaped body the real path
    returns, so a bot cannot tell — and **nothing** lands: no lead row carries this
    test's email and no `lead.created` outbox row was enqueued.
    """
    email, phone = unique_contact()
    response = await db_client.post(
        "/api/public/intake",
        json=public_body_with(
            email=email, phone=phone, website="http://spam.example"
        ),
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}

    # Nothing persisted: no Sunshine lead row carries this test's unique email.
    assert await _lead_count_for_email(database_engine, email) == 0


# --- Phase 3: the rate limit -------------------------------------------------


async def test_sixth_request_from_one_ip_in_the_window_is_429(seeded, db_client):
    """The sixth post from one IP within the window → 429 (the default 5/60s limit).

    The module-level limiter is shared across the whole process, so this test keys on
    an IP **unique to it** (a random last octet) — otherwise its five allowed hits
    could be spent by another test's traffic and cross-contaminate. The first five
    posts from that IP are allowed (200); the sixth is rate-limited (429).
    """
    unique_ip = f"203.0.113.{uuid.uuid4().int % 200 + 1}"
    headers = {"X-Forwarded-For": unique_ip}

    for _ in range(5):
        email, phone = unique_contact()
        allowed = await db_client.post(
            "/api/public/intake",
            json=public_body_with(email=email, phone=phone),
            headers=headers,
        )
        assert allowed.status_code == 200

    email, phone = unique_contact()
    blocked = await db_client.post(
        "/api/public/intake",
        json=public_body_with(email=email, phone=phone),
        headers=headers,
    )
    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "rate limit exceeded"}


# --- Phase 4: strict validation ----------------------------------------------


async def test_malformed_email_is_422(seeded, db_client):
    """An email with no `@` → 422 (the light email-shape check)."""
    _, phone = unique_contact()
    response = await db_client.post(
        "/api/public/intake",
        json=public_body_with(email="not-an-email", phone=phone),
    )
    assert response.status_code == 422


async def test_bad_zip_is_422(seeded, db_client):
    """A zip that is not 5 digits / ZIP+4 → 422."""
    email, phone = unique_contact()
    response = await db_client.post(
        "/api/public/intake",
        json=public_body_with(email=email, phone=phone, zip_code="3310"),
    )
    assert response.status_code == 422


async def test_future_date_of_birth_is_422(seeded, db_client):
    """A date of birth in the future → 422 (must be strictly in the past)."""
    email, phone = unique_contact()
    response = await db_client.post(
        "/api/public/intake",
        json=public_body_with(email=email, phone=phone, date_of_birth="2999-01-01"),
    )
    assert response.status_code == 422


async def test_empty_product_lines_is_422(seeded, db_client):
    """An empty `product_lines_of_interest` list → 422 (the ≥1 rule)."""
    email, phone = unique_contact()
    response = await db_client.post(
        "/api/public/intake",
        json=public_body_with(
            email=email, phone=phone, product_lines_of_interest=[]
        ),
    )
    assert response.status_code == 422


async def test_unknown_product_line_key_is_422(seeded, db_client):
    """A product-line key the named tenant does not offer → 422 (route key check).

    `not_a_real_line` is not a Sunshine key, so the route's tenant-aware membership
    check rejects it after the slug resolves but before any lead is written.
    """
    email, phone = unique_contact()
    response = await db_client.post(
        "/api/public/intake",
        json=public_body_with(
            email=email,
            phone=phone,
            product_lines_of_interest=["medicare_advantage", "not_a_real_line"],
        ),
    )
    assert response.status_code == 422


async def test_over_cap_field_is_422(seeded, db_client):
    """A field over its length cap → 422 (the `notes` cap is 1000 characters)."""
    email, phone = unique_contact()
    response = await db_client.post(
        "/api/public/intake",
        json=public_body_with(email=email, phone=phone, notes="x" * 1001),
    )
    assert response.status_code == 422


# --- Phase 5: unknown slug ----------------------------------------------------


async def test_unknown_tenant_slug_is_404(seeded, db_client):
    """A slug that maps to no tenant → 404 (no honeypot, a real post otherwise)."""
    email, phone = unique_contact()
    response = await db_client.post(
        "/api/public/intake",
        json=public_body_with(
            tenant_slug="no-such-tenant", email=email, phone=phone
        ),
    )
    assert response.status_code == 404


# --- Phase 6: the duplicate path still fires ---------------------------------


async def test_second_matching_public_post_flags_duplicate_and_enqueues_event(
    seeded, db_client, database_engine
):
    """A second matching public post flags the duplicate and enqueues its event.

    Two public posts sharing the same email/phone: the first lands cleanly; the second
    is matched against it, so the second lead's `duplicate_of_lead_id` is set to the
    first lead's id and a single `lead.duplicate_detected` event is enqueued — yet the
    second response is still the sanitized `{"ok": true}`, leaking none of that.
    """
    email, phone = unique_contact()
    first = await db_client.post(
        "/api/public/intake", json=public_body_with(email=email, phone=phone)
    )
    assert first.status_code == 200
    assert first.json() == {"ok": True}

    second = await db_client.post(
        "/api/public/intake", json=public_body_with(email=email, phone=phone)
    )
    assert second.status_code == 200
    assert second.json() == {"ok": True}

    # The two leads share an email; the second (newer) one carries the linkage to the
    # first (older) one — oldest wins, matching the create core's matcher semantics.
    first_id, second_id = await _two_lead_ids_for_email_oldest_first(
        database_engine, email
    )
    second_row = await read_lead_row(
        database_engine, SUNSHINE.schema_name, second_id
    )
    assert second_row.duplicate_of_lead_id == first_id

    # Exactly one `lead.duplicate_detected` event for the second lead, naming the match.
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


# --- Read helpers: find rows by email when the response hides the id ----------


async def _lead_count_for_email(database_engine, email):
    """Return how many Sunshine lead rows carry `email`'s blind index.

    The sanitized response never returns an id, so a row is found by the deterministic
    blind index of its normalized email — the same fingerprint the create core stores.
    Reads through the SELECT-capable superuser engine, schema-qualified.
    """
    from app.pii.crypto import normalize_email
    from app.pii.service import compute_blind_index

    tenant_id = await _sunshine_tenant_id(database_engine)
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


async def _only_lead_id_for_email(database_engine, email):
    """Return the id of the single Sunshine lead row carrying `email`'s blind index.

    Asserts exactly one match so a happy-path test reads back the row it just created.
    """
    ids = await _lead_ids_for_email_oldest_first(database_engine, email)
    assert len(ids) == 1
    return ids[0]


async def _two_lead_ids_for_email_oldest_first(database_engine, email):
    """Return `(older_id, newer_id)` for the two Sunshine leads sharing `email`."""
    ids = await _lead_ids_for_email_oldest_first(database_engine, email)
    assert len(ids) == 2
    return ids[0], ids[1]


async def _lead_ids_for_email_oldest_first(database_engine, email):
    """Return the ids of Sunshine leads carrying `email`'s blind index, oldest first.

    Ordered by `created_at` then `id` — the same oldest-wins ordering the matcher
    uses — so the duplicate test can name the older lead as the match target.
    """
    from app.pii.crypto import normalize_email
    from app.pii.service import compute_blind_index

    tenant_id = await _sunshine_tenant_id(database_engine)
    blind_index = await compute_blind_index(tenant_id, normalize_email(email))
    async with database_engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    f"SELECT id FROM {SUNSHINE.schema_name}.leads "
                    "WHERE email_blind_index = :blind_index "
                    "ORDER BY created_at, id"
                ),
                {"blind_index": blind_index},
            )
        ).all()
    return [row.id for row in rows]


async def _sunshine_tenant_id(database_engine):
    """Return the Sunshine tenant's UUID from `platform.tenants`.

    The blind index is tenant-scoped (it folds the tenant's index key in), so finding
    a row by email blind index needs the same `tenant_id` the create path used.
    """
    async with database_engine.connect() as connection:
        return (
            await connection.execute(
                text("SELECT id FROM platform.tenants WHERE slug = :slug"),
                {"slug": SUNSHINE.slug},
            )
        ).scalar_one()


async def _demo_session_exists(database_engine, session_id) -> bool:
    """Whether a `platform.demo_sessions` row with `session_id` exists.

    Reads through the SELECT-capable superuser engine, schema-qualified, matching the
    other platform reads above — the route auto-mints on the login-role session.
    """
    async with database_engine.connect() as connection:
        return (
            await connection.execute(
                text(
                    "SELECT count(*) FROM platform.demo_sessions WHERE id = :id"
                ),
                {"id": session_id},
            )
        ).scalar_one() == 1


async def _demo_session_count(database_engine) -> int:
    """Return the total number of `platform.demo_sessions` rows.

    The container DB is shared and never reset, so a reuse test asserts the count is
    **unchanged** across a second post rather than any absolute value.
    """
    async with database_engine.connect() as connection:
        return (
            await connection.execute(
                text("SELECT count(*) FROM platform.demo_sessions")
            )
        ).scalar_one()
