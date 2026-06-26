# P2.3 — Quotes → Application → Policy — Technical Design Document

> **Build strategy:** Tracer bullet — locked by the program plan's M2 cross-cutting decision (rationale in §6 D0); `3-tdd-to-epic-plan` copies this to the epic plan and `4-plan-epic` honors it (`0-conventions.md` → *Build strategies*).

## 1. Summary

Build the opportunity-to-policy spine. From a *Qualified* opportunity an agent requests
carrier quotes over a **real broker round-trip** (a new non-terminal `carrier.quote` stub
that returns 2–3 deterministic canned options), selects a quote to create an **Application**,
completes a product-specific step (beneficiary / health questions), submits for an **inline
deterministic carrier decision**, and on approval an **issued Policy** lands — with the
opportunity stage advancing itself the whole way. A declined application is retained as
read-only history and a different attached quote can supersede it. For Tenant 1 the
Application carries an encrypted, masked, audited-reveal **Medicare ID** (reusing P1.3).

## 2. Business Requirements

Source BRD: [./brd-p2.3-quotes-application-policy.md](./brd-p2.3-quotes-application-policy.md) — the agreed requirements; not re-narrated here. Clarifications surfaced during this design that the BRD leaves open:

- **One phase, one TDD.** The BRD's "Size L, split likely" is **epic-plan-time epic slicing**, not a phase split — the program plan already treats P2.3 as one phase. `3-tdd-to-epic-plan` slices the §9 work breakdown into epics.
- **Decline return target** is *Quoted* when the tenant enables it, else *Qualified* (BRD §6.8 "Quoted/Qualified") — both demo tenants enable *Quoted* (D11, C3).
- The **carrier decision** reads the **converted contact's** email (the BRD's "applicant email"); no separate applicant-email field is introduced (D7).
- The **per-record event timeline** for opportunities/quotes/applications/policies is **P2.5**, not this phase; P2.3 makes the quote round-trip watchable by **polling the quote-request status** (D14).

## 3. Goals / Non-Goals

**Goals**
- An agent takes a *Qualified* opportunity to an **issued Policy**, every transition watchable.
- The **lifecycle state machine** is proven end-to-end, including **decline → supersession → re-apply**.
- The **carrier quote round-trip** is an observable event-driven interaction (requested → pending → completed).
- **Application/policy status auto-advances** the opportunity stage; automation-owned stages are no longer manually reachable.
- **Secure-PII** showcase: a Tenant-1 Medicare ID, encrypted, masked-by-default, audited reveal.
- **Multi-tenant + demo-session isolation** for every new record and event.

**Non-Goals**
- Real Carrier Quote service (→ M3, behind identical events); cross-sell + renewals (→ P2.4); CRM sync of the new records (→ P3); a "pending / manual review" carrier outcome; in-app editing of the carrier/product catalog (seed/registry-driven); the generalized per-record timeline + correlation trace (→ P2.5).

## 4. Current State

The phase builds on settled foundations (paths link the patterns it reuses):

