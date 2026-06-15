"""The events package — the frozen event-bus contract for Phase P1.5.

`catalog.py` holds the pure, DB-free vocabulary (the `EventType` string enum, the
`SCHEMA_VERSION`, and the consumer→binding registry) that every later P1.5 epic —
and M3's real sidecars — share, so none of them can ever disagree on an event name
or a routing key.

`envelope.py` holds the `EventEnvelope` shape, its `build_envelope` builder, and the
JSON serialize/parse for the broker body. Every envelope carries a `tenant_id` so
later epics route by it, and its `payload` is an entity reference plus **non-PII**
fields by contract — never a PII snapshot or a revealed value.

This package is **pure data — no database, no I/O.** Freezing the contract here, and
pinning it with drift-asserting tests, is what de-risks the stub→real swap: the
envelope and routing keys cannot silently change out from under M3.
"""
