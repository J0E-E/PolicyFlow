# PolicyFlow — Program & Phase Plan

> **Living document.** This is the source-of-truth build path that sits *above* the
> per-unit pipeline. Each **phase** below feeds the normal chain
> `1-prompt-to-brd` → `2-requirements-to-tdd` → `3-tdd-to-epic-plan` → the per-epic loop, with
> **one phase = one TDD = one epic plan**. It is opinionated and sequenced — an
> ordered build path, not a backlog — and edited **in place** as phases complete.
> The full behavioral spec is [PolicyFlow_Requirements.md](./PolicyFlow_Requirements.md);
> this doc only decides **order, decomposition, and what is faked when**.

---

## How to read this doc

PolicyFlow is a multi-tenant insurance **workflow-orchestration** platform with CRM
integrations, built as a production-minded portfolio MVP that walks a cold visitor
end-to-end in minutes and **explains its own engineering** as it goes.

**The program's central tension:** the requirements are deep and broad (workflow
state machines, four sidecars, field-level encryption, schema-per-tenant isolation, event-driven delivery,
a self-explaining demo) — and it is tempting to build them as horizontal layers
(all data models, then all services, then all UI). **We do the opposite.** Every
phase is a **vertical slice** that keeps the system runnable and deployable, and the
very first thing we build is not a feature at all — it is the *delivery path itself*
(Phase 0). Features only ever land on a system that is already live in production.

### Guiding principles

- **Skeleton first, features second.** Phase 0 proves push→build→deploy→live before
  a single domain feature exists. Foundations (auth, tenant isolation, encryption,
  audit, event bus) come next because they cannot be retrofitted.
- **Vertical slices, never horizontal layers.** Each phase is demoable by hand in a
  browser on the local stack. "Backend only" is never a phase.
- **Stubs behind real seams.** Phase 1 ships stub consumers *behind the same events*
  Phase 3 will serve for real, so the swap is invisible to the rest of the system.
- **Local/prod parity.** One Docker stack definition runs identically locally and on
  EC2. Dev *is* the local stack; there is no deployed dev environment.
- **Tenant isolation is the cross-cutting invariant.** Every phase carries an
  isolation note; no record, event, sidecar datum, or demo-session datum ever
  escapes its tenant — tenant-scoped data lives in a **per-tenant PostgreSQL schema**
  (one schema per tenant) and events carry `tenant_id` — and PII is protected
  end-to-end.
- **The demo is a feature, not packaging.** Explainers, badges, the stepper, and the
  "How it's built" page ship as first-class work, their shells in Phase 1.
- **Tests ship with every slice.** Every change updates the relevant FE/BE test cases,
  and a **pre-commit** gate runs the full suite on each commit and blocks on red — no
  epic is "done" with an absent or failing suite for the behavior it adds. The harness
  and gate are stood up in **P0.1a**.

---

## Decide Once, Decide Early

Expensive-to-retrofit decisions, frozen here as interfaces that later phases only
extend. (Cross-cutting; the stack choices were settled at TDD time for Phase 0.)

1. **Language/framework & topology** — React SPA (nginx-served) + Python/FastAPI for
   core and all four sidecars; sidecars are separate worker processes **in one repo**
   communicating over a real broker. *Committed by requirements.*
2. **Message broker — RabbitMQ.** Durable delivery, exchange-based fan-out, per-queue
   DLX/DLQ, management UI for queue depth. Every consumer is an independent
   subscription with its own retry + dead-letter. *Frozen P0; consumers added P1+.*
3. **Database — PostgreSQL.** Tenant isolation is **schema-per-tenant**: one schema
   per tenant for all tenant-scoped data, plus a shared `platform` schema for
   cross-tenant operational/aggregate and reference data. Each tenant schema is
   owned by / granted to a dedicated per-tenant DB role. **No RLS** — a per-tenant
   schema makes row-level policies redundant. *Frozen P0; tenant schemas land P1.*
4. **Tenant context is derived only from the authenticated session**, injected by
   middleware which sets the connection's `search_path` + tenant DB role for every
   query; the schema boundary enforces it beneath the app. Never from a request
   parameter. The platform-scoped path uses a platform role reading the shared
   `platform` schema (and, where sanctioned, across tenant schemas), and is audited.
   *Interface frozen now; enforced P1.*
5. **Event envelope shape** (`event_id`, `event_type`, `schema_version`, `tenant_id`,
   `occurred_at`, `correlation_id`, optional `causation_id`, `actor`, `demo_session_id`)
   and **at-least-once + idempotent consumers + no-guaranteed-ordering** semantics.
   *Frozen P1; honored by every consumer thereafter.*
6. **Transactional outbox** as the publish mechanism so events are never lost relative
   to committed state. *Pattern frozen P1.*
7. **PII model** — field-level (application-layer) encryption with **HMAC blind index**
   for email/phone, envelope encryption (per-tenant data key under an env-supplied
   master key), masking-by-default with audited click-to-reveal. *Frozen P1.*
8. **Adapter boundaries** — `AuthProvider`, `CRMAdapter` (→ `MockCRMAdapter`),
   enrichment/quote/notification behind events. *Seams declared P1, real impls P3.*
9. **Demo-session model** — `demo_session_id` tag on visitor records, layered over
   shared read-only seed data, session-scoped controls, 24h expiry purge across core
   and sidecar stores. *Frozen P1.*
10. **Deploy mechanics** — push to `main` → CodePipeline → CodeBuild→ECR → CodeDeploy
    pulls on EC2; migrations + seed run as deploy steps (Alembic); TLS via Let's
    Encrypt/certbot at nginx; all AWS via Terraform; secrets in SSM Parameter Store.
    *Frozen P0.*
11. **Test tooling & commit gate** — `pytest` (+ `httpx`, `pytest-asyncio`) for core and
    sidecars, Vitest + Testing Library for the SPA, orchestrated by the **pre-commit**
    framework as the commit gate; the same suites run in CI. Stood up in **P0.1a**; every
    later phase only adds cases behind it. *Frozen P0.1a.*

---

## Spec reconciliations

Early simplifications are **sequencing decisions, not deviations** — each names when
the fuller element comes online.

- **Placeholder pages (P0)** become the real Landing/Tenant-Selection in **P1.6**.
- **Stub enrichment + sync-logger consumers (P1.5)** are replaced by the real
  Enrichment and CRM Sync services in **M3**, behind the identical events.
- **Stubbed quote generation (P2.3)** becomes the real Carrier Quote service in **M3**.
- **Minimal DLQ list (P3.5)** becomes the full integration-health dashboard in **M4**.
- **Empty baseline migration (P0)** gains the real domain schema incrementally from
  **P1** onward.

---

## The Phase Plan

Milestones map to the requirements' Phase 0–4 and to the `phase-<n>/` folders.
Phases carry stable IDs `P<milestone>.<n>` used as the TDD/epic-plan filename prefix.
**Horizon rule:** Milestone 0 (current) and Milestone 1 (next) are planned in detail;
Milestones 2–4 are deliberate **sketches** (ID + one-line goal + acceptance) that earn
a full design pass when they come into view — do not mistake a sketch for an
under-specified plan.