- **Opportunity stage machine** — pure [core/app/opportunities/state.py](../../core/app/opportunities/state.py): `OpportunityStage`, forward-by-one-to-next-enabled + any-active→Lost, framework-free `InvalidStageTransition`. The stage-change action [core/app/opportunities/service.py](../../core/app/opportunities/service.py) rides the request transaction and emits via the outbox; the endpoint [core/app/opportunities/router.py](../../core/app/opportunities/router.py) owns guards + the `_scope_to_session` / foreign-404 / seed-409 demo-session isolation trio.
- **Event bus** — `EventType` + `CONSUMER_BINDINGS` in [core/app/events/catalog.py](../../core/app/events/catalog.py); the transactional-outbox write seam `enqueue_event` ([core/app/events/outbox.py](../../core/app/events/outbox.py)) runs on the **caller's request session** (tenant role is INSERT-only on its own `outbox`); the polling relay publishes; the **terminal** stubs [core/app/events/consumers.py](../../core/app/events/consumers.py) run own-session as the tight `event_consumer` role and publish nothing back; lifespan wiring [core/app/events/runtime.py](../../core/app/events/runtime.py) registers one consumer per `CONSUMER_HANDLERS` tuple.
- **PII** — `encrypt_field` / `decrypt_field` (tenant-id bound as AES-GCM AAD) in [core/app/pii/service.py](../../core/app/pii/service.py); the leads reveal endpoint [core/app/leads/router.py](../../core/app/leads/router.py) (`REVEAL_PII` cap → decrypt one allow-listed field → `on_pii_revealed` seam → return) is the verbatim pattern to mirror.
- **Registry-as-config** — [core/app/tenancy/registry.py](../../core/app/tenancy/registry.py): frozen `TenantConfig` + `ProductLine` carry per-tenant pipeline config with **zero migrations** (P2.2 D1 precedent). The dedicated-role discipline (`audit_writer`, `outbox_relay`, `event_consumer`, `demo_purge`) lives here too.
- **Entities** — schema-less [Opportunity](../../core/app/models/opportunity.py) (carries the nullable `estimated_annual_premium` P2.3 fills) / [Contact](../../core/app/models/contact.py) (`email_encrypted` is the carrier-decision input) / [Lead](../../core/app/models/lead.py). Latest migration is **0015**; P2.3 starts at **0016**.

## 5. Proposed Design

> Flow diagram: [diagrams/tdd-p2.3-money-path.excalidraw](./diagrams/tdd-p2.3-money-path.excalidraw) ([rendered PNG](./diagrams/tdd-p2.3-money-path.png)) — the agent money-path, the async broker round-trip, the opportunity-stage coupling, and the decline → supersession loop.

### 5.1 New entities (migration 0016, per-tenant schemas)

- **`quote_requests`** — the pollable round-trip: `id`, `opportunity_id`, `status` (`pending` → `completed`), `product_line`, `correlation_id`, `demo_session_id`, timestamps.
- **`quotes`** — one row per returned option: `id`, `quote_request_id`, `opportunity_id`, `carrier`, `product_label`, `coverage_amount`, `premium_monthly`, `premium_annual`, `correlation_id`, `demo_session_id`, timestamps.
- **`applications`** — `id`, `opportunity_id`, `contact_id`, `product_line`, `selected_quote_id`, `status` (state machine §5.2), the carrier/product/coverage/premium **copied from the selected quote**, `beneficiary` + `health_answers` (`jsonb`), `medicare_id_encrypted` (`bytea`, nullable — Tenant-1 only), `decision` / `decided_at`, `superseded_by_application_id`, `correlation_id`, `demo_session_id`, timestamps. A **partial unique index** on `(opportunity_id) WHERE status IN ('Draft','Submitted')` backstops "one active per opportunity" (C5).
- **`policies`** — `id`, `opportunity_id`, `application_id`, `contact_id`, `policy_number`, carrier/product/coverage/premium, `status` (`Active`), `correlation_id`, `demo_session_id`, `issued_at`.

All schema-less ORM models resolved via `search_path` (the `Lead`/`Opportunity` precedent); migration owns the tables + indexes + grants; excluded from `alembic check`.

### 5.2 Pure state machine — `app/applications/state.py`

Mirrors `opportunities/state.py`. `ApplicationStatus`: `Draft`, `Submitted`, `Approved`, `Declined`, `Superseded`. Transitions: `Draft → Submitted`; `Submitted → {Approved (terminal), Declined}`; `Declined → Superseded` (set when a new application supersedes it). **Active** = `{Draft, Submitted}`. Framework-free `InvalidApplicationTransition`, mapped to 409 at the edge.

### 5.3 Carrier/product catalog — static registry data (no DB, no migration)

Extend the registry: per-tenant carriers + a per-`ProductLine` tuple of 2–3 **option templates** `{carrier, product_label, coverage_amount, premium_monthly}` (`premium_annual = premium_monthly × 12`). Inherently immutable ("never mutated"), read in-process by the stub — the P2.2 D1 registry-config precedent. Two new `ProductLine` attributes: `application_step: 'beneficiary' | 'health' | None` (D10) and a `TenantConfig.collects_medicare_id: bool` flag (Sunshine `True`, Florida `False`, D9).

