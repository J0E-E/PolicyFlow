"""The transactional-outbox write seam — `enqueue_event`.

Phase P1.5's event bus rests on one guarantee: **an event is never lost relative
to the committed state that produced it.** The mechanism (frozen by the TDD §5.2
as the transactional outbox) is to write the event into a database table *in the
same transaction* as the state change — so the record and its event either both
land or both roll back, never one without the other.

Epic 1 froze the `EventEnvelope` (the data shape); Epic 2 stood up the per-tenant
`outbox` table and the `OutboxEvent` ORM model. This module adds the one small
write helper that ties them together: `enqueue_event(db, envelope)` maps an
envelope onto an `OutboxEvent` and inserts it with a single `db.add(...)` +
`await db.flush()`, mirroring the `create_record` insert idiom in
`app/pii_demo/router.py`.

Two properties make the write transactional and tenant-safe with no extra work:

- **It runs on the caller's *request* session** — the one `get_tenant_db`
  already opened with `async with db.begin()` and scoped with `SET LOCAL ROLE` +
  `SET LOCAL search_path`. So the helper deliberately does **not** commit: the
  request transaction owns commit/rollback, and that shared transaction is
  exactly what makes the event land or roll back with the state change. (Contrast
  the polling relay in Epic 5, which reads the outbox on its **own** session as
  the `outbox_relay` role.)
- **No schema interpolation is needed.** `OutboxEvent` is schema-less, so the
  active `search_path` resolves it into the caller's tenant schema automatically
  — the same reason `create_record`'s `PiiDemoRecord` insert lands in the right
  schema. The tenant role is INSERT-only on its own `outbox` (Epic 2's grant), so
  this is a pure INSERT with no read-back; `published_at` is left NULL for the
  relay to stamp later.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.events.envelope import EventEnvelope
from app.models.outbox_event import OutboxEvent


async def enqueue_event(db: AsyncSession, envelope: EventEnvelope) -> None:
    """Write one envelope into the caller's tenant outbox, on the request session.

    Maps the envelope's fields 1:1 onto an `OutboxEvent` and inserts it with a
    single `db.add(...)` + `await db.flush()` — the `create_record` idiom. The
    flush surfaces any INSERT error here at the call site rather than later at
    commit. The helper does **not** commit: it runs inside the request
    transaction `get_tenant_db` opened, so the event is committed (or rolled
    back) together with the state change that triggered it. `published_at` is
    left NULL for the Epic 5 relay to stamp once the event is published.

    Every column the INSERT writes is set client-side — including the envelope's
    own `occurred_at` — so SQLAlchemy emits a plain `INSERT` with **no
    `RETURNING`**. That matters here: the tenant role is INSERT-only on its own
    `outbox` (Epic 2's grant) and lacks SELECT, so a `RETURNING` to fetch a
    server-side default (the model's `now()` default for `occurred_at`) would be
    permission-denied. Writing the envelope's `occurred_at` is also the faithful
    mapping — the committed event carries the moment `build_envelope` stamped,
    not a separate DB-write time.
    """
    db.add(
        OutboxEvent(
            event_id=envelope.event_id,
            event_type=envelope.event_type,
            schema_version=envelope.schema_version,
            tenant_id=envelope.tenant_id,
            occurred_at=envelope.occurred_at,
            correlation_id=envelope.correlation_id,
            causation_id=envelope.causation_id,
            actor_user_id=envelope.actor_user_id,
            actor_role=envelope.actor_role,
            demo_session_id=envelope.demo_session_id,
            payload=envelope.payload,
        )
    )
    await db.flush()
