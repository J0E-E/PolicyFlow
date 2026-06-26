"""The `opportunities` package — the pipeline building blocks for Phase P2.2.

`state.py` holds the pure, DB-free opportunity stage machine: the
`OpportunityStage` string enum, the canonical forward spine, the
optional/anchor/terminal stage sets, and the `next_enabled_stage` /
`allowed_targets` / `assert_transition` functions that take a tenant's enabled
stage set so the logic stays pure. Later epics layer per-tenant config, the
stage endpoint, the Medicare gate, and the board UI on top of these blocks.

This first module is **pure data — no database, no I/O, no framework**, mirroring
`app.leads.state`. Freezing the stage machine here, and pinning it with
drift-asserting tests, keeps every later epic honest about the legal transitions.
"""
