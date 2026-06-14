# P1.4 — Audit Logging — Technical Design Document

## 1. Summary

Build the **append-only audit spine** the platform records every sensitive
operation through, from day one. A single audit-emit service writes one immutable
record per audited action — storing **field names, never raw PII values** — into
one of two stores chosen by a single rule: a schema-less `audit_records` table in
**each tenant schema** for tenant-scoped events, and a `platform.audit_records`
table for tenantless/platform events (so the Platform-Admin cross-tenant read
lands in the platform store automatically). Writes go through a **dedicated
`audit_writer` DB role on its own short-lived session** (the `pii/keys.py`
precedent), which lets the two existing no-op seams —
`record_platform_read_for_audit` (P1.2, runs under the read-only `platform_reader`
role) and `on_pii_revealed` (P1.3) — be filled with **zero call-site churn**, and
makes **append-only physical**: `audit_writer` holds `INSERT`+`SELECT` only and no
role the app uses to touch audit holds `UPDATE`/`DELETE`. The phase wires every
sensitive surface that exists today — PII reveal, cross-tenant platform read, auth
login/logout, and the `pii_demo` record create — and ships a **guarded backend
read endpoint** (`GET /api/audit`, gated by the already-defined `VIEW_AUDIT_LOGS`
capability) that renders no unmasked PII and is **itself audited**, satisfying
"viewing audit is itself an audited operation." The acceptance proof is automated:
sensitive ops write records, records carry names-not-values, append-only is
enforced at the DB layer, tenant audit is readable only within its tenant, and
viewing audit writes an `audit.viewed` record. The audit **viewer UI** is deferred
to M4; the **`pii.revealed` event + transactional outbox** stay deferred to P1.5
(this phase writes only the audit *record*, not the event).

## 2. Business Requirements

