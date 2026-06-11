# PolicyFlow — Program & Phase Plan

> **Living document.** This is the source-of-truth build path that sits *above* the
> per-unit pipeline. Each **phase** below feeds the normal chain
> `1-requirements-to-tdd` → `2-tdd-to-epic-plan` → the per-epic loop, with
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

#### P0.1 — Walking Skeleton & Deployment Pipeline ◄

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

#### P0.1a — Test harness & commit gate

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

### Milestone 1 — Foundations & Core Platform

Foundations precede all feature work. Planned in detail (next milestone). Phases are
ordered so the system stays runnable/deployable after each.

#### P1.1 — Authentication & RBAC

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

#### P1.2 — Tenant scoping (schema-per-tenant)

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

#### P1.3 — Field-level encryption, blind index & masking

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

#### P1.4 — Audit logging

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

#### P1.5 — Event bus + envelope + stub consumers

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

#### P1.6 — Demo shell `[UI]`

- **Goal:** Real landing + tenant-selection, branding, demo access model + role
  switcher, guided-stepper shell (prefill row + scenario-reference panel), explainer
  shell, "Simulated" badge component, "How it's built" page shell.
- **Shippable outcome / acceptance:** a visitor lands, reads orientation, picks a
  tenant, is signed in as a seeded Agent, and can switch roles; stepper + explainer
  shells render.
- **Depends on:** P1.1 (auth/role), P0.1 (SPA shell).
- **Isolation note:** role switcher changes identity, not enforcement; RBAC stays
  server-enforced per assumed role.
- **Size:** L (split likely at epic-plan time; keep UI-bearing epics isolated).

#### P1.7 — Lead intake, queue, qualification & duplicate detection `[UI]`

- **Goal:** Public intake forms (validation + abuse controls), unassigned queue +
  claiming, qualify/reject, deterministic duplicate detection + resolution.
- **Shippable outcome / acceptance:** walkthrough steps 3–6 demoable on the local
  stack; duplicate-bait flags and resolves.
- **Depends on:** P1.3 (blind index), P1.5 (events), P1.6 (shell).
- **Isolation note:** intake is an unauthenticated write — rate-limited, honeypot,
  schema-validated; every submission tied to a demo session and tenant.
- **Size:** L.

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
M0  P0.1 ◄ Walking Skeleton & Pipeline        (exit test gates everything)
        → P0.1a Test harness & commit gate     (tests + pre-commit gate from here on)
        |
M1  P1.1 Auth/RBAC → P1.2 Tenant schemas → P1.3 Encryption → P1.4 Audit
        → P1.5 Event bus+stubs → P1.6 Demo shell [UI]
        → P1.7 Intake/queue/qualify/dup [UI] → P1.8 Seed+sessions → P1.9 Timeline [UI]
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
| 1 | Hands-off push→prod on parity infra | P0.1 exit test | If a push to `main` does not reach `policyflow.joeyshub.com` with zero manual steps, halt feature work until fixed. |
| 2 | TLS at nginx on a single EC2 without an ALB | P0.1 | If certbot cannot issue/renew for the host, fall back to ACM+ALB and accept the added cost/infra. |
| 3 | Schema-per-tenant + app-layer encryption coexisting without breaking blind-index search | P1.3 | If blind-index exact-match can't run within a tenant schema, revisit per-tenant key derivation before building intake. |
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
`1-requirements-to-tdd` → `2-tdd-to-epic-plan` → the per-epic loop. Two work types:
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

1. Run `2-tdd-to-epic-plan` on the P0.1 TDD → `./phase-0/epic-plan-P0.1-walking-skeleton.md`.
2. Execute the per-epic loop for P0.1; the **exit test** is the go/no-go gate.
3. Stand up **P0.1a** (test harness + `pre-commit` gate) — its own TDD/epic plan; lands
   any time after P0.1 Epic 2, green before Milestone 1, and does not gate the exit test.
4. On a green exit test, start Milestone 1 with P1.1 (Auth/RBAC).

**2026-06-11** — Added **P0.1a** (test harness & commit gate) after noticing the plan
carried no test strategy; tooling frozen (`pytest` + Vitest behind `pre-commit`) and the
*Tests ship with every slice* principle recorded.
