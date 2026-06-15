# P1.5 — Event bus + envelope + stub consumers — Technical Design Document

> Phase **P1.5** of the [Program & Phase Plan](../program-and-phase-plan.md).
> Source requirements: [PolicyFlow_Requirements.md](../PolicyFlow_Requirements.md)
> → *Event-Driven Architecture*, *Sidecar Services*, *Phased Delivery → Phase 1*.
> Next step: `3-tdd-to-epic-plan` → sibling `epic-plan-P1.5-event-bus-envelope-stub-consumers.md`.

---

## 1. Summary

P1.5 stands up the **real event bus** the whole event-driven story rests on, while
keeping every *consumer* a deliberate stub. It delivers four things behind one
contract: the frozen **event envelope** (the JSON shape every event carries), a
**transactional outbox** (each event written in the *same* database transaction as
the state change that produced it, so events are never lost relative to committed
state), a **RabbitMQ topic-exchange topology** (one durable exchange, per-consumer
durable queues, per-queue dead-letter exchange → dead-letter queue), and two
**inline stub consumers** (an enrichment stub and a sync-logger stub) that consume
**idempotently**. No domain `lead` exists yet (that is P1.7), so the path is driven
from the two tenant-scoped writes that *do* exist today: the `pii_demo` create
publishes `record.created`, and the already-waiting `on_pii_revealed` seam publishes
`pii.revealed`. M3 later swaps the stub consumers for real sidecar services **behind
the identical events** — the swap is the thing this phase exists to de-risk
(Risk #4). The deliverable is demoable by hand: create a record, watch the RabbitMQ
management UI show queue depth tick up and drain as the stubs consume once each, and
see a poisoned message land in the dead-letter queue.

---

## 2. Business Requirements

Lifted from the requirements' *Event-Driven Architecture*, *Sidecar Services*, and
*Phase 1* sections, and the program plan's P1.5 entry + Decide-Once #5/#6:

- **The system publishes domain events as business actions occur**; consumers
  process them asynchronously.
- **Event envelope** carries `event_id`, `event_type`, `schema_version`,
  `tenant_id`, `occurred_at`, `correlation_id`, optional `causation_id`, optional
  `actor` (user vs system), and optional `demo_session_id`.
- **Payload convention:** entity reference + key **non-PII** fields — never full PII
  snapshots (this also satisfies "no raw PII in logs"). The documented PII exception
  (whitelisted fields for Enrichment / CRM Sync) is an **M3** concern; P1.5 stub
  payloads stay non-PII.
- **Delivery semantics:** at-least-once; **all consumers idempotent** (dedupe on
  `event_id`); **ordering not guaranteed**; events **fan out** (each consumer is an
  independent subscription with its own retry + dead-letter — a single shared work
  queue is not acceptable).
- **Broker/transport** must support durable delivery, multi-consumer fan-out,
  per-consumer retry, and **observable queue depth**.
- **Consistency:** domain events must not be lost relative to committed state —
  mechanism is the **transactional outbox** (frozen Decide-Once #6).
- **Inline stub consumers** (enrichment stub returning canned results, sync-logger
  stub) ship behind the **same events** Phase 3 will serve.
- **Isolation (cross-cutting axis):** every event + queue message carries
  `tenant_id`; consumers scope by it; no record, event, or consumer datum escapes
  its tenant; no raw PII in event payloads or logs.

---

## 3. Goals / Non-Goals

### Goals

- A frozen, versioned **event envelope** + builder, honored by every later phase.
- A **transactional outbox** (per-tenant) + a **polling relay** that publishes
  committed events to RabbitMQ and never loses one relative to committed state.
- A **topic-exchange topology** with per-consumer durable queues and per-queue
  DLX→DLQ; **queue depth observable** in the management UI.
- **Two idempotent inline stub consumers** behind the same events M3 will serve,
  each producing a tenant-scoped, test-observable effect.
- **Correlation IDs flow** end-to-end (publish → relay → consumer), recorded for the
  future timeline (P1.9).
- The path is **demoable by hand** on the local stack and **proven by a named
  acceptance suite** behind the green gate.

### Non-Goals (owned elsewhere)

- **Real sidecar logic** (real enrichment outputs, CRM field mappings, external-ID
  upsert, carrier quotes, notifications) → **M3**.
- **Real `lead.created`** and the rest of the lead-lifecycle events → **P1.7**,
  behind this identical envelope/topology.
- **Retry-with-backoff** ("max 3 attempts") and **DLQ replay/discard UI** → M3 CRM
  Sync (replay UI P3.5 / M4). P1.5 builds DLX/DLQ *plumbing* only.
- **Metrics read model** (the catalog's "Metrics" consumer) → **M4**.
- **`demo_session_id` population** → **P1.8** (the field exists, always `None` now).
- **Request/reply completion loop** (`lead.enrichment.completed` → core applies →
  `lead.enriched`) — needs a real lead to apply results to → **P1.7+**. P1.5 stubs
  are **terminal**.
- **Per-record event-timeline UI** → **P1.9** (it will read `processed_events`).

---

## 4. Current State

Investigation grounding the design (links are clickable):

- **Broker provisioned, not yet used for messaging.** [docker-compose.yml](../../docker-compose.yml)
  runs `rabbitmq:3.13-management-alpine`; [requirements.txt](../../core/requirements.txt)
  pins `aio-pika==9.5.4`; today it is touched only by the health probe
  ([health.py](../../core/app/health.py) → `check_broker`). The **management UI port
  15672 is not published** — reachable only on the internal Docker network.
- **No domain entities.** No `lead` table; the only tenant-scoped write demonstrators
  are `pii_demo` ([pii_demo/router.py](../../core/app/pii_demo/router.py)) and
  `tenant_settings`.
- **Two seams already name P1.5:** [reveal_seam.py:8](../../core/app/pii/reveal_seam.py#L8)
  ("P1.5 will send the `pii.revealed` event") and the reveal route
  [pii_demo/router.py:363](../../core/app/pii_demo/router.py#L363) already `await`s it.
- **Per-tenant table + tight-role precedent.** [0007_audit_records.py](../../core/alembic/versions/0007_audit_records.py)
  creates per-tenant tables by iterating `registry.TENANTS`, with a dedicated
  `audit_writer` role (INSERT+SELECT only) and REVOKE-tightened grants. [0003_tenant_schemas.py](../../core/alembic/versions/0003_tenant_schemas.py)
  sets the default-privilege model (tenant role gets CRUD on its schema; `NOINHERIT`
  login role `SET ROLE`s into exactly one tenant).
- **Own-session module-global pattern** for cross-cutting writes outside the request
  transaction: [audit/service.py](../../core/app/audit/service.py) +
  [app.pii.keys], with the global `session_factory` monkeypatched in tests
  ([conftest.py:149](../../core/tests/conftest.py#L149)).
- **Schema-less tenant ORM model pattern** (resolved via `search_path`, excluded from
  `alembic check`): `AuditRecord` / `PiiDemoRecord` / `TenantSettings`
  ([models/audit_record.py:86](../../core/app/models/audit_record.py#L86)).
- **Registry single source of truth** for schema/role per tenant
  ([tenancy/registry.py](../../core/app/tenancy/registry.py)); per-request scoping via
  `get_tenant_db` ([tenancy/scoping.py](../../core/app/tenancy/scoping.py)) which yields
  the session **inside** `async with db.begin()` — so anything a route writes on that
  session commits atomically.
- **`main.py` has no lifespan** ([main.py](../../core/app/main.py)) — it only mounts
  routers. Background work needs one added. The test client uses
  `httpx.ASGITransport`, which **does not fire lifespan events**, so lifespan-started
  tasks do not auto-run in tests (tests drive relay/consumers explicitly).
- **Test substrate** boots ephemeral **Postgres** via `testcontainers[postgres]`
  ([conftest.py](../../core/tests/conftest.py)); **no RabbitMQ testcontainer** today.
- **Entrypoint** runs `alembic upgrade head` → seed → uvicorn
  ([entrypoint.sh](../../core/entrypoint.sh)); migration failure fails boot.

---

## 5. Proposed Design

> **Flow diagram:** [diagrams/tdd-P1.5-event-bus-flow.png](./diagrams/tdd-P1.5-event-bus-flow.png)
> (source: [tdd-P1.5-event-bus-flow.excalidraw](./diagrams/tdd-P1.5-event-bus-flow.excalidraw)) —
> HTTP write → transactional outbox → polling relay → topic exchange → fan-out to the
> two stub queues → idempotent consume → DLQ on failure, across the core/broker boundary.

### 5.1 Components (all new under `core/app/events/`, plus two wirings + one migration)

| Module | Responsibility |
|---|---|
| `events/catalog.py` | **Pure data.** `EventType` (the P1.5 subset of the Event Catalog), `SCHEMA_VERSION = 1`, the consumer→binding registry (consumer name + routing-key patterns). Mirrors `audit/records.py`. |
| `events/envelope.py` | The `EventEnvelope` shape + `build_envelope(...)` (mint `event_id`, stamp version/`occurred_at`, carry `tenant_id`/`correlation_id`/`actor`, `demo_session_id=None`) + JSON serialize/parse for the broker body. |
| `events/outbox.py` | `enqueue_event(db, envelope)` — one INSERT into the **caller's tenant** `outbox` table on the **request session**, inside the request transaction (transactional). |
| `events/relay.py` | The **polling relay** (own-session, `outbox_relay` role): iterate `TENANTS`, select unpublished rows, publish each, mark `published_at`. |
| `events/broker.py` | RabbitMQ topology (`declare_topology`) + `publish_envelope` over aio-pika. |
| `events/consumers.py` | The two stub handlers (enrichment, sync-logger): dedupe → canned effect + log → record `processed_events` → ack; on error nack(no-requeue) → DLQ. |
| `models/outbox_event.py`, `models/processed_event.py` | Schema-less tenant ORM models (search_path-resolved, drift-excluded; migration owns indexes). |
| `alembic/versions/0008_event_bus.py` | Per-tenant `outbox` + `processed_events` tables in every tenant schema; `outbox_relay` + `event_consumer` roles; grants. |
| `main.py` lifespan | Startup: connect broker, declare topology, start relay + consumer tasks. Shutdown: cancel + close. |
| Wirings | `pii_demo` create → `record.created`; `on_pii_revealed` → `pii.revealed`. |

### 5.2 Data model changes — migration `0008_event_bus`

Two per-tenant tables in **each** tenant schema (iterate `registry.TENANTS`, the
`0007` pattern), both schema-less ORM twins resolved via `search_path` and excluded
from `alembic check` (the `PiiDemoRecord` precedent; migration owns the indexes).

**`<tenant>.outbox`** — the transactional outbox:

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | app-side `uuid4` |
| `event_id` | uuid NOT NULL | the envelope id; unique |
| `event_type` | text NOT NULL | also the routing key |
| `schema_version` | int NOT NULL | |
| `tenant_id` | uuid NOT NULL | every event carries it |
| `correlation_id` | uuid NOT NULL | constant across one flow |
| `causation_id` | uuid NULL | NULL in P1.5 (stubs terminal) |
| `actor_user_id` | uuid NULL | NULL ⇒ system actor |
| `actor_role` | text NULL | |
| `demo_session_id` | uuid NULL | always NULL until P1.8 |
| `payload` | jsonb NOT NULL | entity ref + **non-PII** fields |
| `occurred_at` | timestamptz NOT NULL DEFAULT now() | |
| `published_at` | timestamptz NULL | NULL ⇒ unpublished (relay sets it) |

- Partial index `WHERE published_at IS NULL` on `(occurred_at)` for the relay scan.
- Unique on `event_id` (defensive; the relay's at-least-once is handled downstream).

**`<tenant>.processed_events`** — per-consumer idempotency + observable effect:

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `consumer_name` | text NOT NULL | e.g. `enrichment.stub`, `sync.logger` |
| `event_id` | uuid NOT NULL | the deduped key |
| `tenant_id` | uuid NOT NULL | |
| `event_type` | text NOT NULL | for the future timeline |
| `correlation_id` | uuid NOT NULL | for the future trace view |
| `processed_at` | timestamptz NOT NULL DEFAULT now() | |

- **Unique `(consumer_name, event_id)`** — the dedup constraint; a duplicate insert
  is the idempotency signal.

**Roles & grants** (mirroring `audit_writer`):

- `outbox_relay` (NOLOGIN): USAGE on each tenant schema; **SELECT + UPDATE** on each
  `outbox` (read unpublished, set `published_at`). No INSERT/DELETE.
- `event_consumer` (NOLOGIN): USAGE on each tenant schema; **INSERT + SELECT** on each
  `processed_events`. No UPDATE/DELETE.
- Tenant role: keeps default **INSERT** on its own `outbox` (the transactional write
  by the request session) and **SELECT** on its own `processed_events` (the P1.9
  timeline reads it); its auto-granted writes on `processed_events` and reads/writes
  it should not hold are tightened by REVOKE per the `0007` precedent.
- `platform_reader`: auto-granted SELECT on the new tables is **revoked** (operational
  bookkeeping stays inside its tenant), matching `0007`'s tenant-audit tightening.
- Login role made a member of both new roles via `GRANT … TO CURRENT_USER` (the
  `NOINHERIT` `SET ROLE` precedent).

### 5.3 Interfaces

```python
# events/catalog.py
class EventType(StrEnum):
    RECORD_CREATED = "record.created"   # pii_demo create — the lead.created stand-in
    PII_REVEALED   = "pii.revealed"     # filled via on_pii_revealed

SCHEMA_VERSION = 1

# consumer name → routing-key bindings on the topic exchange
ENRICHMENT_STUB = "enrichment.stub"     # binds: record.created  (+ lead.created in P1.7)
SYNC_LOGGER     = "sync.logger"         # binds: #  (logs every event)
```

```python
# events/envelope.py
@dataclass(frozen=True)
class EventEnvelope:
    event_id: uuid.UUID
    event_type: str
    schema_version: int
    tenant_id: uuid.UUID
    occurred_at: datetime
    correlation_id: uuid.UUID
    causation_id: uuid.UUID | None
    actor_user_id: uuid.UUID | None
    actor_role: str | None
    demo_session_id: uuid.UUID | None
    payload: dict

def build_envelope(*, event_type, tenant_id, actor_user_id, actor_role,
                   payload, correlation_id=None, causation_id=None) -> EventEnvelope: ...
def to_message_body(envelope) -> bytes: ...      # JSON
def from_message_body(body) -> EventEnvelope: ...
```

```python
# events/outbox.py  — transactional, on the caller's tenant session
async def enqueue_event(db: AsyncSession, envelope: EventEnvelope) -> None: ...

# events/relay.py  — own-session, outbox_relay role
async def publish_pending_once(broker_channel) -> int: ...   # one sweep; returns count
async def run_relay_loop(...) -> None:                       # poll every N seconds

# events/broker.py
async def declare_topology(channel) -> None: ...             # exchange + queues + DLX/DLQ
async def publish_envelope(channel, envelope) -> None: ...   # routing_key = event_type

# events/consumers.py  — own-session, event_consumer role, routed by tenant_id
async def handle_enrichment(message) -> None: ...
async def handle_sync_logger(message) -> None: ...
```

### 5.4 RabbitMQ topology (topic exchange)

- One durable **topic** exchange `policyflow.events`.
- One durable **DLX** `policyflow.events.dlx` (topic).
- Per consumer, a durable queue with `x-dead-letter-exchange = policyflow.events.dlx`
  and a sibling DLQ bound to the DLX on the same key:
  - `enrichment.stub` ← binding `record.created` → DLQ `enrichment.stub.dlq`
  - `sync.logger` ← binding `#` (all events) → DLQ `sync.logger.dlq`
- `record.created` **fans out** to both queues (proves fan-out + per-consumer
  idempotency); `pii.revealed` reaches `sync.logger` (proves a second event type and
  that nothing is dropped). Messages publish **persistent** with AMQP
  `message_id = event_id`, `correlation_id = correlation_id`, `tenant_id` header.

### 5.5 Primary flows

**A. Publish via the transactional outbox (`record.created`).**
1. `POST /api/pii-demo/` runs inside `get_tenant_db`'s `async with db.begin()`.
2. The handler inserts the `pii_demo` row, then calls `enqueue_event(db, envelope)` —
   a second INSERT into `<tenant>.outbox` **on the same session/transaction**.
3. The request returns; the block commits → the record **and** its outbox row land
   atomically (or both roll back). The existing own-session audit write is unchanged.

**B. Relay → broker.**
1. The lifespan relay loop wakes every ~1s.
2. As `outbox_relay`, for each tenant it `SELECT … FROM <tenant>.outbox WHERE
   published_at IS NULL ORDER BY occurred_at`.
3. For each row it `publish_envelope(channel, …)` to the topic exchange, then
   `UPDATE … SET published_at = now()`.
4. **At-least-once:** a crash between publish and update re-publishes on the next
   sweep — consumer dedup (flow C) absorbs the duplicate.

**C. Consume idempotently.**
1. A stub handler parses the envelope, then as `event_consumer` (own session, routed
   by `tenant_id`) attempts `INSERT … processed_events (consumer_name, event_id, …)`.
2. **Unique `(consumer_name, event_id)` violation ⇒ already processed** → ack + skip
   (idempotent). Otherwise the insert commits, the canned effect runs (enrichment:
   log "canned enrichment for <entity>"; sync-logger: log the event), and the message
   is acked.
3. **Handler exception** → `nack(requeue=False)` → the message dead-letters via the
   DLX to that consumer's DLQ (observable in the management UI). No retry loop.

**D. Correlation flow.** `record.created` / `pii.revealed` each mint a fresh
`correlation_id` (a new flow) carried on the envelope, the AMQP property, and the
`processed_events` row — so one flow is traceable end-to-end (the seed of P1.9 /
the P2.5 trace view). `causation_id` stays `null` (no event causes another yet).

### 5.6 Runtime & observability

- **Lifespan** (`main.py`): on startup open one aio-pika connection, `declare_topology`,
  start the relay task + one consumer task per stub; on shutdown cancel tasks and close
  the connection. Tolerant of a not-yet-ready broker (bounded connect retry) so boot
  ordering races don't crash the app.
- **Queue depth observable:** publish `15672:15672` in dev
  [docker-compose.yml](../../docker-compose.yml) so the management UI is browsable at
  `localhost:15672`. Prod [docker-compose.prod.yml](../../docker-compose.prod.yml)
  leaves it **unpublished** (internal only — off the public internet; reachable via SSM
  tunnel if ever needed).

---

## 6. Decisions

| # | Decision | Chosen | Alternatives considered | Rationale |
|---|---|---|---|---|
| 1 | **What publishes in P1.5** (no `lead` until P1.7) | Reuse existing tenant writes: `pii_demo` create → `record.created`; fill `on_pii_revealed` → `pii.revealed` | A dedicated `POST /api/events/demo` endpoint; wait for P1.7 | Minimal churn; proves the **transactional** outbox on a real state change; fills the seam already named for P1.5. The real `lead.created` lands in P1.7 behind the identical contract. |
| 2 | **Where stub consumers run** | In-process inline tasks in the **core** container (lifespan) | Separate `worker` process/container in the same repo | The plan says "inline"; the **event contract** is the seam M3 depends on, not the process boundary. M3 relocates consumers to real sidecars then. |
| 3 | **Exchange type** | **Topic** exchange (`policyflow.events`) | Direct (no wildcards); fanout (broadcast + filter in code) | Per-consumer routing matches the Event Catalog; wildcard binds (`record.created`, `#`, later `lead.*`) are what consumers want. |
| 4 | **Outbox placement** | **Per-tenant `outbox`** table in each tenant schema | Single `platform.outbox` | A `platform` write can't sit in the tenant role's transaction → would break atomicity. Per-tenant keeps the write transactional **and** schema-isolated. |
| 5 | **Outbox→broker mechanism** | **Polling relay** (~1s, lifespan task) | Postgres `LISTEN/NOTIFY` | Simple, durable, no new infra; sub-second demo latency is fine. NOTIFY adds an always-on listener + more failure modes and still needs a poll fallback. |
| 6 | **Consumer dedup + state** | **Per-tenant `processed_events`** (`event_consumer` role, routed by `tenant_id`) | Consumer-owned, column-scoped store | Preserves the project's single isolation model (schema-per-tenant); no new column-scoped pattern. M3 relocates state to sidecar-owned stores. |
| 7 | **DLQ depth** | DLX/DLQ **plumbing + dead-letter on failure** (nack, no requeue) | Also a bounded retry | Retry-with-backoff ("max 3") is M3 CRM Sync's job; replay/discard UI is P3.5/M4. P1.5 proves the seam, not sidecar retry logic. |
| 8 | **Stub shape** | **Terminal** (consume + observable effect) | Request/reply completion events | "Core applies results" needs a real lead to apply them to → P1.7+. |
| 9 | **Cross-cutting roles** | Dedicated `outbox_relay` (SELECT+UPDATE) + `event_consumer` (INSERT+SELECT), own-session | Reuse a tenant role / the login role | Mirrors `audit_writer`: tight grants, no request identity, isolation-safe cross-tenant relay. |
| 10 | **Management UI exposure** | Publish `15672` **dev only**; prod unpublished | Publish in prod; never publish | Acceptance needs queue depth browsable locally; prod parity keeps the UI off the public internet. |
| 11 | **Envelope constants** | `schema_version = 1`; `demo_session_id` always `None`; `causation_id` `null` | — | The fields are frozen now; their P1.5 values reflect what exists (no demo sessions until P1.8, no causation until follow-on events). |
| 12 | **`.git/info/exclude`** | **Not** adding `.development-docs/` | Append per skill default | These docs are already tracked/committed in this repo; excluding would hide this TDD and break project practice. |

---

## 7. Risks and Open Questions

- **Risk #4 (the one this phase de-risks): stub→real swap staying invisible.** The
  envelope shape + topic-exchange topology + routing keys are the contract M3 must
  reuse unchanged. Mitigation: freeze the envelope + catalog as pure data with
  drift-asserting tests (the `audit/records.py` precedent); the named acceptance suite
  exercises the exact contract a real sidecar will bind to.
- **At-least-once duplicates** from a relay crash between publish and `published_at`
  update are **by design** — consumer dedup (`processed_events` unique key) absorbs
  them. The acceptance suite redelivers the same `event_id` and asserts one effect.
- **Unroutable messages:** an event with no bound queue is dropped by RabbitMQ.
  `sync.logger` binds `#`, so every published event has at least one consumer — nothing
  silently vanishes.
- **Lifespan vs `ASGITransport`:** tests don't fire lifespan, so relay/consumers are
  driven explicitly in tests (deterministic) rather than relying on background tasks.
- **Broker readiness at boot:** the lifespan connect uses a bounded retry so a
  compose start-order race doesn't crash core (health already gates ordering, but the
  app should self-heal).
- **Open question for P1.7 (not P1.5):** when the real `lead.created` arrives, does the
  enrichment stub move to a request/reply completion event? Deferred — P1.5 keeps stubs
  terminal and records the seam.

---

## 8. Rollout / Verification

- **Migration `0008` is additive** (new tables + roles); applied by the entrypoint at
  deploy. New roles are cluster-global, created idempotently (the `0003`/`0007`
  DO-block guard). `alembic check` stays drift-clean (schema-less models excluded;
  migration owns indexes); `0008` down/up round-trip is tested.
- **No existing API contract changes:** `pii_demo` responses are byte-for-byte
  unchanged (create just *also* enqueues an outbox row); the `on_pii_revealed`
  signature change is internal. Existing suites stay green.
- **Manual demo (local stack):**
  1. Bring up the stack; open `localhost:15672` (guest/guest) → see the
     `enrichment.stub` / `sync.logger` queues + their DLQs declared.
  2. Log in as an Agent; `POST /api/pii-demo/` → both queues' depth ticks up, then
     drains as the stubs consume; `processed_events` shows one row per consumer.
  3. Reveal a field → `pii.revealed` flows to `sync.logger`.
  4. Force a handler error (a test-only poison flag) → the message lands in the DLQ
     and stays there (no replay in P1.5).
- **Backwards compatibility:** purely additive; prod compose keeps 15672 unpublished.

---

## 9. Work Breakdown

Simplest-first: the contract, then storage, then the publish side, then the bus, then
consumers, then runtime, then the two real triggers, then observability, then the
acceptance proof. Each item is one focused, reviewable epic (~150 lines · ~8 files).

1. **Event vocabulary + envelope (pure data, no I/O).** `events/catalog.py`
   (`EventType` subset, `SCHEMA_VERSION`, consumer/binding registry) +
   `events/envelope.py` (`EventEnvelope`, `build_envelope`, JSON serialize/parse).
   Unit tests assert the vocabulary against a hand-written expectation (the
   `test_audit_records` precedent) and round-trip the envelope.
2. **Migration `0008` + ORM models.** Per-tenant `outbox` + `processed_events` tables,
   `outbox_relay` + `event_consumer` roles, grants/REVOKEs; schema-less
   `OutboxEvent` / `ProcessedEvent` models registered in `models/__init__`. Substrate
   test: apply, `alembic check` drift-clean, `0008` down/up round-trip.
3. **Transactional enqueue.** `events/outbox.py::enqueue_event(db, envelope)` — INSERT
   on the caller's session. DB test: row present on commit, gone on rollback;
   per-tenant isolation (tenant A's role cannot read B's outbox).
4. **Broker topology + publish.** `events/broker.py::declare_topology` +
   `publish_envelope`. Unit-test the declared bindings as data; first RabbitMQ
   testcontainer test that a published envelope lands in the bound queues
   (adds `testcontainers[rabbitmq]` dev dep).
5. **Polling relay.** `events/relay.py` (own-session, `outbox_relay`): publish
   unpublished rows, mark `published_at`. DB+broker test: enqueue → sweep → message in
   queue + row marked published; only unpublished selected; a re-sweep after a forced
   "publish-but-not-marked" re-publishes (at-least-once).
6. **Stub consumers.** `events/consumers.py`: enrichment + sync-logger; dedupe via
   `processed_events` (own-session, `event_consumer`, routed by `tenant_id`); canned
   effect + structured log; ack / nack→DLQ. Tests: consume writes one row; redelivery
   of the same `event_id` is idempotent; a poison message dead-letters.
7. **Lifespan wiring.** `main.py` lifespan: connect broker (bounded retry),
   `declare_topology`, start relay + consumer tasks, clean shutdown. Smoke test that
   startup/shutdown wire without error.
8. **Trigger 1 — `record.created`.** `pii_demo` create enqueues on the request session
   (transactional with the insert). Test: create → one outbox row in the same tx;
   existing create/audit tests stay green.
9. **Trigger 2 — `pii.revealed`.** Extend `on_pii_revealed` to accept `db` and enqueue
   the event; the reveal route passes its `db`. Test: reveal → one `pii.revealed`
   outbox row; existing reveal/audit tests stay green.
10. **Observability + config.** Publish `15672` in dev compose (prod unpublished); add
    `EVENT_EXCHANGE` + `OUTBOX_POLL_INTERVAL_SECONDS` to `config.py` (reuse
    `RABBITMQ_URL`).
11. **Named acceptance suite** `tests/test_event_bus_acceptance.py` (Postgres +
    RabbitMQ testcontainers): create record → relay publishes → **both** stubs consume
    **once** (fan-out + idempotency) → `correlation_id` flows end-to-end → a poisoned
    message dead-letters → per-tenant isolation of `outbox` / `processed_events` holds.

---

*End of P1.5 TDD. Next: `3-tdd-to-epic-plan` → `epic-plan-P1.5-event-bus-envelope-stub-consumers.md`.*
