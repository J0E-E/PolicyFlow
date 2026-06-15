"""The named reveal seam — `on_pii_revealed`, now filled in P1.4.

Every guarded reveal of a PII field (Epic 12's reveal endpoint) is a privileged
action that later phases observe: P1.4 (audit) is now filled here and P1.5 will
send the `pii.revealed` event. This module is the single, named place both of
those land. Epic 12 already `await`s `on_pii_revealed` on the reveal path, so
P1.4/P1.5 fill this one body — with zero call-site churn. As of P1.4 it writes
exactly one tenant-store `pii.revealed` audit record carrying the field **name**
only (never the revealed value); the P1.5 event still lands here later.

It mirrors the established `record_platform_read_for_audit` seam in
`app.tenancy.scoping`, filled in P1.4 Epic 6.

Tenant isolation: the audit record routes to the caller's own tenant schema via
`identity.tenant_id` (the reveal endpoint rides `get_tenant_db` and requires
`REVEAL_PII`, so the caller is always a real tenant) — the row can never cross a
tenant boundary, and it stores the field name only, so the audit trail itself
never leaks PII.

`Identity` is reused from its single source of truth (`app.auth.provider`) rather
than redeclared, exactly as `app.tenancy.scoping` does.
"""

import uuid

from ..audit.records import EventType, Outcome
from ..audit.service import record_audit_event
from ..auth.provider import Identity


async def on_pii_revealed(
    identity: Identity, entity_type: str, entity_id: uuid.UUID, field_name: str
) -> None:
    """The reveal seam for a guarded PII field reveal — now filled in P1.4.

    P1.4 (audit) is filled here and P1.5 (the `pii.revealed` event) lands here
    later. Epic 12's reveal endpoint already `await`s this on every successful
    reveal, so those phases only fill this body — no call site changes.

    It writes exactly one record to the **tenant store**: `identity.tenant_id`
    routes the row to that tenant's ``audit_records``, with `event_type`
    `pii.revealed`, the `entity_type`/`entity_id` of the revealed record, and
    `field_names=[field_name]` — the field **name** only, never the revealed
    value, so the audit trail does not itself leak PII. `identity.role` is a
    `Role` (a `StrEnum`/`str`), so the audit service binds it as-is. The write
    propagates on failure (strict), so a reveal can never proceed unaudited.
    """
    await record_audit_event(
        tenant_id=identity.tenant_id,
        actor_user_id=identity.user_id,
        actor_role=identity.role,
        event_type=EventType.PII_REVEALED,
        outcome=Outcome.SUCCESS,
        entity_type=entity_type,
        entity_id=entity_id,
        field_names=[field_name],
    )