### 5.4 The carrier-quote round-trip (the one new event-driven flow)

1. **`POST /api/opportunities/{id}/quote-requests`** (agent, `CREATE_EDIT_RECORDS`, holder = owner or Tenant Admin) — writes a `quote_requests` row `status=pending` and `enqueue_event(quote.requested)` on the request transaction (atomic). The Medicare gate (`is_blocked_for_medicare`) is re-checked here (BRD §7) before the write.
2. The **`carrier.quote` consumer** (new, **non-terminal**) consumes `quote.requested` off its own queue. Because it (a) writes domain rows and (b) enqueues a completion event, it **cannot** reuse the terminal `_consume` core (which is hardwired to `event_consumer` + a `(envelope)→None` effect). It is a **parallel consume path** (C1): resolve the tenant schema from the envelope (the existing `_get_tenant_schema` idiom), `SET LOCAL ROLE <tenant db_role>` + `search_path`, **dedupe** on `quote_request_id` (an existing-completed request short-circuits — idempotent on redelivery), generate the options from the registry catalog, INSERT the `quotes` rows, mark the request `completed`, and `enqueue_event(quote.completed)` — all in one transaction on its own session, propagating `demo_session_id` + `correlation_id` from the envelope.
3. The relay publishes `quote.completed`; `sync.logger` (`#`) reacts.
4. **`GET /api/opportunities/{id}/quote-requests/{rid}`** is polled (~1.5s, the P1.9 idiom) until `completed`, then renders the `quotes`. First successful completion **attaches** the quotes and moves the opportunity to *Quoted* (BRD §6.2).

### 5.5 Selection, application lifecycle, coupling

- **Select a quote** — `POST /api/opportunities/{id}/applications` `{quote_id}`: create `applications` (`Draft`, carrier/product/coverage/premium copied from the quote), move the opportunity → *Application Started*, set `estimated_annual_premium` to the quote's annual premium. (D6) Emits `application.started`.
- **Product step** — `PATCH /api/applications/{id}` captures `beneficiary` / `health_answers` per the product line's `application_step`; Tenant-1 captures the **Medicare ID** (encrypted via `encrypt_field`).
- **Submit** — `POST /api/applications/{id}/submit`: `Draft → Submitted`, opportunity → *Submitted*, emit `application.submitted`; then **inline carrier decision** (§5.6).
- **Decision (inline, same transaction)** — approved by default; declined iff the contact's decrypted email contains `deny`. **Approved** → `application.approved`, **issue Policy** (create `policies` row + `policy.created`), opportunity → *Approved* → *Policy Active*. **Declined** → `application.declined`, opportunity → *Quoted* (else *Qualified*, C3).
- **Supersession** — selecting a **different attached quote** after a decline creates a new `Draft` application and marks the prior declined one `Superseded` (`superseded_by_application_id`); the service enforces one active per opportunity.

**Coupling is synchronous + in-transaction** (D6): the application service moves the opportunity stage **directly** via an **internal stage-setter** that writes `opportunity.stage` + emits, **bypassing `assert_transition` and the Medicare gate** (it drives automation-owned and backward moves the manual machine forbids, C3). Domain events still publish for observability. **Manual lockdown:** add `AUTOMATION_OWNED_STAGES = {Application Started, Submitted, Approved, Policy Active}`; the manual `POST /opportunities/{id}/stage` endpoint rejects any target in that set (422 "lifecycle-driven"), and the board suppresses its Advance control when `next_stage` is automation-owned (so it never offers a button that 422s, C2).

### 5.6 Carrier decision rule

At submit, `decrypt_field(tenant_id, contact.email_encrypted)` and set `declined` iff `'deny' in email.lower()`, else `approved`. Deterministic; the value is never logged or returned. The decline acceptance thread depends on a **seeded contact whose email contains `deny`** (C4) — a seed prerequisite (contacts have no email-edit path).

