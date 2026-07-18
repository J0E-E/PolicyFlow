"""Renewal generation (P2.4) — the post-policy renewal domain.

`rules.py` holds the pure, clock-free/DB-free renewal predicates that decide
*whether* and *when* a policy renews: the AEP-window and rolling-anniversary
checks, the renewal deadline per rule, and the idempotency cycle key. The rules
are the single source of truth the later generation core (Epic 4) reads; keeping
them clock-free and DB-free lets the unit tests pin every boundary directly.
"""