### Milestone 0 — Walking Skeleton & Deployment Pipeline `◄`

#### P0.1 — Walking Skeleton & Deployment Pipeline ◄ — **COMPLETE**

- **Goal:** Prove the entire delivery path — code pushed to GitHub builds and deploys
  to production with zero manual steps — and stand up the full container topology
  before any feature exists.
- **Shippable outcome / acceptance:** **Exit test** — a trivial change pushed to
  `main` appears at `https://policyflow.joeyshub.com` with no manual steps. The same
  Docker stack (nginx, frontend SPA shell, FastAPI core placeholder, RabbitMQ,
  PostgreSQL) runs locally via a single command, fully wired; placeholder landing +
  tenant-selection pages render over HTTPS in prod.
- **Key components:** repo + `docker-compose` stack; nginx reverse proxy + TLS
  (certbot); React SPA shell; FastAPI core skeleton (`/health`); RabbitMQ + Postgres
  containers; Alembic wired with empty baseline + deploy-time migrate/seed hook;
  Terraform for all AWS (EC2, VPC/SG, IAM, Route 53 record, ECR, CodePipeline/
  CodeBuild/CodeDeploy, SSM params); CI/CD push→ECR→deploy.
- **Faked / deferred:** landing/tenant-select **content** (real pages → **P1.6**);
  domain schema (→ **P1**); auth/RBAC (→ **P1.1**); event consumers (→ **P1.5**);
  real seed data (→ **P1.8**).
- **Depends on:** none.
- **Isolation note:** no tenant data exists yet; the *mechanisms* that will enforce
  isolation are scaffolded — Postgres provisioned (schema-per-tenant ready, shared
  `platform` schema reserved), per-tenant key material design reserved, secrets kept
  in SSM out of repo/state.
- **Why now / what this de-risks:** retires the single biggest delivery risk (can we
  ship hands-off to a parity environment at all?) before any feature investment.
- **Size:** L (infra-heavy, mostly one-time).
- **Status:** **COMPLETE** (2026-06-12). All 12 epics done; the exit test passed live
  — a push to `main` reached `https://policyflow.joeyshub.com` over valid HTTPS with
  zero manual steps, cert self-issued on deploy. Risks #1 and #2 retired. The
  end-to-end run surfaced 8 glue/hardening fixes, all captured in the P0.1 epic plan
  (Epic 12 notes, `./phase-0/epic-plan-P0.1-walking-skeleton.md`) and recorded in
  `../ops/exit-test-runbook.md` → "Record the run".

#### P0.1a — Test harness & commit gate — **COMPLETE**

- **Goal:** Stand up the automated FE/BE test harness and a **pre-commit** gate so that,
  from here on, every phase ships with test cases that are updated and run on every commit.
- **Shippable outcome / acceptance:** `pytest` runs core's suite (starting with the
  `/api/health` **ok** and **degraded** paths) and Vitest runs the SPA suite (a smoke
  test until the real React components land in P0.1 Epics 4–5); a **pre-commit** hook
  runs both and **blocks the commit on any failure**; the same suites run in CI. A
  deliberately broken test fails the commit — proving the gate is live, not decorative.
- **Key components:** `pytest` (+ `httpx`, `pytest-asyncio`) under `core/`; Vitest +
  Testing Library config under `frontend/`; `.pre-commit-config.yaml` wiring both; a CI
  step running the suites; and a short `TESTING.md` stating the standing rule —
  **every change updates the relevant test cases and the suite must be green to commit.**
- **Faked / deferred:** real FE component tests (arrive with Epic 4–5 and P1.6+);
  tenant-isolation / PII-masking fixtures (→ P1.2 / P1.3); end-to-end browser tests
  (→ later, as UI surfaces land).
- **Depends on:** P0.1 (Epic 2 provides the first backend surface to test). Does **not**
  gate the P0.1 exit test, but should be green before Milestone 1 feature work begins.
- **Isolation note:** no tenant data exists yet; the harness is structured so
  tenant-scoping and masking assertions slot in from P1.2/P1.3 onward.
- **Why now:** retrofitting a test culture after features exist is the same trap as
  retrofitting isolation — cheap to establish now, painful later.
- **Size:** S.
- **Status:** **COMPLETE** (2026-06-12). All 9 epics done. Backend `pytest` (5 passed:
  health ok + three degraded combos + harness) and frontend Vitest (2 passed: `<App>`
  smoke + harness) both green; the blocking `pre-commit` gate runs both on every commit
  and a deliberately broken test was proven to reject the commit (Epic 9). The same two
  suites mirror in CodeBuild `pre_build` and GitHub Actions (`.github/workflows/tests.yml`);
  the standing rule is documented in `../../TESTING.md`. Milestone 0 is now fully done.

### Milestone 1 — Foundations & Core Platform

Foundations precede all feature work. Planned in detail (next milestone). Phases are
ordered so the system stays runnable/deployable after each.

#### P1.1 — Authentication & RBAC — **COMPLETE**

- **Goal:** Username/password auth behind a pluggable `AuthProvider`; fixed
  server-side RBAC enforced on every API request.
- **Shippable outcome / acceptance:** seeded users can sign in; each role's
  capability matrix is enforced server-side and verifiable by test; unauthorized
  calls are rejected.
- **Key components:** `AuthProvider` interface, session/JWT issuance, user model with
  external-identity field, RBAC middleware + capability matrix.
- **Faked / deferred:** OIDC flow (out of scope); role switcher UI (→ P1.6).
- **Depends on:** P0.1.
- **Isolation note:** auth establishes the session that is the *only* source of
  tenant context; RBAC checks run before any data access.
- **Why now:** every later endpoint needs enforcement from day one.
- **Size:** M.
- **Status:** **COMPLETE** (2026-06-12). All 14 epics shipped behind a green gate
  (core suite **95 passed** on the real ephemeral-Postgres substrate). Acceptance met:
  the nine seeded personas sign in (`POST /api/auth/login` → `pf_session` cookie); the
  role→capability matrix is enforced server-side (`require_capability`) and verified
  cell-by-cell and end-to-end (Tenant-Admin-only `GET /api/tenant/config` returns 200,
  every other role 403, anonymous 401); unauthorized calls are rejected. Auth lives
  behind the pluggable `AuthProvider` seam (`LocalPasswordAuthProvider`); sessions are
  opaque tokens stored only as SHA-256 hashes. The DB-backed suite runs inside the CI
  gate (GitHub Actions + CodeBuild, Docker-in-job). Epic plan:
  `./p1.1/epic-plan-P1.1-auth-and-rbac.md`. One out-of-scope migration bug (generic
  `sa.Enum` vs PG `ENUM` double `CREATE TYPE`) was surfaced and fixed by the Epic 11
  real-DB substrate — exactly what it exists to catch.

#### P1.2 — Tenant scoping (schema-per-tenant) — **COMPLETE**