### 5.7 Medicare ID (Tenant-1)

Agent-entered during the application step, stored `medicare_id_encrypted`, masked-by-default on Application + Policy reads. **`POST /api/applications/{id}/reveal-medicare-id`** mirrors the leads reveal verbatim: `REVEAL_PII` capability → `decrypt_field` → `await on_pii_revealed(db, identity, "application", id, "medicare_id")` (the seam takes `entity_type` as a free string — no audit-enum change) → return. Field presence gated by `collects_medicare_id`; Tenant-2 never renders it.

### 5.8 Events (catalog additions)

`EventType` += `quote.requested`, `quote.completed`, `application.started`, `application.submitted`, `application.approved`, `application.declined`, `policy.created`. `CONSUMER_BINDINGS` += `ConsumerBinding("carrier.quote", ("quote.requested",))`; `sync.logger` (`#`) still covers everything; enrichment stub unchanged. Payloads non-PII, `entity_id`-keyed (+ `opportunity_id` etc.); `correlation_id` carried forward from the opportunity; `causation_id=None` (the P2.2 `_emit` precedent).

### 5.9 Frontend (Agent workspace, all `[UI]`)

Opportunity detail: request-quotes control + round-trip status (polling) + quote list/selection; application detail with the product-step form + submit; policy view; Medicare ID masked + click-to-reveal. Read-Only sees masked reads, no actions. Reuse the design system + P1.9 polling idiom.

## 6. Decisions

**D0. Build strategy — Tracer bullet.** *Chosen:* tracer bullet. *Alternatives:* walking skeleton. *Rationale:* the architecture (events, outbox, schema-per-tenant, PII) is already proven across P1.x; the **risk here is the money-path behaviour/UX** (quote round-trip, lifecycle, coupling, decline/re-apply), so the thinnest customer-visible end-to-end slice gives the fastest feedback. Locked by the program plan's M2 cross-cutting decision.

**D2. Carrier-quote round-trip — async via broker, new non-terminal `carrier.quote` stub.** *Alternatives:* inline synchronous generation in the request handler. *Rationale:* the BRD demands a **watchable** pending→completed round-trip and a stub↔M3 swap behind identical events; inline would hide the bus the demo exists to show.

**D2b. Stub runs own-session as the tenant `db_role`.** *Alternatives:* a new dedicated `carrier_quote` least-privilege role. *Rationale:* it creates tenant **domain** data (Quote rows) + an outbox row, which is exactly the tenant role's job; a new role buys no isolation the tenant role lacks and adds a migration/grant. It cannot reuse the terminal `_consume` core (different role + domain writes + outbox enqueue), so it is a **parallel** consume path with its own `quote_request_id` dedupe (C1).

**D3. Two tables — `quote_requests` (lifecycle) + `quotes` (options).** *Alternatives:* one `quotes` table with a batch tag. *Rationale:* the pollable status and the rendered option rows are distinct concerns; separating them gives a clean `pending→completed` poll target (P1.9 idiom) without overloading option rows with request state.

**D4. Carrier/product catalog as static registry data.** *Alternatives:* seed DB tables. *Rationale:* "never mutated" reference data read in-process is inherently immutable as frozen registry data — zero migration/role, mirroring the P2.2 D1 pipeline-config precedent.

**D5. New `applications` table + pure `app/applications/state.py`.** *Rationale:* mirrors the proven `opportunities/state.py` single-source-of-truth machine; jsonb for beneficiary/health keeps content out of the schema; a partial unique index backstops one-active-per-opportunity (C5).

**D6. Coupling — synchronous, in-transaction, direct internal stage-setter; manual lockdown via `AUTOMATION_OWNED_STAGES`.** *Alternatives:* a broker consumer reacting to `application.*` events. *Rationale:* atomic + immediately visible beats eventual consistency for the demo; the internal setter must bypass `assert_transition`/the Medicare gate because it drives automation-owned (and backward, on decline) moves the manual machine forbids. The manual endpoint blocks targets in the set (resolving the P2.2 D14 interim).

