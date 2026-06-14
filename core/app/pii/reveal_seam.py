"""The named reveal seam — `on_pii_revealed`, a no-op today.

Every guarded reveal of a PII field (Epic 12's reveal endpoint) is a privileged
action that later phases observe: P1.4 will write an audit record and P1.5 will
send the `pii.revealed` event. This module is the single, named place both of
those land. Epic 12 already `await`s `on_pii_revealed` on the reveal path, so
P1.4/P1.5 only fill this one body — with zero call-site churn. It deliberately
does nothing yet (writes no audit record, sends no event), so the reveal path
works today without an audit store or an event bus.

It mirrors the established `record_platform_read_for_audit` no-op seam in
`app.tenancy.scoping`.

Tenant isolation: this is a pure placeholder that touches no tenant data and no
database, so it cannot cross a tenant boundary. The tenant-scoping concerns
arrive together with the audit/event bodies in P1.4/P1.5.

`Identity` is reused from its single source of truth (`app.auth.provider`) rather
than redeclared, exactly as `app.tenancy.scoping` does.
"""

import uuid

from ..auth.provider import Identity


async def on_pii_revealed(
    identity: Identity, entity_type: str, entity_id: uuid.UUID, field_name: str
) -> None:
    """The reveal seam for a guarded PII field reveal — a no-op today.

    P1.4 (audit) and P1.5 (the `pii.revealed` event) land here. Epic 12's reveal
    endpoint already `await`s this on every successful reveal, so those phases only
    fill this body — no call site changes. It deliberately does nothing yet (writes
    no audit record, sends no event), so the reveal path works today without an
    audit store or an event bus.
    """
    return None