- **Goal:** one PostgreSQL schema per tenant + a shared `platform` schema; tenant
  context injected by middleware (session-set `search_path` + per-tenant DB role);
  Platform Admin carve-out path.
- **Shippable outcome / acceptance:** automated test proves a Tenant A user cannot
  read/modify any Tenant B record through any endpoint; cross-tenant platform reads
  go through the dedicated path and are audited.
- **Key components:** per-tenant schemas + DB roles, scoping middleware (search_path),
  shared `platform` schema, platform-scoped role/path, per-schema Alembic migrations.
- **Faked / deferred:** platform health UI (→ M4).
- **Depends on:** P1.1.
- **Isolation note:** this phase *is* the isolation backbone.
- **Why now:** retrofitting tenant scoping after features exist is intractable.
- **Size:** M.
- **Status:** **COMPLETE** (2026-06-13). All 9 epics shipped behind a green gate (core
  suite **135 passed** on the ephemeral-Postgres substrate). Acceptance met: the
  isolation suite (`test_isolation_acceptance.py`) proves a Tenant A user cannot read
  or modify any Tenant B record — both at the DB layer (a per-tenant role is *physically*
  denied another tenant's schema: SELECT/UPDATE/INSERT raise `permission denied`, own
  schema still reads) and over HTTP (A-vs-B across every endpoint, values never cross);
  cross-tenant reads go only through the sanctioned platform path
  (`GET /api/platform/tenant-settings` behind `require_platform_admin` + `get_platform_db`),
  with a named `record_platform_read_for_audit` seam already `await`ed on that path —
  **emission deferred to P1.4 (Audit logging)** per sequencing. The isolation backbone:
  per-tenant schemas + dedicated roles + a shared `platform` schema (migration `0003`),
  a `tenant_settings` demonstrator created per-schema (`0004`), the registry as single
  source of truth (`tenancy/registry.py`), the per-request `get_tenant_db` dependency
  (`SET LOCAL ROLE` + `SET LOCAL search_path`, reset at transaction end with a proven
  no-leak across pooled connections), and the Alembic schema-filter hygiene that keeps
  the drift gate clean against migration-owned tenant schemas (closes the P1.1 Epic-2
  caveat). Epic plan: `./p1.2/epic-plan-P1.2-tenant-scoping.md`.

#### P1.3 — Field-level encryption, blind index & masking  — **COMPLETE**

- **Goal:** Application-layer field encryption, HMAC blind index for email/phone,
  envelope encryption, masking-by-default render layer.
- **Shippable outcome / acceptance:** PII columns are encrypted at rest; exact-match
  duplicate lookup works via blind index without decryption; masked rendering is the
  default; derived `age_band` stored in plaintext.
- **Key components:** envelope encryption (per-tenant data key under env master key),
  blind-index helper, encrypt/decrypt model layer, masking utilities.
- **Faked / deferred:** audited click-to-reveal UI wiring depends on P1.4 + P1.6.
- **Depends on:** P1.2.
- **Isolation note:** per-tenant data keys reinforce isolation; no raw PII in logs.
- **Why now:** the PII shape constrains the schema; must precede domain entities.
- **Size:** M.
- **Status:** **COMPLETE** (2026-06-14). All 13 epics shipped behind a green gate
  (full backend suite **230 passed**; the P1.3 surface re-verified here at **96 passed**
  plus one known DinD asyncpg connection-timeout flake that passes on isolated re-run).
  Acceptance met and **Risk #3 retired**: the named acceptance suite
  (`test_pii_acceptance.py`) proves PII is ciphertext at rest (raw `*_encrypted` bytea
  never contains the seeded plaintext), exact-match duplicate lookup runs via the HMAC
  blind index **without decryption** under the real per-tenant role (`SET LOCAL ROLE`
  equality query), one tenant's ciphertext cannot be decrypted with another tenant's key
  (per-tenant subkey + tenant-id AAD), masking is the default on every read, and
  `age_band` is plaintext. Envelope encryption is in place — per-tenant root keys wrapped
  under the env `PII_MASTER_KEY` in `platform.tenant_data_keys` (migration `0005`,
  login-role-only read), HKDF-derived encryption + blind-index subkeys cached per process;
  the `pii_demo` demonstrator (migration `0006`) carries every field treatment behind
  masked write/read (`POST`/`GET /api/pii-demo`), blind-index lookup
  (`POST /api/pii-demo/lookup`), and a capability-gated reveal
  (`POST /api/pii-demo/{id}/reveal`, `REVEAL_PII`) whose `on_pii_revealed` seam is a
  no-op until P1.4. **Deferred per plan:** audited click-to-reveal UI wiring (needs P1.4
  audit + P1.6 shell). Epic plan: `./p1.3/epic-plan-P1.3-field-encryption-blind-index-masking.md`.

#### P1.4 — Audit logging — **COMPLETE**

- **Goal:** Append-only audit emission from day one for sensitive operations.
- **Shippable outcome / acceptance:** user actions, record changes, auth events, PII
  reveals, and cross-tenant reads write append-only audit records (field *names*,
  never raw PII); viewing audit is itself audited.
- **Key components:** audit record model, emission hooks, `pii.revealed` path.
- **Faked / deferred:** audit viewer UI (→ M4).
- **Depends on:** P1.2 (and P1.3 for reveal semantics).
- **Isolation note:** audit records are tenant-scoped; platform cross-tenant reads
  logged separately.
- **Size:** S–M.
- **Status:** **COMPLETE** (2026-06-15). All 11 epics shipped behind a green gate
  (full backend suite **280 passed**). Acceptance met: a sensitive op of each wired
  kind writes an append-only audit record carrying field *names*, never values —
  `auth.login` (success/failure, failure PII-free in the platform store), `auth.logout`,
  `record.created` (`pii_demo` create), `pii.revealed` (field name only),
  `platform.cross_tenant_read`, and `audit.viewed`; viewing audit is itself audited.
  Two physical stores — `platform.audit_records` + a per-tenant `audit_records` in every
  tenant schema (migration `0007`) — are made **append-only by grant**: the dedicated
  `audit_writer` role holds INSERT+SELECT only (UPDATE/DELETE physically denied), tenant
  roles are SELECT-only on their own audit and denied another tenant's, and
  `platform_reader` cannot read any tenant audit — all proven by live `permission denied`
  execution (`test_audit_append_only_acceptance.py`). The audit-emit service
  (`audit/service.py`) opens its own short-lived `audit_writer` session and routes by
  `tenant_id` (present → that schema; `None` → platform). Both P1.2/P1.3 seams are now
  filled: `record_platform_read_for_audit` (Epic 6) and `on_pii_revealed` (Epic 7). The
  guarded `GET /api/audit` (Epic 10) is `VIEW_AUDIT_LOGS`-gated, tenant-scoped, PII-free,
  and self-audits before responding. Named acceptance suite `test_audit_acceptance.py`;
  `alembic check` drift-clean + `0007` down/up round-trip green. Epic plan:
  `./p1.4/epic-plan-P1.4-audit-logging.md`. **Faked / deferred per plan:** audit viewer
  UI (→ M4). **Next move:** **P1.5 (Event bus + envelope + stub consumers)**.

