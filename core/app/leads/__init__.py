"""The `leads` package — the lead-lifecycle building blocks for Phase P1.7.

`state.py` holds the pure, DB-free lead vocabulary: the `LeadStatus` and
`LeadSource` string enums and the `assert_transition` guard that rejects any
status move outside the allowed set. Later epics layer persistence, masking,
duplicate matching, and the intake/action endpoints on top of these blocks.

This first module is **pure data — no database, no I/O, no framework.** Freezing
the status machine here, and pinning it with drift-asserting tests, keeps every
later epic (the claim/qualify/reject/resolve endpoints) honest about the legal
transitions.
"""
