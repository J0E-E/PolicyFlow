"""The audit package — the append-only audit spine for Phase P1.4.

`records.py` holds the pure, DB-free vocabulary (the `EventType` and `Outcome`
string enums) that every audit migration, service, and wiring epic shares, so
none of them can ever disagree on a spelling.
"""