#### P1.5 — Event bus + envelope + stub consumers — **COMPLETE**

- **Goal:** Broker wiring, event envelope, transactional outbox, and inline **stub**
  consumers (enrichment stub with canned results, sync-logger stub) behind the same
  events M3 will serve.
- **Shippable outcome / acceptance:** `lead.created` (and early events) publish via
  outbox; stubs consume idempotently; queue depth observable; correlation IDs flow.
- **Key components:** RabbitMQ topology (exchanges, per-consumer queues, DLX), outbox
  publisher, envelope schema, idempotent stub consumers.
- **Faked / deferred:** real sidecars (→ M3); notification surfaces (→ M3).
- **Depends on:** P1.2.
- **Isolation note:** every event + queue message carries `tenant_id`; consumers
  scope by it.
- **Size:** M.
- **Status:** **COMPLETE** (2026-06-15). All 11 epics shipped behind a green gate
  (full backend suite **347 passed**). Acceptance met: the named acceptance suite
  (`test_event_bus_acceptance.py`) proves the whole contract end-to-end on the real
  Postgres + RabbitMQ substrate — a `pii_demo` create enqueues a `record.created`
  outbox row, the polling relay publishes it, **both** stub consumers
  (`enrichment.stub`, `sync.logger`) receive it (fan-out) and each writes exactly
  **one** `processed_events` row, `correlation_id` + `tenant_id` flow through
  unchanged, a relay re-publish (crash between publish and mark) is still consumed
  **once** (idempotent on `(consumer_name, event_id)`), a poison message dead-letters
  into `enrichment.stub.dlq`, and `outbox`/`processed_events` stay per-tenant isolated.
  The seam M3's real sidecars bind to is in place: a durable topic exchange +
  per-consumer durable queues + per-queue DLX/DLQ derived from
  `catalog.CONSUMER_BINDINGS` (`broker.py`); the per-tenant transactional `outbox` +
  `processed_events` tables (migration `0008`, with dedicated `outbox_relay` /
  `event_consumer` roles); the transactional `enqueue_event`; the own-session polling
  relay (publish-before-mark, at-least-once via `published_at IS NULL`); the two
  idempotent terminal stubs (nack-without-requeue to the DLQ); the `event_bus_lifespan`
  runtime wiring (bounded-retry connect, relay task + one consumer task per stub); the
  two real triggers (`record.created` on create, `pii.revealed` on reveal — both riding
  the request transaction, never carrying a PII value); and queue depth browsable via
  the dev-only RabbitMQ management UI (Epic 10). **Validation fix:** marking the phase
  complete surfaced that the full backend suite was red *as a whole* — three Epic-5
  `test_relay.py` tests keyed on global published counts / "the next message on the
  queue", which broke once Epic 8 made every create enqueue an outbox row that later
  relay sweeps drain on the shared, never-reset container; remade event-pinned (assert
  `>= 1`, find the message by `message_id`), the idiom the Epic 11 acceptance suite
  already uses, so the full suite is green. **Faked / deferred per plan:** real sidecars
  + notification surfaces (→ M3). Epic plan:
  `./p1.5/epic-plan-P1.5-event-bus-envelope-stub-consumers.md`. **Next move:** **P1.6
  (Demo shell)**.

#### P1.6 — Demo shell `[UI]` — **COMPLETE**

- **Goal:** Real landing + tenant-selection, branding, **two-surface demo model
  (Shopper site ↔ Agent workspace) with a persistent surface toggle**, demo access
  model + staff-only role switcher, guided-stepper shell (prefill row +
  scenario-reference panel), explainer shell, "Simulated" badge component, "How it's
  built" page shell.
- **Shippable outcome / acceptance:** a visitor lands, reads orientation, picks a
  tenant, is dropped into the Agent workspace signed in as a seeded Agent, can switch
  roles, and can toggle to the consumer-facing Shopper site and back; stepper +
  explainer shells render.
- **Depends on:** P1.1 (auth/role), P0.1 (SPA shell).
- **Isolation note:** role switcher changes identity, not enforcement; RBAC stays
  server-enforced per assumed role. The surface toggle changes *surface*, not identity
  — the Shopper site is unauthenticated and carries no RBAC role.
