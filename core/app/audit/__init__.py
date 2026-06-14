"""The audit package — the append-only audit spine for Phase P1.4.

`records.py` holds the pure, DB-free vocabulary (the `EventType` and `Outcome`
string enums) that every audit migration, service, and wiring epic shares, so
none of them can ever disagree on a spelling.

`service.py` holds `record_audit_event` — the single function every audited
action calls. It routes by `tenant_id` to the right store, opens its own session
as the `audit_writer` role, and writes one append-only record of names, never
values.
"""