**D7. Carrier decision — decrypt the contact email, `deny` substring → declined.** *Alternatives:* a separate applicant-email field on the application. *Rationale:* the contact already carries the "applicant email" (BRD wording); no new field, deterministic, value never surfaced.

**D8. Policy auto-issued in the approve transaction; deterministic human-readable number.** *Rationale:* keeps *Policy Active* atomic with the decision (most watchable). `POL-<TENANT_PREFIX>-<YEAR>-<6HEX>` derived from the application uuid — deterministic **given the application** (no random suffix); not byte-identical across re-seeds, which "repeatable demo" does not require (C6).

**D9. Medicare ID agent-entered during the application step; gated by a registry flag.** *Alternatives:* seeded on Tenant-1 fixtures. *Rationale:* entering it during the step **demonstrates the secure-PII capture flow** (the showcase goal), not just a masked read; `collects_medicare_id` on `TenantConfig` keeps the tenant rule in the registry, not a hardcoded schema check.

**D10. Product step mapped by a `ProductLine.application_step` attribute.** *Rationale:* the registry is already the per-product source of truth; an attribute keeps the mapping declarative. Mechanism + mapping fixed here; exact beneficiary fields and the 3–5 health questions are an epic-plan **content** decision.

**D11. Supersession — re-selection creates a new Draft + marks the prior Declined app Superseded; decline returns the opportunity to Quoted (else Qualified).** *Alternatives:* offering a fresh re-quote on the decline path. *Rationale:* re-selection of an already-attached quote is the minimal acceptance path; re-quote is optional and deferred. Quoted-when-enabled-else-Qualified keeps the rule tenant-robust (C3).

**D12. Event vocabulary + the single new binding.** *Rationale:* seven `entity_id`-keyed non-PII members + `carrier.quote` bound to `quote.requested`; `sync.logger` `#` keeps every event consumed; `correlation_id` forward + `causation_id=None` matches the existing `_emit` precedent.

**D13. Demo-session isolation reused verbatim.** *Rationale:* all four tables carry `demo_session_id`; the `visible_to_session` / foreign-404 / seed-409 trio from `opportunities/router.py` is the proven guard; the stub propagates `demo_session_id` from the envelope.

**D14. Watchability via quote-request polling; generalized timeline deferred to P2.5.** *Rationale:* polling a status column is the P1.9 idiom and sufficient for the round-trip; generalizing the per-record timeline to opp/quote/app/policy is explicitly P2.5 scope.

## 7. Risks and Open Questions

- **R1 (C1) — non-terminal consumer is a new pattern.** The carrier-quote stub needs a role + domain writes + outbox enqueue the terminal `_consume` core does not support. *Mitigation:* a parallel consume path with `quote_request_id` dedupe (an already-`completed` request is a no-op on redelivery); reconcile the dedupe-row role (`event_consumer`) vs the domain-write role (tenant) explicitly at epic plan.
- **R2 (C2) — the manual lockdown breaks existing P2.2 stage tests** that advance into automation-owned stages via `POST /stage` (`test_opportunity_stage.py`, `test_opportunity_pipeline_acceptance.py`, `test_florida_board_config_and_approved_skip` — the `Policy Active` advances flip 200→422). *Mitigation:* the lockdown epic ships with those test edits (P2.2 D14 explicitly left this as interim); the board must suppress Advance when `next_stage` is automation-owned.
- **R3 (C4) — the decline thread needs a seeded `deny@…` contact.** Contacts have no email-edit path, so step-12 acceptance depends on seed data (analogous to the P2.2 under-65 seed-nudge). *Mitigation:* a seed WBS item providing a Sunshine/Florida contact whose decrypted email contains `deny`.
- **R4 — content not yet fixed:** the exact beneficiary fields and the 3–5 health questions (epic-plan content decision, D10).
- **R5 — concurrency:** "one active application per opportunity" is service-enforced; the partial unique index (C5) is the DB backstop. Fine for the single-agent demo.