- **Size:** L (split likely at epic-plan time; keep UI-bearing epics isolated).
- **Status:** **COMPLETE** (2026-06-19). All 24 epics shipped behind a green gate
  (full backend suite **369 passed** on the real Postgres + RabbitMQ substrate; full
  frontend suite **179 passed** across 27 files; `tsc -b && vite build` clean). The
  phase split into three layers as planned — access-model skeleton (1–5), design system
  + app shell (6–13), demo surfaces (14–21) — plus the **2026-06-17** two-surface
  refinement appended as Epics 23–24 (Shopper shell + persistent surface toggle) with a
  brand-color seed cleanup (Epic 22) between. Acceptance met end-to-end: a visitor lands
  and reads orientation (Epic 14), picks a tenant (`GET /api/tenants` Epic 1 → branded
  select-tenant Epic 15), is dropped into the Agent workspace signed in as a seeded Agent
  (passwordless `POST /api/demo/assume-persona` Epic 2 → guarded `/app` Epic 5 → branded
  masthead Epic 10 → demo home Epic 16), can switch roles via the masthead switcher with
  Platform-Admin inversion (Epic 11), and can toggle to the unauthenticated Shopper site
  and back carrying the session + tenant (Epics 23–24); the guided-stepper docket
  (Epic 17), scenario-reference panel (Epic 18), explainer popovers (Epic 19), "Simulated"
  badge (Epic 20), and public "How it's built" page (Epic 21) all render. The
  **tenant-isolation / PII invariant held throughout**: the role switcher changes
  *identity* not enforcement (RBAC stays server-enforced per assumed real seeded user);
  the surface toggle changes *surface* not identity (the Shopper site is unauthenticated
  and carries no RBAC role); the seed password never reaches the browser and no PII
  crosses the new surfaces. The design system was built first-principles to the UI/UX
  Guide (tokens + IBM Plex Mono, Button/Card/StampTag/Popover primitives, the
  branded persona-aware app shell). One dependency reversal recorded mid-phase
  (`iconoir-react` adopted in Epic 11, superseding the TDD's "no icon system"). Epic plan:
  `./p1.6/epic-plan-P1.6-demo-shell.md`. **Faked / deferred per plan:** the real public
  intake form drops onto the Shopper buyer-home seam in **P1.7**; durable, session-aware
  stepper progress in **P1.8** (in-memory for now); audit-viewer / dashboards in **M4**;
  the live demo-session countdown in **P1.8** (static "DEMO SESSION" stamp for now). **Doc
  debt (non-blocking):** the P1.6 TDD §5.2/§5.4 + Decision 7 + Work Breakdown still
  describe only the single `/app` workspace — they predate the two-surface refinement and
  need a sync pass (the program plan + requirements already reflect it). **Next move:**
  **P1.7 (Lead intake, queue, qualification & duplicate detection `[UI]`)**.

#### P1.7 — Lead intake, queue, qualification & duplicate detection `[UI]` — **COMPLETE**

- **Goal:** **Two intake routes behind the same `lead.created` event** — self-service
  on the public Shopper surface (validation + abuse controls; lands unassigned) and
  agent-entered in the Agent workspace (authenticated, `CREATE_LEAD`; born owned by the
  entering agent) — plus unassigned queue + claiming, qualify/reject, deterministic
  duplicate detection + resolution.
- **Shippable outcome / acceptance:** walkthrough steps 3–6 demoable on the local
  stack via **either** route (the stepper describes both up front; the demoer picks);
  a self-service lead lands in the queue and is claimed, an agent-entered lead is born
  owned; duplicate-bait flags and resolves; both routes drive identical downstream.
- **Depends on:** P1.3 (blind index), P1.5 (events), P1.6 (shell + surface toggle).
- **Isolation note:** the self-service route is an unauthenticated write —
  rate-limited, honeypot, schema-validated; the agent-entered route is behind session +
  RBAC; every submission tied to a demo session and tenant.
- **Size:** L.
- **Status:** **COMPLETE** (2026-06-20). All 22 epics shipped behind a green gate (full
  backend suite **512 passed** on the real Postgres + RabbitMQ substrate; full frontend
  suite **270 passed** across 38 files; `tsc -b && vite build` clean). Built simplest-first:
  pure vocabulary + unit-testable building blocks (Epics 1–6), the first end-to-end
  agent-intake slice (7), the public-route stack (8–10), reads + actions (11–15), the minimal
  seed (16), the frontend data layer + four UI surfaces (17–21), and the named acceptance
  suite (22). Acceptance met end-to-end: both intake routes ride the identical `lead.created`
  event through one shared `create_lead` core — self-service `POST /api/public/intake` lands a
  lead `New`/unowned/`public_form` (rate-limited, honeypot, strict validation, sanitized
  `{"ok": true}` response) and agent-entered `POST /api/leads` is born `Working`/owned/
  `agent_entered`; the unassigned queue + one-click claim (`New → Working`, `lead.assigned`),
  qualify/reject (`Working → Qualified|Rejected` + events), deterministic duplicate detection
  via the P1.3 blind index (email-OR-phone, oldest-wins, no decryption) with agent resolution
  (link / new / reject), and audited click-to-reveal over masked-by-default reads all work; a
  minimal per-tenant seed keeps the queue non-empty and makes the Jordan-Rivera duplicate-bait
  flag and resolve. The named acceptance suite (`test_lead_intake_acceptance.py`) proves the
  genuinely-missing end-to-end lifecycle on the real substrate plus the one physical proof the
  lead path lacked — under a switched per-tenant role, a cross-tenant `leads`
  SELECT/UPDATE/INSERT is `permission denied` while own-schema reads succeed — and that the
  live intake endpoint flags a duplicate on the blind index alone (decrypt patched to fail).
  **Tenant-isolation / PII invariant held throughout.** Epic plan:
  `./p1.7/epic-plan-P1.7-lead-intake-queue-qualification-duplicate-detection.md`. **Faked /
  deferred per plan:** the full per-tenant seed + demo-session lifecycle/purge (**P1.8**); the
  per-record event timeline (**P1.9**). **Next move:** **P1.8 (Seed data, demo-session
  lifecycle & reset)**.

#### P1.8 — Seed data, demo-session lifecycle & reset

- **Goal:** Per-tenant seed data, demo-session sandboxing + tagging, 24h expiry purge,
  nightly reset, session indicator + graceful expired-session handling.
- **Shippable outcome / acceptance:** dashboards/lists render non-trivially from seed
  alone; concurrent visitors never collide; expired sessions degrade gracefully.
- **Depends on:** P1.2, P1.7.
- **Isolation note:** session records layered over shared read-only seed; purge
  cascades across core and (later) sidecar stores by `demo_session_id` + `tenant_id`.
- **Size:** L.

#### P1.9 — Per-record event timeline `[UI]`

- **Goal:** Live-updating per-record event timeline on the lead detail view.
- **Shippable outcome / acceptance:** lead detail shows each domain event + stub
  reaction with status/timestamps, updating live.
- **Depends on:** P1.5, P1.7.
- **Isolation note:** timeline reads scoped to the record's tenant.
- **Size:** M.

### Milestone 2 — Domain Workflow *(sketch — earns full design pass at M2 start)*

- **P2.1 — Lead conversion** — one-transaction Contact + Household + one Opportunity
  per product line; Lead frozen. *Accept: walkthrough step 7.*
- **P2.2 — Opportunity pipeline & product rules `[UI]`** — canonical stage machine,
  Medicare eligibility gate, beneficiary/health steps, pipeline value fields.
  *Accept: steps 8.*
- **P2.3 — Quotes → Application → Policy** — stubbed quote gen, quote-selection
  creates Application, application lifecycle, policy creation, masked Medicare ID.
  *Accept: steps 9–12.*
- **P2.4 — Renewals & cross-sell** — anniversary job + AEP sweep + demo time controls;
  cross-sell prompt. *Accept: step 15.*
- **P2.5 — Timeline + correlation trace extension `[UI]`** — timeline on
  opportunities/policies + end-to-end trace view. *Accept: step 20.*

### Milestone 3 — Integration Sidecars *(sketch)*

Real services replace P1–P2 stubs behind the same events.

- **P3.1 — CRM Sync service** — tenant field mappings + side-by-side viewer, external-ID
  upsert correlation, retry, DLQ, replay, failure simulation. *Accept: steps 13–14.*
- **P3.2 — Enrichment service** — consumer-data outputs, quality score, eligibility flag.
- **P3.3 — Carrier Quote service** — carrier mapping table, real async quotes.
- **P3.4 — Notification service `[UI]`** — notification center + simulated outbox.
  *Accept: step 16.*
- **P3.5 — Minimal DLQ list `[UI]`** — replay/discard actions (full dashboard → M4).

### Milestone 4 — Observability & Polish *(sketch)*

- **P4.1 — Funnel + integration-health dashboards `[UI]`** + platform health page.
  *Accept: step 19.*
- **P4.2 — Audit log viewer `[UI]`.** *Accept: step 17.*
- **P4.3 — Pipeline value by stage + opportunity sorting `[UI]` [SHOULD]`.**
- **P4.4 — Inbound CRM webhook demo control [SHOULD]`.**
- **P4.5 — Demo polish: guided-demo refinement + "5-minute highlights" path
  [SHOULD]`.**

---

## Build Order at a glance

```text
M0  P0.1 ✓ Walking Skeleton & Pipeline        (exit test PASSED 2026-06-12 — gate cleared)
        → P0.1a ✓ Test harness & commit gate   (tests + pre-commit gate live from here on)
        |
M1  P1.1 ✓ Auth/RBAC → P1.2 ✓ Tenant schemas → P1.3 ✓ Encryption → P1.4 ✓ Audit
        → P1.5 ✓ Event bus+stubs → P1.6 ✓ Demo shell [UI]
        → P1.7 ✓ Intake/queue/qualify/dup [UI] → P1.8 Seed+sessions → P1.9 Timeline [UI]
        |
M2  P2.1 Conversion → P2.2 Pipeline [UI] → P2.3 Quote→App→Policy
        → P2.4 Renewals+cross-sell → P2.5 Timeline/trace [UI]
        |
M3  P3.1 CRM Sync → P3.2 Enrichment → P3.3 Carrier Quote
        → P3.4 Notification [UI] → P3.5 DLQ list [UI]
        |
M4  P4.1 Dashboards [UI] → P4.2 Audit viewer [UI] → P4.3–P4.5 [SHOULD]
```

**Hard-sequential chains:** P0.1 gates all. Within M1, P1.1→P1.2→P1.3 are strictly
ordered (each builds the next's substrate); P1.5 needs P1.2; UI phases (P1.6/P1.7/P1.9)
need their backend substrate.

**Go/no-go gates (`◄`):** **P0.1 exit test** — if a push does not reach prod hands-off,
STOP and fix the pipeline before any feature work (the whole program's premise).

**Scope-boxed spikes:** none required up front; the stack is committed. Treat any
Terraform/CI surprise during P0.1 as a finding to record, not a re-architecture.

---

## Dependency / Integration map

- **M0 → everything:** P0.1 produces the running stack + pipeline every later phase
  deploys onto. Intentionally *throwaway* in P0.1: landing/tenant-select content,
  the empty baseline migration. *Permanent:* the Docker topology, Terraform, CI/CD,
  nginx/TLS, Alembic + deploy hook.
- **M1 internal:** auth→scoping→encryption→audit form the security spine; the event
  bus + stubs (P1.5) are the seam M3 plugs into unchanged. UI phases (P1.6/1.7/1.9)
  parallelize *after* their backend substrate lands, and are kept as isolated
  `[UI]` epics so `frontend-design` can fully own them.
- **M1 → M3:** stub consumers and the quote stub are the **merge-friction seams** —
  M3 swaps implementations behind identical events; if the envelope/contract held,
  the swap touches no caller.
- **M2 → M4:** dashboards/audit-viewer/trace read from the metrics read model and
  audit store built incrementally in M1–M2; M4 is mostly read-side UI over existing
  events.

---

## Risk register & checkpoints

| # | Riskiest unknown | Retired by | Kill / pivot criteria (falsifiable) |
|---|---|---|---|
| 1 | Hands-off push→prod on parity infra | P0.1 exit test ✓ **retired 2026-06-12** | If a push to `main` does not reach `policyflow.joeyshub.com` with zero manual steps, halt feature work until fixed. |
| 2 | TLS at nginx on a single EC2 without an ALB | P0.1 ✓ **retired 2026-06-12** (certbot issued; no ALB needed) | If certbot cannot issue/renew for the host, fall back to ACM+ALB and accept the added cost/infra. |
| 3 | Schema-per-tenant + app-layer encryption coexisting without breaking blind-index search | P1.3 ✓ **retired 2026-06-14** | If blind-index exact-match can't run within a tenant schema, revisit per-tenant key derivation before building intake. |
| 4 | Stub→real sidecar swap staying invisible | P1.5 / M3 | If M3 cannot replace a stub without changing callers, the envelope contract was wrong — fix the contract, not the callers. |
| 5 | Demo-session purge cascading across core + sidecar stores | P1.8 / M3 | If session purge leaves orphaned sidecar records, tighten the `demo_session_id` propagation before M4. |

---

## Reuse & build-vs-buy strategy

- **Lean on existing:** RabbitMQ (broker + management UI + DLX), PostgreSQL schemas + roles,
  SQLAlchemy + Alembic, FastAPI, AWS managed CI/CD (CodePipeline/Build/Deploy), ECR,
  SSM Parameter Store, certbot/Let's Encrypt, Terraform.
- **Buy/adopt (managed):** all AWS infra primitives; no bespoke orchestration.
- **Must be bespoke (the showcase):** workflow state machines + orchestration,
  tenant-specific CRM field-mapping engine, envelope encryption + blind index +
  masking layer, transactional outbox, the self-explaining demo (explainers, badges,
  stepper, "How it's built" page), demo-session sandboxing.

---

## Scope guardrails — what to deliberately defer

| Deferred | Owning phase / status |
|---|---|
| Real landing/tenant-select content | P1.6 (P0 ships placeholders) |
| Domain schema & entities | P1+ (P0 ships empty baseline) |
| Real sidecars (enrichment/sync/quote/notification) | M3 (P1–P2 stubs) |
| Full integration-health dashboard | M4 (P3.5 minimal DLQ list) |
| Inbound CRM webhook, 5-min highlights | M4 [SHOULD] |
| Admin config-editing UIs, contact merge, owner-scoped visibility | Out of scope (stretch) |

**Minimum Viable Increment:** P0.1 alone — a hands-off pipeline putting a placeholder
page live over HTTPS on the parity stack — is a shippable, demonstrable increment.

---

## How this maps to the build pipeline

Each phase = **one TDD + one epic plan**, fed through
`1-prompt-to-brd` → `2-requirements-to-tdd` → `3-tdd-to-epic-plan` → the per-epic loop. Two work types:
**implementation phases** carry the per-epic review budget (~150 lines · ~8 files ·
one commit each); there are no research spikes in this program (the stack is
committed). From **P0.1a** on, every epic also updates its FE/BE test cases behind the
**pre-commit** gate (see the *Tests ship with every slice* principle).

**Worked example — decomposing P0.1 into named epics** (the actual TDD's work
breakdown, for illustration):

1. Repo scaffold + `docker-compose` with Postgres + RabbitMQ (health-checked).
2. FastAPI core skeleton + `/health` + Alembic empty baseline.
3. React SPA shell + nginx reverse proxy (local).
4. Placeholder landing + tenant-selection pages `[UI]`.
5. Terraform: network/EC2/IAM/SSM baseline.
6. Terraform: ECR + CodePipeline/CodeBuild/CodeDeploy.
7. Terraform: Route 53 record + certbot/TLS at nginx.
8. CodeDeploy app spec + deploy-time migrate/seed hook; prove the exit test.

(Each later phase earns the same treatment when it reaches the front of the queue.)

---

## Where we are & the next N moves

**2026-06-11** — Program plan authored. Phase 0 (P0.1) TDD written at
`./phase-0/tdd-P0.1-walking-skeleton.md`. Stack decided: RabbitMQ, PostgreSQL,
Let's Encrypt/certbot at nginx, CodeBuild→ECR→CodeDeploy, deploy on push to `main`,
Alembic wired with empty baseline. **Isolation model decided (overrides the original
shared-schema + RLS spec): schema-per-tenant** — one PostgreSQL schema per tenant +
per-tenant DB role + session-set `search_path`, a shared `platform` schema for
cross-tenant/reference data, **no RLS**. Requirements doc, UI/UX Guide, and this plan
updated to match. **Next moves:**

1. Run `3-tdd-to-epic-plan` on the P0.1 TDD → `./phase-0/epic-plan-P0.1-walking-skeleton.md`.
2. Execute the per-epic loop for P0.1; the **exit test** is the go/no-go gate.
3. Stand up **P0.1a** (test harness + `pre-commit` gate) — its own TDD/epic plan; lands
   any time after P0.1 Epic 2, green before Milestone 1, and does not gate the exit test.
4. On a green exit test, start Milestone 1 with P1.1 (Auth/RBAC).

**2026-06-11** — Added **P0.1a** (test harness & commit gate) after noticing the plan
carried no test strategy; tooling frozen (`pytest` + Vitest behind `pre-commit`) and the
*Tests ship with every slice* principle recorded.

**2026-06-12** — **P0.1 COMPLETE — the go/no-go gate is green.** All 12 epics shipped
and the live exit test passed: a push to `main` ran Source → Build → ECR → Deploy
hands-off and the landing went live at `https://policyflow.joeyshub.com` over valid
HTTPS with zero manual steps (TLS cert self-issued on deploy). Risks #1 and #2 retired.
Standing the cloud up surfaced 8 glue/hardening fixes (subnet AZ, ECR-Public base
images, SSM Session Manager shell, certbot bootstrap robustness, restart policy,
edge-aware ValidateService, committed TLS options, deploy-time cert auto-issuance) —
all captured in the Epic 12 notes. **Next moves:**

1. Stand up **P0.1a** (test harness + `pre-commit` gate) — its own TDD/epic plan; the
   one remaining piece of Milestone 0.
2. Then start **Milestone 1** with **P1.1 (Auth/RBAC)**.
3. Optional infra follow-up (recorded, not blocking): Terraform-generate the DB/broker
   passwords into SSM to remove the manual `put-parameter` step and the volume-init
   footgun.

**2026-06-12** — **P0.1a COMPLETE — Milestone 0 fully done.** All 9 epics shipped: a
backend `pytest` suite (5 passed) and frontend Vitest suite (2 passed) behind a blocking
`pre-commit` gate, proven live by a deliberately broken test that rejected the commit,
mirrored in CodeBuild `pre_build` and GitHub Actions, with the standing rule in
`../../TESTING.md`. Every later phase now adds cases behind a green gate. **Next move:**
start **Milestone 1** with **P1.1 (Auth/RBAC)**.

**2026-06-12** — **P1.1 COMPLETE — Milestone 1 underway.** All 14 epics shipped: async
SQLAlchemy + the `platform` schema (`tenants`/`users`/`auth_sessions`), bcrypt hashing,
the pluggable `AuthProvider` (`LocalPasswordAuthProvider`), opaque SHA-256-hashed
sessions, the role→capability matrix + `require_capability` guard, the auth router
(`login`/`logout`/`me`), a guarded RBAC demonstrator (`GET /api/tenant/config`), the
2-tenant/9-persona seed, and a real ephemeral-Postgres test substrate. Core suite **95
passed**; the DB-backed suite runs in the CI gate (GitHub Actions + CodeBuild). The
substrate surfaced and fixed a live migration bug (generic `sa.Enum` vs PG `ENUM`).
**Next move:** **P1.2 (Tenant scoping — schema-per-tenant)**, which retires Risk #3.

**2026-06-13** — **P1.2 COMPLETE — the isolation backbone is in.** All 9 epics shipped
behind a green gate (core suite **135 passed**): the registry single-source-of-truth,
migration `0003` (per-tenant schemas + dedicated roles + `platform_reader` + the
GRANT/REVOKE model), seed-populated `schema_name`/`db_role` columns, the per-schema
`tenant_settings` demonstrator (`0004`), the `get_tenant_db` per-request scoping
dependency (`SET LOCAL ROLE`/`search_path`, no-leak proven across pooled connections),
the tenant-scoped + Platform-Admin carve-out endpoints, the named isolation acceptance
suite (a per-tenant role is *physically* denied another tenant's schema; A-vs-B holds
over every endpoint), and Alembic schema-filter hygiene keeping the drift gate clean.
The cross-tenant read goes only through the sanctioned platform path; its
`record_platform_read_for_audit` seam is wired but emits nothing — emission lands in
**P1.4**. **Next move:** **P1.3 (Field-level encryption, blind index & masking)**, which
retires Risk #3 (schema-per-tenant + app-layer encryption coexisting without breaking
blind-index search).

