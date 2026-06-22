"""The session visibility predicate for the shared-tenant read path.

In the demo, many visitors share one tenant schema, so a plain `SELECT` over
`leads` would let one visitor see another's rows. This module is the single place
that scopes a leads query to **what the caller is allowed to see**: the shared seed
baseline (`demo_session_id IS NULL`) plus the caller's own session rows
(`demo_session_id = :session_id`).

`visible_to_session(query, demo_session_id)` appends that `WHERE` clause to a
`leads` SELECT:

- a session id given ⇒ `demo_session_id IS NULL OR demo_session_id = :session_id`
  (seed ∪ the caller's own rows);
- `demo_session_id is None` (no demo cookie, or an expired/unknown one) ⇒ just
  `demo_session_id IS NULL` (seed-only — a non-demo or session-less caller sees the
  shared baseline and nothing visitor-private).

It is read-path only (list / queue / detail). The same isolation on the **write**
actions (claim / qualify / reject / resolve-duplicate) is Epic 5's.
"""

import uuid
from typing import Optional

from sqlalchemy import Select

from ..models.lead import Lead


def visible_to_session(
    query: Select, demo_session_id: Optional[uuid.UUID]
) -> Select:
    """Scope a `leads` SELECT to the seed baseline plus the caller's own session.

    Appends `demo_session_id IS NULL OR demo_session_id = :session_id` when a
    session id is given, or just `demo_session_id IS NULL` (seed-only) when it is
    `None` — so a caller without a live demo session sees only the shared seed rows,
    never another visitor's. The returned query is the input with the predicate
    added; the caller's existing `WHERE` / ordering / limit are preserved.
    """
    if demo_session_id is None:
        return query.where(Lead.demo_session_id.is_(None))

    return query.where(
        (Lead.demo_session_id.is_(None))
        | (Lead.demo_session_id == demo_session_id)
    )