## 8. Rollout / Verification

- **Migration 0016** is additive (new per-tenant tables + indexes + grants); no existing-table change beyond reusing `opportunities.estimated_annual_premium`/`target_close_date`. Down-migration drops the new tables.
- **No feature flag** — the phase is gated by being new endpoints/surfaces; existing flows are unaffected except the deliberate manual-stage lockdown (R2).
- **Manual verification (happy path, steps 9–11):** Qualified opportunity → request quotes → watch pending→completed → review options → select → Application created, opportunity at *Application Started*, premium updated → complete the product step → submit → approved → Policy issued with a number; Tenant-1 Medicare ID masked, reveal works and is audited.
- **Manual verification (decline + supersession, step 12):** submit an application whose contact email contains `deny` → `application.declined`, opportunity back to *Quoted* → select a different quote → superseding Application carried to approval.
- **Coupling proof:** moving an application/policy through statuses advances the opportunity stage with no manual change; manual reach into automation-owned stages is rejected.
- **Isolation proof:** Tenant-1 quotes/applications/policies absent in Tenant-2, which also lacks the Medicare-ID field; a second demo session never sees another's records.
- A named **acceptance suite** (`test_quotes_application_policy_acceptance.py`) proves both threads end-to-end on the real Postgres + RabbitMQ substrate, plus the isolation and coupling proofs.

## 9. Work Breakdown

Ordered simplest-first, **tracer-bullet first** (the first item is the thinnest customer-visible end-to-end slice; complexity layers after). Granular for `3-tdd-to-epic-plan` to slice into epics.

1. **Event vocabulary + catalog** — add the seven `EventType` members and the `carrier.quote` binding; update `test_event_catalog.py`.
2. **Tracer slice: quote round-trip → selection → Application(Draft)** — migration 0016 (`quote_requests`, `quotes`, `applications` minimal + grants); the `carrier.quote` non-terminal consumer (parallel consume path, registry catalog, `quote_request_id` dedupe); request-quotes + poll + select endpoints; opportunity → *Quoted* on attach, → *Application Started* on select with premium update; minimal FE (request, poll, select). End-to-end customer-visible.
3. **Carrier/product catalog in the registry** — carriers + per-product option templates + `application_step` attribute + `collects_medicare_id` flag; registry tests.
4. **Application state machine** — pure `app/applications/state.py` + tests; wire `Draft`/`Submitted`/`Approved`/`Declined`/`Superseded`.
5. **Product-specific step** — `PATCH /applications/{id}` capturing beneficiary / health_answers per `application_step`; FE step form. *(Field content settled at epic plan.)*
6. **Submit + inline carrier decision** — decrypt-contact-email rule; `application.submitted` → `approved`/`declined`; opportunity coupling for both.
7. **Policy issuance** — `policies` table (in 0016 or a follow-on migration), auto-issue on approval, deterministic policy number, `policy.created`, opportunity → *Policy Active*; FE policy view.
8. **Application↔Opportunity coupling lockdown** — internal stage-setter; `AUTOMATION_OWNED_STAGES` + manual-endpoint 422; board Advance suppression; **update the affected P2.2 stage tests** (R2).
9. **Decline → supersession** — return to *Quoted*/*Qualified*; mark prior app Superseded; one-active enforcement + partial unique index; re-selection creates a new Draft.
10. **Medicare ID (Tenant-1)** — encrypt on capture, mask on read, `reveal-medicare-id` endpoint reusing the leads reveal + `on_pii_revealed`; FE masked + reveal.
11. **Demo-session isolation** — `demo_session_id` on all four tables; `visible_to_session` reads + foreign-404 / seed-409 mutations across the new endpoints; stub envelope propagation.
12. **Seed** — quote/application/policy demo data + the **`deny@…` decline contact** (R3); a coherent shared-baseline + per-session story.
13. **Acceptance suite** — both threads + coupling + isolation proofs on the real substrate.
