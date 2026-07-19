"""The derive-at-read *Renewal Due* overlay predicate, as a batch helper (P2.4).

A **baseline** policy (`demo_session_id IS NULL`) never takes the real `Active →
Renewal Due` status write, so it reads *Renewal Due* only when the caller's session
holds an `origin='renewal'` opportunity pointing at it (ADR 0005). Epic 6 inlined this
per-policy in `opportunities/router.py`; Epic 13 lifts it into this shared **set/batch**
helper so the household policy list can resolve every policy in one query (no N+1),
while `get_opportunity_policy` calls it with a one-element set.

The `origin='renewal'` qualifier is load-bearing: a `cross_sell` opportunity (Epic 13)
also sets `source_policy_id`, and must never lift the overlay.
"""

import uuid
from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.opportunity import Opportunity


async def renewal_due_policy_ids(
    db: AsyncSession,
    policy_ids: Collection[uuid.UUID],
    demo_session_id: uuid.UUID | None,
) -> set[uuid.UUID]:
    """Return which of `policy_ids` read *Renewal Due* via the caller's session overlay.

    A policy id is in the returned set when the caller's `demo_session_id` holds an
    `origin='renewal'` opportunity whose `source_policy_id` is that policy. Resolved in
    a **single** query over the whole set (no N+1). With no demo session, or no ids, the
    overlay can never fire — returns the empty set without a query.

    The caller decides which ids to pass: only **baseline** policies (`demo_session_id
    IS NULL`) are ever lifted by the overlay — a session-owned policy already carries its
    real stored status — so pass baseline policy ids here and flag each as
    `overlay_renewal_due = <id in returned set>`.
    """
    if demo_session_id is None or not policy_ids:
        return set()

    rows = await db.execute(
        select(Opportunity.source_policy_id).where(
            Opportunity.source_policy_id.in_(policy_ids),
            Opportunity.origin == "renewal",
            Opportunity.demo_session_id == demo_session_id,
        )
    )
    return {source_policy_id for (source_policy_id,) in rows.all()}