Lifted from `program-and-phase-plan.md` → **P1.4** (lines 287–298), the
**Decide Once** envelope (#5 actor/correlation, #7 PII model), and
`PolicyFlow_Requirements.md` → **Audit Logging** (§lines 563–574),
**Authorization** (the `View audit logs` row), and **PII Protection**
(§Additional Controls):

- **Capture** for sensitive operations: user actions, record modifications, lead
  conversions / duplicate resolutions, application submissions, policy creation,
  CRM sync outcomes, integration failures, **authentication events**,
  role-assignment changes, **PII reveals**, and **Platform-Admin cross-tenant
  reads**. *(P1.4 wires the subset of these whose surfaces exist today; the rest
  are wired as their surfaces land in M2/M3 — see Non-Goals.)*
- Each audit record includes: **timestamp, tenant, user, event type, entity type,
  entity reference, and outcome.**
- Audit records store entity references and the **names** of changed fields —
  **never raw PII values**.
- Audit records are **append-only**.
- **Viewing or exporting audit logs is itself an audited sensitive operation.**
- The audit log view renders **no unmasked PII** (safe for the demo walkthrough).
- Authorization: **View audit logs** is held by **Tenant Admin** and **Read-Only**
  (not Agent, not Platform Admin) — already encoded as
  `Capability.VIEW_AUDIT_LOGS`.

## 3. Goals / Non-Goals

**Goals**
- A small **audit constants** module (event types + outcomes) — pure, unit-tested.
- A **two-store audit model**: a platform-schema `PlatformAuditRecord` (reflected
  by Alembic) and a schema-less `AuditRecord` (one table per tenant schema,
  created by a registry-loop migration, excluded from drift) — identical columns.
- A **dedicated `audit_writer` DB role** + grants making append-only **physical**,
  created by a hand-written migration alongside the tables.
- A single **audit-emit service** (`record_audit_event`) that resolves the target
  store from `tenant_id`, writes on its **own** session as `audit_writer`, and
  stores **names, never values**.
- **Filling the two seams** (`record_platform_read_for_audit`, `on_pii_revealed`)
  and **wiring** auth login/logout + `pii_demo` create — every sensitive surface
  that exists today.
- A **guarded `GET /api/audit`** read endpoint (`VIEW_AUDIT_LOGS`, tenant-scoped,
  PII-free) that is **itself audited**.
- An **acceptance suite** proving sensitive ops are audited, names-not-values,
  append-only, tenant-scoped, and viewing-is-audited.

**Non-Goals** (owned by later phases — each named)
- **Audit viewer / export UI** → **M4 (P4.2)**. P1.4 ships the backend read
  endpoint only.
- **The `pii.revealed` event + transactional outbox** (and all other domain
  events) → **P1.5**. The reveal seam stays one place; P1.4 writes only the audit
  *record*. (When P1.5 lands, `correlation_id` ties the record to the event.)
- **Auditing real domain record changes** (lead conversions, duplicate
  resolutions, application/policy lifecycle, CRM sync outcomes, integration
  failures, role-assignment changes) → **M2/M3**, audited as those surfaces are
  built, through this same service. P1.4 proves the path on the `pii_demo` create.
- **Auditing RBAC-denied (403) attempts** → deferred. Capturing denials needs
  guard/middleware-level emission; P1.4 audits *successful* sensitive ops plus
  **failed login** (the one denial on a pre-RBAC path). The `outcome` column
  leaves room.
- **Seeded audit history** (so the viewer is non-empty on a cold boot) →
  **P1.8/M4** (seed + demo polish). P1.4's viewer is populated by real actions.
- **Demo-session tagging / 24h purge** of audit rows → **P1.8** (it owns
  `demo_session_id` and the purge cascade; seeded audit survives purge).
- **Per-target-tenant detail** on the cross-tenant read record → future; the
  current platform read lists *all* tenants and the seam carries only `identity`.

## 4. Current State

- **The two seams are wired and waiting — no-op today.**
  `record_platform_read_for_audit(identity)` is `await`ed inside `get_platform_db`
  on the privileged path ([scoping.py:129](../../core/app/tenancy/scoping.py#L129));
  `on_pii_revealed(identity, entity_type, entity_id, field_name)` is `await`ed on
  every successful reveal ([reveal_seam.py:27](../../core/app/pii/reveal_seam.py#L27)).
  Both return `None`. P1.4 fills the bodies; the reveal endpoint already passes
  `entity_type="pii_demo"`, the record id, and the field name.
- **The RBAC cell already exists.** `Capability.VIEW_AUDIT_LOGS` is defined and
  granted to **Tenant Admin** + **Read-Only** (not Agent, not Platform Admin) in
  [rbac.py:39](../../core/app/auth/rbac.py#L39). The audit read endpoint needs no
  matrix change — only `require_capability(VIEW_AUDIT_LOGS)`.
- **Two table patterns are established and reusable.**
  - *Per-tenant, schema-less:* [tenant_settings.py](../../core/app/models/tenant_settings.py)
    / [pii_demo.py](../../core/app/models/pii_demo.py) — no schema binding,
    resolved via `search_path`; created **in each tenant schema** by a registry
    loop ([0006_pii_demo.py](../../core/alembic/versions/0006_pii_demo.py)); the
    `alembic/env.py` filter excludes them from drift.
  - *Platform-schema, reflected:* [tenant_data_key.py](../../core/app/models/tenant_data_key.py)
    (`__table_args__ = {"schema": "platform"}`) — surfaced normally by
    `alembic check`.
  `AuditRecord` follows the first; `PlatformAuditRecord` the second.
- **The role/grant model is set.** [0003_tenant_schemas.py](../../core/alembic/versions/0003_tenant_schemas.py)
  creates the per-tenant `NOLOGIN` roles + `platform_reader`, sets
  `ALTER DEFAULT PRIVILEGES` granting tenant roles **CRUD** and `platform_reader`
  **SELECT** on future tables in each tenant schema, and makes the connected login
  role `NOINHERIT` + a member of every role so a request can `SET ROLE` into
  exactly one. `audit_writer` joins this model (created idempotently via a `DO`
  block; `GRANT audit_writer TO CURRENT_USER`). **Note the default-privileges
  consequence:** a new tenant `audit_records` table is auto-granted CRUD to the
  tenant role and SELECT to `platform_reader` — so the migration must explicitly
  **`REVOKE`** to tighten it to append-only + tenant-only.
- **The "own session" precedent is set.** Per-tenant key resolution reads through a
  module-global `app.pii.keys.session_factory`, a session **separate** from the
  request's `get_db`; the test substrate monkeypatches it via the
  `container_keys_session_factory` fixture ([conftest.py:129](../../core/tests/conftest.py#L129)).
  The audit service mirrors this exactly (its own `session_factory`, its own
  `container_audit_session_factory` fixture).
- **The safe-identifier idiom is set.** Schema/role identifiers can't be bound as
  parameters, so they are interpolated **only after** whitelist-validation against
  the registry ([scoping.py:46](../../core/app/tenancy/scoping.py#L46),
  `is_known_tenant_pair`). The audit service resolves `tenant_id → schema_name`
  from `platform.tenants` (as `get_tenant_db` does) and validates against the
  registry before interpolating.
- **Role names live in the registry.** `PLATFORM_ROLE = "platform_reader"` in
  [registry.py:60](../../core/app/tenancy/registry.py#L60) is the single source of
  truth; `AUDIT_WRITER_ROLE = "audit_writer"` joins it there.
- **Auth surfaces to wire.** [auth/router.py](../../core/app/auth/router.py):
  `login` (success path has the `Identity`; failure returns 401 generically),
  `logout` (revokes the token; does **not** currently resolve the identity).
- **The record-change surface that exists today** is `pii_demo` create
  ([pii_demo/router.py:124](../../core/app/pii_demo/router.py#L124)); it knows the
  field names it wrote and the new row id.
- **Test substrate is ready.** [conftest.py](../../core/tests/conftest.py) gives a
  session-scoped ephemeral Postgres (testcontainers, `alembic upgrade head`), a
  real `db_session`, a DB-backed `db_client`, and `login_as`/`seeded` helpers
  ([test_endpoints_db.py](../../core/tests/test_endpoints_db.py)). The named
  acceptance pattern is set by [test_pii_acceptance.py](../../core/tests/test_pii_acceptance.py)
  and the physical-permission pattern by [test_isolation_acceptance.py](../../core/tests/test_isolation_acceptance.py).
  Full backend suite is currently **230 passed**.
- **One existing test must change:** `test_reveal_seam.py` asserts the seam is a
  no-op returning `None`; once filled it writes a record, so that test is updated
  (not removed).
- **Constraints** — `CLAUDE.md`: descriptive naming, booleans as yes/no questions,
  natural-language verbs, many small focused modules. Memory: minimal-churn
  insertion-style edits; dev *is* the local Docker stack, prod on EC2; single
  source of truth for shared data.

## 5. Proposed Design

### High-level approach
Every audited action calls **one** function, `record_audit_event(...)`, with the
caller's identity fields plus what happened (event type, outcome, optional entity
reference, optional **field names**). The service picks the store by a single rule
— **`tenant_id` present → that tenant's schema; absent → `platform`** — opens its
**own** short-lived session, reads the tenant's schema name from `platform.tenants`
(as the login role, before any role switch) and whitelist-validates it, then issues
`SET LOCAL ROLE audit_writer` and a schema-qualified `INSERT INTO
<schema>.audit_records (...)`, and commits. Because the only role that writes audit
(`audit_writer`) has `INSERT`+`SELECT` and no `UPDATE`/`DELETE`, and the only role
that reads audit in-app (the tenant role, via the viewer) has `SELECT` only,
**append-only is physical**. The two existing seams call this function and need no
signature change; auth login/logout, `pii_demo` create, and the new `GET /api/audit`
call it too. The viewer reads the tenant's records under `get_tenant_db` (tenant
role) and, before returning, records its own `audit.viewed`.

> **Diagram:** [audit emission & two-store routing](./diagrams/tdd-P1.4-audit-emission-flow.excalidraw)
> ([rendered PNG](./diagrams/tdd-P1.4-audit-emission-flow.png))
> — the five emit sites → `record_audit_event` → the `tenant_id` routing fork →
> `audit_writer` on its own session → tenant vs platform store; and the guarded,
> self-auditing read path.

### Components added / changed (core service)

```
core/app/
  audit/
    __init__.py
    records.py         # EventType + Outcome constants; field-name helpers — pure, no DB
    service.py         # record_audit_event(...): own session, tenant_id→schema resolve+
                       #   whitelist, SET LOCAL ROLE audit_writer, schema-qualified INSERT.
                       #   Module-global `session_factory` (the keys.py pattern).
    router.py          # GET /api/audit — guarded (VIEW_AUDIT_LOGS), tenant-scoped,
                       #   PII-free, self-auditing.
    schemas.py         # the masked-by-construction (names-only) audit response model
  models/
    audit_record.py    # PlatformAuditRecord (schema="platform") + schema-less AuditRecord
  tenancy/
    registry.py        # + AUDIT_WRITER_ROLE = "audit_writer"
    scoping.py         # fill record_platform_read_for_audit body
  pii/
    reveal_seam.py     # fill on_pii_revealed body
  auth/
    router.py          # emit auth.login (success/failure) + auth.logout
  pii_demo/
    router.py          # emit record.created (field NAMES only) on create
  main.py              # mount audit_router
core/alembic/versions/
  0007_audit_records.py  # audit_writer role; platform.audit_records; per-tenant
                         #   audit_records (registry loop) + grants + append-only REVOKEs
core/tests/
  conftest.py          # + container_audit_session_factory fixture (mirrors keys)
```

### Data model — `audit_records` (identical columns in both stores)

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | surrogate key |
| `occurred_at` | `timestamptz` NOT NULL DEFAULT `now()` | **timestamp** |
| `tenant_id` | `uuid` NULL | **tenant** — the owning tenant; `NULL` for platform/tenantless events |
| `actor_user_id` | `uuid` NULL | **user** — a reference, never the username/email; `NULL` for failed login / anonymous |
| `actor_role` | `text` NULL | the role at action time; `NULL` when there is no identity |
| `event_type` | `text` NOT NULL | **event type** — e.g. `auth.login`, `pii.revealed`, `record.created`, `platform.cross_tenant_read`, `audit.viewed` |
| `entity_type` | `text` NULL | **entity type** — e.g. `pii_demo`, `audit_records` |
| `entity_id` | `uuid` NULL | **entity reference** |
| `field_names` | `text[]` NULL | the **names** of fields involved — **never values** |
| `outcome` | `text` NOT NULL | **outcome** — `success` / `failure` (`denied` reserved) |

- One non-unique index `ix_audit_records_occurred_at` on `occurred_at` for the
  viewer's newest-first ordering. (Filtering by `event_type` is a viewer concern →
  M4.)
- **"User" is stored as a reference, not a name.** `actor_user_id` + `actor_role`,
  never `username` (it is an email — PII-ish). This keeps the audit store free of
  raw PII by construction, satisfying "never raw PII values."
- **Deliberately omitted now** (added by their owning phase, no speculative
  columns): `correlation_id` → **P1.5** (ties record ↔ event); `demo_session_id`
  → **P1.8** (tagging + purge).
- `PlatformAuditRecord` binds `{"schema": "platform"}` (reflected by Alembic);
  `AuditRecord` is schema-less (resolved via `search_path`, excluded from drift by
  the existing `env.py` filter) — exactly the `tenant_data_key` vs `pii_demo`
  split. The two map distinct table keys (`platform.audit_records` vs
  `audit_records`), so both can coexist on `Base.metadata`.

### Roles, grants & physical append-only (migration `0007`)

```
audit_writer            (new, NOLOGIN; GRANT audit_writer TO CURRENT_USER)
  platform schema:      GRANT USAGE; GRANT INSERT, SELECT ON platform.audit_records
  each tenant schema:   GRANT USAGE; GRANT INSERT, SELECT ON <schema>.audit_records
  → never granted UPDATE/DELETE anywhere  ⇒ append-only is physical for writes

tenant role (per tenant)
  <schema>.audit_records:  default privileges granted CRUD → REVOKE INSERT, UPDATE,
                           DELETE  (keep SELECT, for the viewer)  ⇒ read-only + no writes

platform_reader
  <schema>.audit_records:  default privileges granted SELECT → REVOKE SELECT
                           ⇒ tenant audit is readable only inside its own tenant
  platform.audit_records:  not granted (no in-app reader; Platform Admin lacks
                           VIEW_AUDIT_LOGS) — write-then-quiet compliance store
```

- **Honest scope of the guarantee:** physical append-only holds for **every role
  the app uses to touch audit** — `audit_writer` (writes) and the tenant roles
  (reads). The connected superuser/login role retains full rights but **no app code
  path ever issues `UPDATE`/`DELETE` on audit** (the service only `SET ROLE
  audit_writer` then `INSERT`s). This mirrors how the rest of the platform's
  guarantees are stated against the *roles the app runs as*.
- `audit_writer` writing into a tenant schema needs only `USAGE` + `INSERT`; it
  uses a **schema-qualified** insert (no `search_path` needed), schema name taken
  only from the registry whitelist.

### Interfaces

**Audit constants (`audit/records.py`) — pure**
```python
class EventType(StrEnum):
    AUTH_LOGIN = "auth.login"
    AUTH_LOGOUT = "auth.logout"
    PII_REVEALED = "pii.revealed"
    RECORD_CREATED = "record.created"
    PLATFORM_CROSS_TENANT_READ = "platform.cross_tenant_read"
    AUDIT_VIEWED = "audit.viewed"

class Outcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"        # DENIED = "denied" reserved (RBAC-denial auditing → deferred)
```

**Audit service (`audit/service.py`)**
```python
async def record_audit_event(
    *,
    tenant_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    actor_role: Role | None,
    event_type: EventType,
    outcome: Outcome,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    field_names: list[str] | None = None,
) -> None:
    """Write one append-only audit record to the tenant or platform store.

    Store rule: tenant_id present → <that tenant's schema>.audit_records;
    absent → platform.audit_records. Runs on its OWN session as `audit_writer`.
    Stores names, never values. Failures propagate (strict — see Decisions).
    """
```

**Filled seams (signatures unchanged — zero call-site churn)**
```python
# tenancy/scoping.py
async def record_platform_read_for_audit(identity: Identity) -> None:
    await record_audit_event(
        tenant_id=None,                       # tenantless Platform Admin → platform store
        actor_user_id=identity.user_id, actor_role=identity.role,
        event_type=EventType.PLATFORM_CROSS_TENANT_READ, outcome=Outcome.SUCCESS,
        entity_type="tenant_settings",
    )

# pii/reveal_seam.py
async def on_pii_revealed(identity, entity_type, entity_id, field_name) -> None:
    await record_audit_event(
        tenant_id=identity.tenant_id,
        actor_user_id=identity.user_id, actor_role=identity.role,
        event_type=EventType.PII_REVEALED, outcome=Outcome.SUCCESS,
        entity_type=entity_type, entity_id=entity_id, field_names=[field_name],
    )
```

**HTTP endpoint (`audit/router.py`)**
- `GET /api/audit` — `require_capability(VIEW_AUDIT_LOGS)` + `get_tenant_db`. Lists
  the caller's tenant's audit records newest-first via the schema-less `AuditRecord`
  (search_path scopes it). The response carries only metadata + `field_names` (no
  PII by construction). **Before returning**, it records its own `audit.viewed`
  (`entity_type="audit_records"`). Tenant Admin / Read-Only → 200; Agent → 403;
  anonymous → 401; Platform Admin → 403 (lacks the capability) — all inherited.

### Primary flows
```
Reveal (P1.3 path, now audited)
  POST /api/pii-demo/{id}/reveal {field:"email"}  [REVEAL_PII + get_tenant_db]
  value = decrypt_field(tenant_id, blob)
  await on_pii_revealed(identity, "pii_demo", id, "email")
     └─ record_audit_event(tenant_id=…, event_type="pii.revealed",
                           entity_type="pii_demo", entity_id=id, field_names=["email"])
        own session → SET LOCAL ROLE audit_writer →
        INSERT INTO <tenant_schema>.audit_records …   (names only; value never stored)
  ◀── 200 {field:"email", value:"…"}   # audit committed BEFORE the value returns

Cross-tenant read (P1.2 path, now audited)
  GET /api/platform/tenant-settings  [require_platform_admin → get_platform_db]
  inside get_platform_db txn (platform_reader): await record_platform_read_for_audit(identity)
     └─ record_audit_event(tenant_id=None, event_type="platform.cross_tenant_read")
        own session (independent connection) → audit_writer →
        INSERT INTO platform.audit_records …
  ◀── 200 {tenants:[…]}

Auth
  POST /api/auth/login (ok)  → record_audit_event(tenant_id=identity.tenant_id,
                                event_type="auth.login", outcome="success")
  POST /api/auth/login (bad) → record_audit_event(tenant_id=None, actor_user_id=None,
                                event_type="auth.login", outcome="failure")  # no PII
  POST /api/auth/logout      → resolve identity from cookie; if valid,
                                record_audit_event(event_type="auth.logout",
                                outcome="success") routed by its tenant_id

Record change (demonstrator)
  POST /api/pii-demo/ {…}  [CREATE_EDIT_RECORDS + get_tenant_db]
  …insert row… → record_audit_event(tenant_id=…, event_type="record.created",
       entity_type="pii_demo", entity_id=row.id,
       field_names=["display_name","email","phone","date_of_birth","mock_medicare_id"])
  ◀── 201 {record:{…masked…}}            # NAMES of written fields; never values

View audit (itself audited)
  GET /api/audit  [VIEW_AUDIT_LOGS + get_tenant_db]
  rows = SELECT … FROM audit_records ORDER BY occurred_at DESC     # tenant role, SELECT only
  await record_audit_event(event_type="audit.viewed", entity_type="audit_records")
  ◀── 200 {records:[… names/metadata only …]}   # a later view shows this view

Isolation: a Florida Tenant-Admin's GET /api/audit runs under tenant_florida +
  search_path=florida → only florida.audit_records; tenant_sunshine cannot SELECT
  florida.audit_records, platform_reader cannot SELECT either (REVOKEd), and no role
  the app uses can UPDATE/DELETE any audit row.
```

### Alembic / hygiene
- `0007_audit_records.py` is **hand-written** (role `DO` block + platform table +
  per-tenant tables via a registry loop + grants/REVOKEs), matching `0003`/`0006`
  style; `downgrade` drops per-schema tables, the platform table, revokes the
  membership, and drops the role.
- The existing `env.py` filter already excludes schema-less per-tenant tables, so
  `audit_records` does not surface as drift; `platform.audit_records` **is** in the
  metadata (`PlatformAuditRecord`, `schema="platform"`), so `alembic check` sees it
  normally and reports none.

## 6. Decisions

| # | Decision | Chosen | Alternatives considered | Rationale |
|---|---|---|---|---|
| 1 | **Store topology** | **Two stores** — schema-less `audit_records` per tenant schema + `platform.audit_records`; routed by a single rule (`tenant_id` present → tenant; else platform) | One central `platform.audit_records` with a `tenant_id` column for everything | Matches the isolation note ("audit records are tenant-scoped; platform cross-tenant reads logged separately"); tenant audit stays *physically* inside the tenant boundary, so the viewer inherits isolation for free and a tenant can never read another's audit. **Tradeoff to showcase** — see callout below. |
| 2 | **Write model** | **Dedicated `audit_writer` role on its own short-lived session** for every emit | Thread the request session through and write same-transaction; a `ContextVar` exposing the request session | The platform-read seam runs under read-only `platform_reader` and login runs before tenant scoping — no single request session works everywhere. The own-session writer gives **zero call-site churn** on the two frozen seams and one uniform path. Tradeoff: not atomic with the business txn (accepted — see Risks; P1.5's outbox is the atomic path for the *event*). |
| 3 | **Append-only enforcement** | **Physical** — `audit_writer` INSERT+SELECT only; tenant roles SELECT only (explicit `REVOKE` of the schema's default CRUD); no `UPDATE`/`DELETE` on any role the app uses | Application-only ("never write update/delete code"); a DB trigger rejecting UPDATE/DELETE | The project's signature move (enforce beneath the app, as schema-per-tenant does). A grant model is simpler than a trigger and provable: an `UPDATE`/`DELETE` raises `permission denied`. |
| 4 | **Ship a read endpoint now** | **Yes** — minimal guarded `GET /api/audit`, PII-free, self-auditing; UI deferred | Defer all reading to M4 | "Viewing audit is itself audited" needs a view path to exist and be testable now; mirrors P1.3 shipping `pii_demo` endpoints with the UI deferred. Gives M4 a ready backend. |
| 5 | **Record columns / "user"** | The requirements' named set + `field_names text[]`; store **`actor_user_id` + `actor_role`, not username** | Include `username`; add `correlation_id`/`demo_session_id` now | Username is an email (PII-ish); a user *reference* satisfies "user" while keeping audit PII-free. `correlation_id`/`demo_session_id` are added by their owning phases (P1.5/P1.8) — no speculative columns. |
| 6 | **Auth-event depth** | **login success + failure + logout**; defer RBAC-denied (403) auditing | Audit only success; also audit every 403 now | Login success/logout are attributable; failed login is a security-relevant auth event recorded to the platform store with **no identifying PII**. Auditing 403s needs guard/middleware emission — a larger lift; `outcome` reserves `denied`. |
| 7 | **Audit-write failure behavior** | **Strict** — failures propagate | Best-effort (swallow + log) | "Audit from day one": a sensitive op should not silently proceed unaudited. For create, a propagating audit error rolls the create back (consistent); for reveal, the value never returns. Best-effort-with-alerting is a future hardening (noted). |
| 8 | **`audit_writer` role name home** | **`registry.py` constant** (`AUDIT_WRITER_ROLE`), imported by migration + service | Hard-code the string in each | One source of truth for role names (mirrors `PLATFORM_ROLE`); migration and service can never disagree. |

> ### 🔎 Showcase / "How it's built" callout (per stakeholder request)
> The **store-topology decision and its tradeoffs** (Decision 1 + the
> write-model/atomicity tradeoff in Decision 2) are flagged as **explainer
> content** for the self-explaining demo — the "How it's built" page and the
> per-step explainers (shells land in **P1.6**, content matures through **M4
> P4.5**). The point to teach: *why audit is split into a tenant store and a
> platform store* (isolation inherited, tenant audit can't leak cross-tenant) and
> *why audit writes are append-only via a dedicated role on a separate session*
> (physical immutability; the deliberate non-atomicity tradeoff vs the P1.5 outbox
> that later makes the **event** twin exactly-once). Recorded in
> [Deferred_Features_Backlog.md](../Deferred_Features_Backlog.md) so it is not lost
> before the explainer phases.

## 7. Risks and Open Questions

- **Audit is not atomic with the business transaction (Decision 2).** The own-session
  writer commits independently. *Effect:* a narrow window where the audit row
  commits and the business txn's later commit fails leaves an orphan audit record
  (for create); for reveal/cross-tenant-read the action is a read that already
  happened in-process, so "audit the attempt" is the intended semantics. *Accepted:*
  the audit *record* store is append-only-from-day-one; the **event** twin gets
  exactly-once via the transactional **outbox in P1.5**. This is the showcase
  tradeoff (Decision 1/2 callout).
- **Strict failure can fail a user action if audit is down (Decision 7).** *Accepted*
  for an MVP "from day one" posture; a best-effort+alert mode is the future
  hardening. Tests run against a healthy substrate so this is deterministic.
- **A separate session opens while a request transaction is mid-flight** (reveal,
  cross-tenant read). *Mitigation:* the writer uses its **own** session/connection
  (the keys.py precedent), so it never reuses the request's scoped connection; the
  identifier is registry-validated before interpolation. Connection count is one
  extra short-lived connection per audited action — fine at demo scale; noted for
  M4 load review.
- **Default-privileges footgun.** A new tenant `audit_records` table is auto-granted
  CRUD to the tenant role and SELECT to `platform_reader`. *Mitigation:* the
  migration **explicitly `REVOKE`s** to leave the tenant role SELECT-only and remove
  `platform_reader` entirely; the acceptance suite proves the resulting permissions
  physically.
- **No raw PII in audit.** *Mitigation:* the only free-text payload is
  `field_names` (names by construction); the service has no parameter for a field
  *value*; an acceptance test asserts seeded/sentinel plaintext never appears in any
  audit row or in the `GET /api/audit` response.
- **`text[]` round-trip under asyncpg.** `field_names` is a Postgres array.
  *Mitigation:* bound list parameter; a DB round-trip test.
- **`logout` must resolve identity to attribute it.** *Mitigation:* resolve via the
  existing `get_session_identity` before revoking; an unresolved/absent session
  records nothing (a no-session logout is not an audit event).
- **Open (deferred, not blocking):** correlation to the `pii.revealed` event
  (`correlation_id`) → **P1.5**; demo-session tagging + purge → **P1.8**; RBAC-denial
  (403) auditing → future; richer per-target-tenant cross-tenant-read detail →
  future; seeded audit history for a non-empty cold-boot viewer → P1.8/M4; the
  viewer UI → **M4 (P4.2)**.

## 8. Rollout / Verification

**Manual verification (local stack)**
1. `docker-compose up` → boot runs `alembic upgrade head` (creates
   `platform.audit_records`, per-schema `audit_records`, the `audit_writer` role +
   grants) then `seed` (unchanged; no audit seeded).
2. Log in as a Sunshine Tenant Admin → `GET /api/audit` → `200` with at least the
   `auth.login` record for this session and the `audit.viewed` from the prior view;
   no unmasked PII anywhere in the body.
3. As a Sunshine Agent, `POST /api/pii-demo/{id}/reveal {field:"email"}` → `200`;
   then as the Tenant Admin `GET /api/audit` shows a `pii.revealed` record with
   `field_names:["email"]` and **no email value**.
4. As the Platform Admin, `GET /api/platform/tenant-settings` → `200`; the row lands
   in `platform.audit_records` (`event_type="platform.cross_tenant_read"`), **not**
   in any tenant store.
5. As an **Agent**, `GET /api/audit` → `403`; anonymous → `401`; Platform Admin →
   `403`.
6. `psql`: `UPDATE sunshine.audit_records …` / `DELETE …` as `tenant_sunshine` →
   `permission denied`; `SELECT … FROM florida.audit_records` as `tenant_sunshine`
   → `permission denied`.

**Automated verification (pytest, ephemeral Postgres)**
- **Constants (no DB):** event-type / outcome string values; field-name helper.
- **Migration/grants (substrate):** `audit_records` exists in every tenant schema
  and `platform.audit_records` exists; `audit_writer` has INSERT+SELECT and **lacks**
  UPDATE/DELETE; tenant role has SELECT only (INSERT/UPDATE/DELETE → `permission
  denied`); `platform_reader` cannot SELECT a tenant `audit_records`.
- **Service (DB):** `record_audit_event` with a `tenant_id` writes to that tenant
  schema; with `None` writes to platform; `field_names` round-trips as names;
  newest-first ordering by `occurred_at`.
- **Append-only acceptance:** an `UPDATE`/`DELETE` attempt under the tenant role and
  under `audit_writer` both raise `permission denied`.
- **Seams:** `record_platform_read_for_audit` writes one platform record;
  `on_pii_revealed` writes one tenant record with `field_names=[field]`
  (**`test_reveal_seam.py` updated** from the no-op assertion).
- **Auth wiring:** login success → `auth.login`/`success` in the tenant store (or
  platform store for the Platform Admin); bad login → `auth.login`/`failure` in the
  platform store with `actor_user_id` NULL and no PII; logout → `auth.logout`.
- **Record change:** `pii_demo` create writes `record.created` with the written
  **field names** and no values (assert seeded plaintext absent from the row).
- **Endpoint:** `GET /api/audit` — Tenant Admin/Read-Only 200, Agent 403, anonymous
  401, Platform Admin 403; tenant-A-vs-B isolation; the response carries no unmasked
  PII; **viewing writes an `audit.viewed`** (a second view sees the first).
- **Named acceptance (`test_audit_acceptance.py`):** a thin narrative — a sensitive
  op of each wired kind produces a record (names-not-values), append-only holds,
  tenant audit is tenant-only, and viewing-is-audited.
- **Migration health:** `alembic upgrade head` then `downgrade` round-trips;
  `alembic check` reports no drift (`platform.audit_records` reflected; schema-less
  `audit_records` excluded by the existing filter).

**Rollout / compatibility**
- No new runtime dependency and no new env var.
- Additive migration `0007` on top of `0006`; pre-go-live reset+reseed acceptable;
  reversible by reverting the migration + code.
- The two seams change from no-op to active; their behavior is additive (a record is
  written) and gated by the same paths that already reached them.
- Must stay green behind the pre-commit gate and CI before P1.5 begins.

## 9. Work Breakdown

Ordered simplest-first — pure constants, then the tables/role, then models, then the
service, then the physical-permission proof, then the seams, then the live wiring,
then the endpoint, then the acceptance proof. Each item is narrow and independently
reviewable (~150 lines · ~8 files).

1. **Audit constants (`audit/records.py`) + registry role name.** `EventType` /
   `Outcome` enums and any field-name helper (pure); add
   `AUDIT_WRITER_ROLE = "audit_writer"` to `registry.py`. Unit-tested; no DB.
2. **Migration `0007`: tables + role + grants.** `audit_writer` (idempotent `DO`
   block) + `GRANT audit_writer TO CURRENT_USER`; `platform.audit_records`;
   per-tenant `audit_records` via a registry loop + the `occurred_at` index; grants
   for `audit_writer`; **`REVOKE`** to tighten tenant role to SELECT-only and remove
   `platform_reader`. Substrate test: tables exist; grants/revokes as designed.
3. **ORM models (`models/audit_record.py`).** `PlatformAuditRecord`
   (`schema="platform"`) + schema-less `AuditRecord`; register in
   `models/__init__.py`. Drift check (`alembic check` clean).
4. **Audit service (`audit/service.py`).** `record_audit_event`: own
   `session_factory`, `tenant_id → schema` resolve + registry whitelist, `SET LOCAL
   ROLE audit_writer`, schema-qualified `INSERT`; strict failure. DB test: tenant vs
   platform routing; `field_names` round-trip; ordering. Add
   `container_audit_session_factory` to `conftest.py`.
5. **Append-only + isolation acceptance (DB).** `UPDATE`/`DELETE` denied for the
   tenant role and `audit_writer`; tenant role SELECT-only; tenant A cannot read
   tenant B audit; `platform_reader` cannot read tenant audit.
6. **Fill `record_platform_read_for_audit`.** Cross-tenant read writes one platform
   record; update its focused test.
7. **Fill `on_pii_revealed`.** Reveal writes one tenant record with
   `field_names=[field]`; **update `test_reveal_seam.py`** from the no-op assertion.
8. **Auth wiring (`auth/router.py`).** Emit `auth.login` (success/failure, failure
   PII-free) and `auth.logout` (resolve identity first). Tests.
9. **Record-change wiring (`pii_demo/router.py`).** Emit `record.created` with the
   written **field names**; test asserts no values present.
10. **Guarded read endpoint (`audit/router.py` + `schemas.py`).** `GET /api/audit`
    (`VIEW_AUDIT_LOGS` + `get_tenant_db`), newest-first, PII-free, **self-auditing
    `audit.viewed`**; mount in `main.py`. Endpoint tests: RBAC matrix; A-vs-B;
    viewing-is-audited; no PII.
11. **Named acceptance suite (`test_audit_acceptance.py`) + hygiene.** The phase's
    concise proof (each wired kind audited, names-not-values, append-only,
    tenant-scoped, viewing-is-audited); `alembic check`/downgrade round-trip; confirm
    CI green.