**2026-06-14** — **P1.3 COMPLETE — Risk #3 retired; the PII spine is in.** All 13 epics
shipped behind a green gate (full backend suite **230 passed**): the pure crypto toolkit
(AES-256-GCM + master-key wrap/unwrap + HKDF subkeys + HMAC blind index), the per-tenant
wrapped-key store (`platform.tenant_data_keys`, migration `0005`) read only by the login
role with a process-lifetime key cache, the encrypt/decrypt/blind-index service seam
(per-tenant subkey + tenant-id AAD), masking + `age_band` utilities, the `pii_demo`
demonstrator (migration `0006`) behind masked write/read + blind-index lookup + a
capability-gated reveal, real per-tenant seeded root keys, and the named acceptance suite
(`test_pii_acceptance.py`) proving ciphertext-at-rest, blind-index exact-match without
decryption under the real tenant role, per-tenant key isolation, and masking-by-default
with reveal as the sole RBAC-gated egress. **Risk #3 retired** — schema-per-tenant +
app-layer encryption coexist and the blind-index equality lookup runs inside the tenant
schema. The reveal seam (`on_pii_revealed`) is wired but emits nothing — audit lands in
**P1.4**. **Next move:** **P1.4 (Audit logging)**, which fills both the
`record_platform_read_for_audit` (P1.2) and `on_pii_revealed` (P1.3) seams.

