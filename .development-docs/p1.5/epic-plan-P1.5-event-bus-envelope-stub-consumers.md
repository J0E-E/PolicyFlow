# P1.5 — Event bus + envelope + stub consumers — Epic Plan

Source TDD: [./tdd-P1.5-event-bus-envelope-stub-consumers.md](./tdd-P1.5-event-bus-envelope-stub-consumers.md)

> **Review budget:** ~150 changed lines · ~8 non-generated files · one focused commit per epic. Tunable per project. (Migrations, config, and compose edits are mechanical boilerplate and don't count toward the line budget.)

> High-level agile roadmap. Each epic's design specifics are confirmed with stakeholders at epic time (`4-plan-epic`) before any code is written.

This phase is **backend-only** — no UI epics. The user-facing demo shell is P1.6; the
per-record event timeline that reads this phase's `processed_events` is P1.9. Epics are
ordered simplest-first: the frozen contract, then storage, then the publish side, then
the bus, then the consumers, then runtime wiring, then the two real triggers, then
observability, and finally the named acceptance proof. Each epic leaves the mainline
running when merged — the bus simply sits idle until the triggers (Epics 8–9) feed it.

## Epic 1 — Event vocabulary + envelope (pure data) — **COMPLETED**
- **Goal:** Freeze the contract every later phase honors — the P1.5 subset of the event catalog (`record.created`, `pii.revealed`, schema version, the consumer→binding registry) and the event envelope with a builder and JSON round-trip — as pure data with no I/O.
- **Rough scope:** A new events vocabulary module and an envelope module under `core/app/events/`, plus unit tests that assert the vocabulary against a hand-written expectation (the `audit/records.py` precedent) and round-trip the envelope through serialize/parse.
- **Open questions / decisions for stakeholders:** Confirm the JSON wire format for the body (how UUIDs and timestamps serialize) so it stays stable for M3 — minor; otherwise none expected.
- **Depends on:** none.
- **Implementation notes:**
  - **JSON wire format confirmed FLAT, mirroring `EventEnvelope` 1:1.** UUIDs serialize as canonical hyphenated strings (`str(...)`), `occurred_at` as ISO-8601 with the UTC offset (`.isoformat()`), absent optionals as JSON `null`, and the actor stays two flat sibling fields (`actor_user_id` / `actor_role`; both `null` ⇒ system actor) — no nested `actor` object. Keeps wire == dataclass == future outbox columns; matches the existing codebase serialization convention.
  - Created `core/app/events/` (new package): `__init__.py`, `catalog.py` (`EventType` `StrEnum`, `SCHEMA_VERSION = 1`, the frozen `ConsumerBinding` dataclass + `CONSUMER_BINDINGS` registry, `ENRICHMENT_STUB` / `SYNC_LOGGER` name constants), and `envelope.py` (`EventEnvelope` frozen dataclass, `build_envelope`, `to_message_body` / `from_message_body`). Mirrors the `audit/records.py` pure-data precedent.
  - Tests `tests/test_event_catalog.py` and `tests/test_event_envelope.py` use the independent-hand-written-expectation style (`test_audit_records.py`): exact member/binding sets cross-checked vs the TDD §5.3 spec, plus envelope builder/round-trip/wire-shape asserts. 22 tests pass under the project venv; pure sync, no DB/Docker.
  - No diagram (pure-data, non-visual — diagram offer skipped per `0-conventions`).

## Epic 2 — Migration `0008` + ORM models
- **Goal:** Add the per-tenant `outbox` and `processed_events` tables to every tenant schema, plus the dedicated `outbox_relay` and `event_consumer` roles with tight grants/REVOKEs (the `0007` precedent), and the matching schema-less ORM models.
- **Rough scope:** One additive Alembic migration iterating the tenant registry, two drift-excluded ORM twins registered with the models package, and a substrate test that applies the migration, confirms `alembic check` stays drift-clean, and round-trips `0008` down/up.
- **Open questions / decisions for stakeholders:** Confirm the index/constraint shape (relay's partial index on unpublished rows; the `(consumer_name, event_id)` dedup unique) reads as intended — the TDD specifies it; settle any naming at epic time.
- **Depends on:** Epic 1.
- **Implementation notes:** _none yet_

## Epic 3 — Transactional enqueue
- **Goal:** Provide the transactional outbox write — an `enqueue_event` that inserts the envelope into the caller's tenant `outbox` on the request session, inside the request transaction, so an event is never lost relative to the committed state that produced it.
- **Rough scope:** A small enqueue helper in the events package, with a DB test proving the row is present on commit and gone on rollback, plus per-tenant isolation (tenant A's role cannot read B's outbox).
- **Open questions / decisions for stakeholders:** none expected.
- **Depends on:** Epic 2.
- **Implementation notes:** _none yet_

## Epic 4 — Broker topology + publish
- **Goal:** Declare the RabbitMQ topology (one durable topic exchange, per-consumer durable queues, per-queue DLX→DLQ with the documented bindings) and publish an envelope to it with the AMQP properties the contract specifies (persistent, `message_id`/`correlation_id`/`tenant_id`).
- **Rough scope:** A broker module under the events package; a unit test asserting the declared bindings as data; the first RabbitMQ testcontainer test that a published envelope lands in its bound queues (adds the `testcontainers[rabbitmq]` dev dependency).
- **Open questions / decisions for stakeholders:** Confirm the aio-pika connection/channel lifecycle (single shared connection vs per-task channel) — settle at epic time; the rest is frozen in the TDD.
- **Depends on:** Epic 1.
- **Implementation notes:** _none yet_

## Epic 5 — Polling relay
- **Goal:** Stand up the own-session polling relay (as `outbox_relay`) that sweeps each tenant's unpublished outbox rows, publishes each to the exchange, and marks `published_at` — with at-least-once semantics by design (a crash between publish and mark re-publishes next sweep).
- **Rough scope:** A relay module exposing a single-sweep function and a loop; a DB+broker test that enqueue → sweep lands the message and marks the row published, that only unpublished rows are selected, and that a forced "published-but-not-marked" row re-publishes on the next sweep.
- **Open questions / decisions for stakeholders:** Confirm the default poll interval (TDD suggests ~1s) and whether a sweep batches or drains fully — tuning only.
- **Depends on:** Epic 3, Epic 4.
- **Implementation notes:** _none yet_

## Epic 6 — Idempotent stub consumers
- **Goal:** Add the two terminal stub handlers (enrichment, sync-logger) that dedupe on `(consumer_name, event_id)` via `processed_events` (own session, `event_consumer`, routed by `tenant_id`), run a canned effect + structured non-PII log, ack on success, and nack-without-requeue to the DLQ on error.
- **Rough scope:** A consumers module under the events package; tests that a consume writes exactly one `processed_events` row, that redelivery of the same `event_id` is idempotent (still one effect), and that a poison message dead-letters.
- **Open questions / decisions for stakeholders:** Confirm the canned-effect shape (what the enrichment stub "returns"/logs) so it stays recognizably non-PII — minor.
- **Depends on:** Epic 2, Epic 4.
- **Implementation notes:** _none yet_

## Epic 7 — Lifespan wiring
- **Goal:** Wire the runtime — a `main.py` lifespan that on startup connects the broker (bounded retry so a boot-order race can't crash core), declares the topology, and starts the relay task plus one consumer task per stub, and on shutdown cancels the tasks and closes the connection cleanly.
- **Rough scope:** Add a lifespan to the core app (which currently has none) and a smoke test that startup/shutdown wire without error. Because the test client's ASGITransport doesn't fire lifespan, tests keep driving the relay/consumers explicitly — the lifespan is the production path only.
- **Open questions / decisions for stakeholders:** Confirm the bounded-retry parameters (attempts/backoff) for an unready broker at boot.
- **Depends on:** Epic 5, Epic 6.
- **Implementation notes:** _none yet_

## Epic 8 — Trigger 1 — `record.created`
- **Goal:** Make the `pii_demo` create publish `record.created` by enqueuing the envelope on the same request session/transaction as the row insert — proving the transactional outbox on a real, existing tenant-scoped write.
- **Rough scope:** Wire the enqueue into the existing create path; a test that one outbox row lands in the same transaction as the created record, and that the existing create/audit tests stay green (responses byte-for-byte unchanged — create just *also* enqueues).
- **Open questions / decisions for stakeholders:** Confirm the non-PII payload fields carried for `record.created` (entity reference + key non-PII fields only) — never a PII snapshot.
- **Depends on:** Epic 3.
- **Implementation notes:** _none yet_

## Epic 9 — Trigger 2 — `pii.revealed`
- **Goal:** Fill the already-waiting reveal seam — extend `on_pii_revealed` to enqueue a `pii.revealed` event on the reveal route's session, carrying the field name only (never the revealed value).
- **Rough scope:** Thread the request session into the seam and enqueue from it; a test that a reveal produces exactly one `pii.revealed` outbox row, and that the existing reveal/audit tests stay green (the signature change is internal).
- **Open questions / decisions for stakeholders:** Confirm the seam keeps both effects ordered/atomic as expected (audit emit + event enqueue on the same reveal) — settle at epic time.
- **Depends on:** Epic 3 (and works end-to-end once Epic 7 is merged).
- **Implementation notes:** _none yet_

## Epic 10 — Observability + config
- **Goal:** Make queue depth browsable on the local stack and pull the new tunables into config — publish the RabbitMQ management UI port in dev compose (prod left unpublished, internal-only) and add the exchange name + outbox poll interval to config, reusing the existing broker URL.
- **Rough scope:** A dev `docker-compose` port edit (prod compose untouched), and a couple of config additions. Mostly mechanical; no new behavior beyond exposure and tuning knobs.
- **Open questions / decisions for stakeholders:** none expected.
- **Depends on:** Epic 5 (poll interval), Epic 7 (the running tasks this observes).
- **Implementation notes:** _none yet_

## Epic 11 — Named acceptance suite
- **Goal:** Prove the whole contract behind the green gate — create a record → relay publishes → **both** stubs consume **once** (fan-out + idempotency) → `correlation_id` flows end-to-end → a poisoned message dead-letters → per-tenant isolation of `outbox`/`processed_events` holds. This is the artifact M3's real sidecars will bind to, so it directly de-risks Risk #4.
- **Rough scope:** A named acceptance test (`test_event_bus_acceptance.py`) on the Postgres + RabbitMQ testcontainer substrate, driving relay/consumers explicitly. Correctness-critical and intentionally end-to-end — kept whole as the phase's single proof (advanced: an atomic acceptance artifact, not split on size).
- **Open questions / decisions for stakeholders:** none expected.
- **Depends on:** Epic 5, Epic 6, Epic 8, Epic 9.
- **Implementation notes:** _none yet_
