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

## Epic 2 — Migration `0008` + ORM models — **COMPLETED**
- **Goal:** Add the per-tenant `outbox` and `processed_events` tables to every tenant schema, plus the dedicated `outbox_relay` and `event_consumer` roles with tight grants/REVOKEs (the `0007` precedent), and the matching schema-less ORM models.
- **Rough scope:** One additive Alembic migration iterating the tenant registry, two drift-excluded ORM twins registered with the models package, and a substrate test that applies the migration, confirms `alembic check` stays drift-clean, and round-trips `0008` down/up.
- **Open questions / decisions for stakeholders:** Confirm the index/constraint shape (relay's partial index on unpublished rows; the `(consumer_name, event_id)` dedup unique) reads as intended — the TDD specifies it; settle any naming at epic time.
- **Depends on:** Epic 1.
- **Implementation notes:**
  - **Plan-time decisions (settled at `4-plan-epic`):**
    - **Index/constraint naming** (the epic's one open question — shape frozen by TDD §5.2, naming derived from the `app/db.py` convention + `0006`/`0007`): `pk_outbox` / `uq_outbox_event_id` / partial `ix_outbox_unpublished` (`ON (occurred_at) WHERE published_at IS NULL`); `pk_processed_events` / `uq_processed_events_consumer_name_event_id` (composite `(consumer_name, event_id)`). Both tables are schema-less + drift-excluded, so the **migration owns** every index/constraint; the ORM twins declare columns + PK only (the `PiiDemoRecord`/`AuditRecord` rule).
    - **Per-tenant only** — `outbox` and `processed_events` exist in each tenant schema (iterate `registry.TENANTS`); **no** `platform.*` twin (unlike audit's tenantless platform store).
    - **Grant matrix (TDD §5.2, mirroring `audit_writer`/`0007`):** `outbox_relay` NOLOGIN → USAGE + SELECT,UPDATE on each `outbox`; `event_consumer` NOLOGIN → USAGE + INSERT,SELECT on each `processed_events`; login role made a member of both via `GRANT … TO CURRENT_USER`. Tenant role tightened to INSERT-only on its `outbox` and SELECT-only on its `processed_events`; `platform_reader` REVOKEd SELECT on both.
    - **Drift + round-trip reused, not duplicated:** the existing `tests/test_migration_hygiene.py` already runs `alembic check` + `downgrade base → upgrade head` for the whole chain, so `0008` is covered once it joins; the new `tests/test_event_bus_migration.py` only asserts the `0008` shape (tables/roles/grant-matrix/indexes via `has_table_privilege` + `pg_indexes`/`pg_constraint`), mirroring `test_audit_migration.py`.
    - **No diagram** (static data-model/grant-matrix epic — offer skipped per `0-conventions`, matching Epic 1).
    - Build order: Phase 1 = tables + ORM twins + `env.py` drift exclusion; Phase 2 = roles + grants/REVOKEs + substrate test. One migration file / one reviewable commit.
  - **Build notes (`5-implement-epic`):**
    - **Roles** added to `app/tenancy/registry.py`: `OUTBOX_RELAY_ROLE = "outbox_relay"`, `EVENT_CONSUMER_ROLE = "event_consumer"` (mirroring the `AUDIT_WRITER_ROLE` constant + docstring).
    - **Migration** `core/alembic/versions/0008_event_bus.py` (revises `0007_audit_records`): per-tenant `outbox` + `processed_events` in each `registry.TENANTS` schema; `outbox_relay`/`event_consumer` created via the copied `create_role_if_absent` DO-block guard + `GRANT … TO CURRENT_USER` membership; grant matrix and REVOKEs exactly as the plan/TDD §5.2 specify; symmetric downgrade drops tables (children first), revokes schema USAGE, then revokes membership and drops the roles (`IF EXISTS`). Names: `pk_outbox` / `uq_outbox_event_id` / partial `ix_outbox_unpublished` and `pk_processed_events` / `uq_processed_events_consumer_name_event_id`.
    - **ORM twins** `app/models/outbox_event.py` (`OutboxEvent`) + `app/models/processed_event.py` (`ProcessedEvent`): schema-less (no `{"schema": …}`), columns + PK only, `payload` as `sqlalchemy.dialects.postgresql.JSONB`; both registered in `app/models/__init__.py`. `OutboxEvent` columns mirror `EventEnvelope` 1:1 plus the relay's `published_at`.
    - **Drift exclusion**: `env.py` `include_object` now also name-excludes `outbox` + `processed_events` (no platform twin → name-only safe); docstring updated. `test_migration_hygiene.py` docstring schema-less list extended to match. No `xfail`/code changes to the hygiene tests were needed — `alembic check` stays drift-clean because the twins are excluded and the migration owns all indexes/constraints.
    - **New substrate test** `core/tests/test_event_bus_migration.py` (mirrors `test_audit_migration.py`): 10 tests — table/column presence per tenant schema, no-platform-twin, both roles exist, the two grant matrices via `has_table_privilege`, tenant-role tightening (INSERT-only outbox / SELECT-only processed_events), `platform_reader` revoked on both, partial index via `pg_indexes`, both uniques via `pg_constraint`. Every expected value reads from the registry.
    - **Targeted tests**: `cd core && ./.venv/Scripts/python.exe -m pytest tests/test_event_bus_migration.py tests/test_migration_hygiene.py -q` → **12 passed** (10 new + the 2 hygiene tests confirming `0008` joins drift-clean and round-trips down/up).
    - **No deviations** from the plan or Rough scope. No ambiguity required resolving — the plan-time decisions, TDD §5.2, and the `0007` precedent fully determined the shape.

## Epic 3 — Transactional enqueue — **COMPLETED**
- **Goal:** Provide the transactional outbox write — an `enqueue_event` that inserts the envelope into the caller's tenant `outbox` on the request session, inside the request transaction, so an event is never lost relative to the committed state that produced it.
- **Rough scope:** A small enqueue helper in the events package, with a DB test proving the row is present on commit and gone on rollback, plus per-tenant isolation (tenant A's role cannot read B's outbox).
- **Open questions / decisions for stakeholders:** none expected.
- **Depends on:** Epic 2.
- **Implementation notes:**
  - Added `core/app/events/outbox.py` — `async def enqueue_event(db, envelope)`: maps the envelope 1:1 onto `OutboxEvent` and inserts with a single `db.add(...)` + `await db.flush()` (the `create_record` idiom). Runs on the caller's request session; does **not** commit (the request transaction owns commit/rollback); `published_at` left NULL for the Epic 5 relay. Schema-less `OutboxEvent` resolves into the caller's tenant schema via the active `search_path`, so no schema interpolation.
  - Added `core/tests/test_outbox_enqueue.py` — 4 DB substrate tests (`database_engine`, `@pytest.mark.asyncio`): Phase 1 present-after-commit / absent-after-rollback; Phase 2 lands-only-in-caller-schema / tenant-role-denied-other-outbox. Enqueue runs under the real INSERT-only tenant role (`SET LOCAL ROLE` + `SET LOCAL search_path`); read-back uses the SELECT-capable superuser engine connection, schema-qualified (the tenant role is INSERT-only on its own outbox).
  - **Deviation from the plan's helper snippet (necessary, and the plan's own decision 1 anticipated it):** the helper also sets `occurred_at=envelope.occurred_at` client-side. With it left unset, SQLAlchemy emitted `INSERT ... RETURNING outbox.occurred_at` to fetch the model's `server_default=now()` — which the INSERT-only tenant role cannot SELECT, so the first run raised `permission denied for table outbox`. Setting `occurred_at` from the envelope removes the server-default round-trip (plain INSERT, no `RETURNING`) and is the faithful mapping (the committed event carries the envelope's stamped time). The present-after-commit test asserts `occurred_at` round-trips.
  - Targeted run (per `0-conventions.md` → Targeted test runs), from `core/`: `./.venv/Scripts/python.exe -m pytest tests/test_outbox_enqueue.py -q` → **4 passed**. Backend-only epic → no frontend tests.

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