**2026-06-15** — **P1.4 COMPLETE — the audit spine is in; both deferred seams now emit.**
All 11 epics shipped behind a green gate (full backend suite **280 passed**): the pure
event-type/outcome vocabulary (`audit/records.py`) + the `audit_writer` registry constant,
migration `0007` (two append-only stores — `platform.audit_records` and a per-tenant
`audit_records` in every schema — with `audit_writer` granted INSERT+SELECT only and
tenant/`platform_reader` grants tightened by REVOKE), the two ORM models (drift-clean),
the own-session two-store `record_audit_event` service, a live `permission denied`
append-only/isolation acceptance proof, the two filled seams (`record_platform_read_for_audit`
+ `on_pii_revealed`), auth/record-change wiring (`auth.login`/`logout`, `record.created`),
the guarded self-auditing `GET /api/audit` (`VIEW_AUDIT_LOGS`, tenant-scoped, PII-free,
writes its own `audit.viewed`), and the named acceptance suite (`test_audit_acceptance.py`)
plus `alembic check`/`0007` round-trip health. Sensitive ops write field *names*, never
values; viewing audit is itself audited; append-only is enforced *physically* by grant, not
just by convention. The audit viewer UI stays deferred to **M4**. **Next move:** **P1.5
(Event bus + envelope + stub consumers)** — the seam M3's real sidecars plug into unchanged.

