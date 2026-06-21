"""The event envelope — the JSON shape every bus event carries, plus its builder.

Phase P1.5 freezes one envelope every published event wraps: a stable set of
fields (who/what/when/which-tenant/correlation) around a non-PII `payload`.
`build_envelope` mints the identity/timestamp fields a fresh event needs, and
`to_message_body` / `from_message_body` are the JSON serialize/parse the broker
body uses.

**Confirmed wire-format decision (P1.5 planning):** the JSON body is **flat,
mirroring this dataclass 1:1** — UUIDs serialize as canonical hyphenated strings
(`str(uuid)`), timestamps as ISO-8601 with the UTC offset (`.isoformat()`), absent
optionals as JSON `null`, and the actor stays two flat sibling fields
(`actor_user_id` / `actor_role`; both `null` ⇒ system actor). No nested `actor`
object. This matches the existing codebase serialization convention and keeps wire
== dataclass == future outbox columns.

This module is **pure data — no database, no I/O.** Every envelope carries a
`tenant_id` so later epics route by it, and the `payload` is an entity reference
plus **non-PII** fields by contract — never a PII snapshot or a revealed value.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from app.events.catalog import SCHEMA_VERSION

__all__ = [
    "EventEnvelope",
    "build_envelope",
    "to_message_body",
    "from_message_body",
]


@dataclass(frozen=True)
class EventEnvelope:
    """The immutable shape every bus event carries (TDD §5.3).

    Frozen so an envelope cannot change after it is built, and so two envelopes
    with identical fields compare equal — the round-trip test relies on that
    generated `__eq__`. The actor is two flat sibling fields: both `None` means a
    system actor (no human behind the action). `demo_session_id` is always `None`
    until P1.8 owns it (Decision 11).
    """

    event_id: uuid.UUID
    event_type: str
    schema_version: int
    tenant_id: uuid.UUID
    occurred_at: datetime
    correlation_id: uuid.UUID
    causation_id: uuid.UUID | None
    actor_user_id: uuid.UUID | None
    actor_role: str | None
    demo_session_id: uuid.UUID | None
    payload: dict


def build_envelope(
    *,
    event_type: str,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    actor_role: str | None,
    payload: dict,
    correlation_id: uuid.UUID | None = None,
    causation_id: uuid.UUID | None = None,
    demo_session_id: uuid.UUID | None = None,
) -> EventEnvelope:
    """Build a fresh envelope, minting the identity and timestamp fields.

    Mints a new `event_id`; stamps the frozen `schema_version` and a
    timezone-aware UTC `occurred_at`; mints a **fresh** `correlation_id` when none
    is passed (a new flow) and preserves one that is supplied (so a flow's events
    share it). `causation_id` defaults to `None`. `demo_session_id` defaults to
    `None` and carries the demo-visit session id when the caller is on a tagged
    path (P1.8 owns it, Decision 11).
    """
    return EventEnvelope(
        event_id=uuid.uuid4(),
        event_type=event_type,
        schema_version=SCHEMA_VERSION,
        tenant_id=tenant_id,
        occurred_at=datetime.now(timezone.utc),
        correlation_id=correlation_id if correlation_id is not None else uuid.uuid4(),
        causation_id=causation_id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        demo_session_id=demo_session_id,
        payload=payload,
    )


def to_message_body(envelope: EventEnvelope) -> bytes:
    """Serialize an envelope to the flat JSON broker body as UTF-8 bytes.

    The dict mirrors the dataclass field names 1:1 (flat — no nested `actor`).
    UUIDs become canonical strings via `str(...)`, `occurred_at` becomes an
    ISO-8601 string via `.isoformat()`, and any absent optional stays JSON `null`.
    """
    body = {
        "event_id": str(envelope.event_id),
        "event_type": envelope.event_type,
        "schema_version": envelope.schema_version,
        "tenant_id": str(envelope.tenant_id),
        "occurred_at": envelope.occurred_at.isoformat(),
        "correlation_id": str(envelope.correlation_id),
        "causation_id": str(envelope.causation_id) if envelope.causation_id is not None else None,
        "actor_user_id": str(envelope.actor_user_id) if envelope.actor_user_id is not None else None,
        "actor_role": envelope.actor_role,
        "demo_session_id": str(envelope.demo_session_id) if envelope.demo_session_id is not None else None,
        "payload": envelope.payload,
    }
    return json.dumps(body).encode("utf-8")


def from_message_body(body: bytes) -> EventEnvelope:
    """Parse a flat JSON broker body back into an `EventEnvelope`.

    The inverse of `to_message_body`: UUID strings parse back via `uuid.UUID(...)`,
    `occurred_at` via `datetime.fromisoformat(...)`, and every optional is
    None-safe (a JSON `null` stays `None`). Round-trips to an equal envelope.
    """
    fields = json.loads(body)
    causation_id = fields["causation_id"]
    actor_user_id = fields["actor_user_id"]
    demo_session_id = fields["demo_session_id"]
    return EventEnvelope(
        event_id=uuid.UUID(fields["event_id"]),
        event_type=fields["event_type"],
        schema_version=fields["schema_version"],
        tenant_id=uuid.UUID(fields["tenant_id"]),
        occurred_at=datetime.fromisoformat(fields["occurred_at"]),
        correlation_id=uuid.UUID(fields["correlation_id"]),
        causation_id=uuid.UUID(causation_id) if causation_id is not None else None,
        actor_user_id=uuid.UUID(actor_user_id) if actor_user_id is not None else None,
        actor_role=fields["actor_role"],
        demo_session_id=uuid.UUID(demo_session_id) if demo_session_id is not None else None,
        payload=fields["payload"],
    )