**2026-06-15** — **P1.5 COMPLETE — the event-bus seam M3 plugs into is in.** All 11 epics
shipped behind a green gate (full backend suite **347 passed**): the frozen event
vocabulary + flat envelope (`app/events/`), the per-tenant transactional `outbox` +
`processed_events` (migration `0008`, `outbox_relay`/`event_consumer` roles), the
transactional `enqueue_event`, the RabbitMQ topology + `publish_envelope` (durable topic
exchange, per-consumer queues, per-queue DLX/DLQ derived from `catalog.CONSUMER_BINDINGS`),
the own-session polling relay (publish-before-mark, at-least-once), the two idempotent
terminal stub consumers (dedupe on `(consumer_name, event_id)`, nack-without-requeue to the
DLQ), the `event_bus_lifespan` runtime wiring, the two real triggers (`record.created`,
`pii.revealed` — both on the request transaction, no PII in the payload), dev-only
management-UI queue-depth visibility + config knobs, and the named acceptance suite
(`test_event_bus_acceptance.py`) proving fan-out + correlation + idempotency + poison→DLQ +
per-tenant isolation end-to-end. Marking complete also caught and fixed a full-suite-red
test-isolation bug: three Epic-5 relay tests keyed on global counts / next-message-on-queue,
broken by Epic 8's create-enqueues-an-outbox-row trigger on the shared, never-reset
container — remade event-pinned (the Epic 11 idiom). Risk #4's contract artifact (the seam
M3's real sidecars bind to) is in place; full retirement lands when M3 swaps a stub behind
the identical events. **Next move:** **P1.6 (Demo shell `[UI]`)** — real landing +
tenant-selection, role switcher, stepper/explainer shells.

**2026-06-17** — **Design refinement (unbuilt phases P1.6/P1.7): two demo surfaces +
two intake routes.** Resolving a demo-UX concern — playing the shopper and the agent on
one surface blurred *who the visitor is* — the demo now has two distinct surfaces, the
public **Shopper site** and the authenticated **Agent workspace**, joined by a persistent
**surface toggle** (a demo convenience; in production they are genuinely separate front
ends). The toggle changes *surface*, not identity, and is kept **separate from the
staff-only role switcher** (Shopper is not an RBAC role). Lead intake accordingly grows
**two routes behind the identical `lead.created` event**: **self-service** (shopper fills
the public form, lands unassigned) and **agent-entered** (authenticated agent enters it as
if taking a call — **decision: born owned by the entering agent**, skipping the queue, so
self-service demonstrates *claiming* and agent-entered demonstrates *direct ownership*).
The demoer picks either route at walkthrough step 3, told both up front; both drive the
identical downstream pipeline, so the entry route is a *front door*, not a fork in the
domain. No backend re-architecture — the public intake path was already unauthenticated +
demo-session-scoped; this layers a UX surface + narrative over the existing seam. Folded
into the requirements (Demo Access Model, Lead Intake, Lead Assignment, Walkthrough 1–6,
glossary) and the P1.6/P1.7 scope above. **Next move (unchanged):** **P1.6 (Demo shell
`[UI]`)**, now including the surface toggle + Shopper surface shell.

**2026-06-19** — **P1.6 COMPLETE — the demo shell + both surfaces are in; Milestone 1 is
now feature-ready.** All 24 epics shipped behind a green gate (full backend suite **369
passed** on the real Postgres + RabbitMQ substrate; full frontend suite **179 passed**
across 27 files; production build clean). This was the program's first interactive
frontend phase, built in three layers — access-model skeleton, design system + app shell,
demo surfaces — with the **2026-06-17** two-surface refinement landed as the trailing
Shopper-shell + surface-toggle epics. Acceptance met end-to-end: a cold visitor lands,
reads orientation, picks a tenant, is dropped into the Agent workspace signed in as a
seeded Agent (passwordless `assume-persona`), switches roles (with Platform-Admin
inversion), and toggles to the unauthenticated Shopper site and back carrying the demo
session + tenant; the guided stepper, scenario-reference panel, explainer popovers,
"Simulated" badge, and public "How it's built" page all render. The isolation invariant
held — the role switcher changes *identity*, the surface toggle changes *surface*, and
the Shopper site carries no RBAC role. Deferred per plan: the real public intake form
(P1.7 Shopper seam), durable stepper progress + live session countdown (P1.8), audit
viewer / dashboards (M4). One doc-debt item recorded (non-blocking): the P1.6 TDD's
routing/surfaces sections predate the two-surface refinement and need a sync pass.
**Next move:** **P1.7 (Lead intake, queue, qualification & duplicate detection `[UI]`)** —
the first feature phase, with two intake routes behind the identical `lead.created` event,
wiring the real public form onto the P1.6 Shopper buyer-home seam.

**2026-06-20** — **P1.7 COMPLETE — the first feature phase is in; leads exist end-to-end.**
All 22 epics shipped behind a green gate (full backend suite **512 passed** on the real
Postgres + RabbitMQ substrate; full frontend suite **270 passed** across 38 files;
`tsc -b && vite build` clean). Two intake routes now ride the identical `lead.created` event
through one shared `create_lead` core: self-service `POST /api/public/intake` (rate-limited +
honeypot + strict validation; lands `New`/unowned/`public_form`; sanitized `{"ok": true}`)
and agent-entered `POST /api/leads` (born `Working`/owned/`agent_entered`). On top sit the
unassigned queue + one-click claim (`lead.assigned`), qualify/reject (+ events), deterministic
duplicate detection via the P1.3 blind index (email-OR-phone, oldest-wins, no decryption) with
agent resolution (link / new / reject), masked-by-default reads with audited click-to-reveal,
and a minimal per-tenant seed (queue non-empty + the Jordan-Rivera duplicate-bait). The four
Shopper/Agent UI surfaces (public form, agent form, leads list + queue tab, lead detail +
actions) and the typed frontend client landed behind their own component tests; the "Leads"
nav is live. The named acceptance suite (`test_lead_intake_acceptance.py`) proves the
end-to-end lifecycle on the real substrate plus the one physical proof the lead path lacked —
a switched per-tenant role is `permission denied` on the other tenant's `leads` while reading
its own — and that the live intake endpoint flags a duplicate on the blind index alone.
Tenant-isolation / PII invariant held throughout. Epic plan:
`./p1.7/epic-plan-P1.7-lead-intake-queue-qualification-duplicate-detection.md`. **Faked /
deferred per plan:** the full per-tenant seed + demo-session lifecycle/purge (**P1.8**); the
per-record event timeline (**P1.9**). **Not yet committed** — Epic 22's test file + these doc
edits are staged in the working tree; the manual `9-document-code-changes` → `commit-epic`
step lands them. **Next move:** **P1.8 (Seed data, demo-session lifecycle & reset)**.
