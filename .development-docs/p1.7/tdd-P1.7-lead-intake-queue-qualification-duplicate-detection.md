# P1.7 — Lead Intake, Queue, Qualification & Duplicate Detection — Technical Design Document

## 1. Summary

P1.7 is PolicyFlow's first **feature** phase: it lands the Lead — the program's first
domain entity — and the two front doors that create it. A prospect can submit a lead two
ways, both behind the identical `lead.created` event and the identical downstream
pipeline: **self-service** on the public Shopper surface (unauthenticated, abuse-controlled,
lands unassigned) and **agent-entered** in the Agent workspace (authenticated, born owned
by the entering agent). On top of intake sit the tenant-wide **unassigned queue** with
one-click **claiming**, **qualify/reject** transitions, deterministic **duplicate detection**
via the P1.3 blind index, and agent **resolution** of a flagged duplicate (link / proceed
as new / reject). Lead PII is encrypted at rest, masked by default on every read, and
revealable through the existing audited `REVEAL_PII` path. The slice is demoable by hand on
the local stack via either route and is fully tested behind the green gate.

## 2. Business Requirements

No BRD exists for this phase; the source of truth is the requirements doc and the program
plan. Primary inputs:

- [PolicyFlow_Requirements.md](../PolicyFlow_Requirements.md) — §Lead Intake, §Lead
  Assignment, §Duplicate Handling, §Lead Qualification and Conversion (qualify/reject half
  only), §Demo Access Model, §PII Protection, §Authorization, §Event Catalog, §Walkthrough
  steps 3–6.
- [program-and-phase-plan.md](../program-and-phase-plan.md#L413-L428) — the P1.7 phase
  entry (goal, acceptance, isolation note, dependencies).

Constraints / clarifications surfaced during this design that the source docs don't already
state (design rationale lives in §6, not here):

- **Contacts do not exist yet** (P2.1), so the requirements' `duplicate_of_contact_id` /
  "link to the existing Contact" cannot be honored literally in P1.7. Duplicate detection
  matches against existing **Leads** this phase; the contact branch is added in P2.1.
- **The demo-session lifecycle is P1.8**, which *depends on* P1.7. There is no session
  backend yet; the envelope hardcodes `demo_session_id = None`. P1.7 carries a nullable
  `demo_session_id` column but does not populate, expire, or purge by it.
- **The full per-tenant seed is P1.8.** Because P1.7's acceptance ("a self-service lead
  lands in the queue and is claimed; duplicate-bait flags and resolves") must light up
  *now*, P1.7 ships its own minimal lead seed; P1.8 supersedes it.
- **Lead conversion is out of scope** (P2.1). P1.7 ends at `Qualified` / `Rejected`; it
  never creates a Contact, Household, or Opportunity, and never publishes `lead.converted`.

## 3. Goals / Non-Goals

### Goals

- A tenant-scoped **Lead** entity with the full intake field set, PII encrypted at rest
  (email/phone blind-indexed), `age_band` derived in plaintext, masked by default on read.
- **Two intake routes** behind one `lead.created`: unauthenticated public self-service
  (lands `New`/unassigned, `lead_source = public_form`) and authenticated agent-entered
  (born `Working`/owned, `lead_source = agent_entered`).
- **Abuse controls on the public route only**: per-IP rate limiting, a honeypot field,
  strict server-side schema validation with length limits.
- **Unassigned queue + claiming** (`New → Working`, owner set, `lead.assigned`).
- **Qualify / reject** (`Working → Qualified | Rejected`).
- **Deterministic duplicate detection** at intake (blind-index match against tenant leads,
  flag + `lead.duplicate_detected`) and **agent resolution** (link / new / reject).
- **Masked-by-default lead reads** + audited **click-to-reveal** (`REVEAL_PII`), reusing the
  built reveal + `on_pii_revealed` seam.
- The five lead events published via the **transactional outbox**; the existing stub
  consumers consume them; correlation IDs flow.
- Frontend: public intake form on the Shopper surface, agent intake form + leads list +
  queue + lead detail in the Agent workspace; the "Leads" nav item goes live.
- A minimal P1.7 lead seed so the queue is non-empty and the duplicate scenario lights up.
- Tests ship with the slice (backend acceptance suite + frontend component tests) behind
  the green gate.

### Non-Goals

- **Lead conversion** to Contact / Household / Opportunity (P2.1).
- **Tenant-Admin reassignment** of a lead to a specific agent. Deferred: with the demo
  presenting one persona at a time, multi-agent reassignment isn't meaningfully demoable
  yet. The `lead.assigned` event and `REASSIGN_LEADS_TASKS` capability are already in place
  for when it lands.
- **Enrichment results / live "enriching → resolved" UI** (P1.9 timeline + M3 real
  enrichment). P1.7 only *publishes* `lead.created`.
- **Demo-session lifecycle** — creation, the auto-anonymous session for direct public
  submissions, tagging, 24h expiry, purge (all P1.8).
- **Full seed data** (25–50 contacts etc., P1.8) and the per-record **event timeline**
  (P1.9).
- **Notification / CRM Sync / Metrics consumers** of the lead events (M3 / M4). Only the
  existing `enrichment.stub` + `sync.logger` consume them in P1.7.
- **Real product catalog** (products, carriers, eligibility rules) — P2.

## 4. Current State

The phase lands on a mature substrate; nearly every mechanism it needs already exists.

- **PII-bearing entity template** — [pii_demo model](../../core/app/models/pii_demo.py),
  [router](../../core/app/pii_demo/router.py), [schemas](../../core/app/pii_demo/schemas.py).
  A schema-less ORM resolved via `search_path`, masked-by-default read builder, blind-index
  lookup, and a `REVEAL_PII`-gated reveal that awaits `on_pii_revealed`. **The Lead is
  modeled directly on this.**
- **PII service** — [service.py](../../core/app/pii/service.py): `encrypt_field` /
  `decrypt_field` / `compute_blind_index` (per-tenant subkey + tenant-id AAD).
  [masking.py](../../core/app/pii/masking.py): `mask_email/phone/dob`, `age_band_for`,
  `normalize_email/phone`.
- **RBAC** — [rbac.py](../../core/app/auth/rbac.py) already defines `CREATE_EDIT_RECORDS`
  (Agent + Tenant Admin), `CLAIM_LEADS_MANAGE_TASKS`, `REASSIGN_LEADS_TASKS`, `REVEAL_PII`.
  **No new capabilities needed.** `require_capability(...)` in
  [dependencies.py](../../core/app/auth/dependencies.py).
- **Tenant scoping** — [scoping.py](../../core/app/tenancy/scoping.py): `get_tenant_db`
  (`SET LOCAL ROLE` + `search_path` from session identity, leak-proof). The whitelist guard
  `is_known_tenant_pair` / `is_known_schema` and the [registry](../../core/app/tenancy/registry.py)
  single-source-of-truth (`TenantConfig`, `PLATFORM_ROLE`, role constants).
- **Event bus** — [catalog.py](../../core/app/events/catalog.py) (`EventType` =
  `record.created`, `pii.revealed`; `CONSUMER_BINDINGS`), [envelope.py](../../core/app/events/envelope.py)
  (`build_envelope`, flat wire format, `demo_session_id` hardcoded `None`),
  [outbox.py](../../core/app/events/outbox.py) (`enqueue_event`, transactional),
  [consumers.py](../../core/app/events/consumers.py) (terminal `enrichment.stub` binds
  `record.created`; `sync.logger` binds `#`).
- **Audit** — `record_audit_event` + the `on_pii_revealed` seam (already emits audit +
  `pii.revealed`).
- **Migrations** — last is [0008_event_bus](../../core/alembic/versions/0008_event_bus.py);
  the per-tenant-table pattern (table-per-schema + indexes + grants from the registry) is
  [0006_pii_demo](../../core/alembic/versions/0006_pii_demo.py).
- **Seed** — [seed.py](../../core/app/seed.py): idempotent, seeds tenants/users/keys/settings
  and `pii_demo` rows per tenant (the pattern the lead seed follows).
- **Frontend** — public Shopper route `/site/:slug` with the
  [`shopper-home-quote-card` seam](../../frontend/src/pages/ShopperHomePage.tsx); the `/app/*`
  guarded zone in [App.tsx](../../frontend/src/App.tsx); the inert "Leads"
  [nav item](../../frontend/src/components/navSections.ts); the typed
  [API client](../../frontend/src/api/client.ts) + [types](../../frontend/src/api/types.ts)
  (snake_case mirror of the wire).

## 5. Proposed Design

Flow diagram: [tdd-P1.7-intake-flow.excalidraw](./diagrams/tdd-P1.7-intake-flow.excalidraw)
— the two routes converging on `lead.created`, the lead state machine, and the
duplicate-detection branch.

### 5.1 Components added / affected

Backend (`core/app/`):

- `models/lead.py` — new schema-less `Lead` ORM (resolved via `search_path`), modeled on
  `pii_demo`.
- `leads/` package — `router.py` (agent + read + action endpoints), `public_router.py`
  (the unauthenticated intake), `schemas.py` (request bodies), `state.py` (the status
  state-machine guard), `matching.py` (duplicate blind-index match), `masking.py` (the
  masked-lead read builder), `rate_limit.py` (in-app limiter).
- `tenancy/scoping.py` — add `get_public_tenant_db` (tenant from request slug, tenant role).
- `events/catalog.py` — add five `lead.*` `EventType` members; extend `enrichment.stub`
  binding to also bind `lead.created`.
- `tenancy/registry.py` — `TenantConfig` gains a keyed `product_lines` tuple.
- `demo/router.py` — `GET /api/tenants` entries gain `product_lines`.
- `config.py` — rate-limit knobs (`PUBLIC_INTAKE_RATE_LIMIT`, window).
- `seed.py` — minimal per-tenant `DEMO_LEADS` (several unassigned + one duplicate-bait).
- `main.py` — register the two lead routers.
- `alembic/versions/0009_leads.py` — per-tenant `leads` table + blind-index indexes +
  grants (tenant CRUD + `platform_reader` SELECT), mirroring `0006`.

Frontend (`frontend/src/`):

- Public intake form replacing `shopper-home-quote-card` (`pages/ShopperHomePage.tsx`),
  with prefill buttons, honeypot, client validation, success state.
- `pages/` — `LeadsPage` (list + queue tab), `LeadIntakePage` (`/app/leads/new`),
  `LeadDetailPage` (`/app/leads/:id`).
- `App.tsx` — `/app/leads`, `/app/leads/new`, `/app/leads/:id` children; `/site/:slug`
  unchanged (form drops into its seam).
- `components/navSections.ts` — flip `leads` to `comingLater: false`, `to: "/app/leads"`.
- `api/client.ts` + `api/types.ts` — lead calls + Lead/ProductLine types.

### 5.2 Data model — the `Lead` (per-tenant `leads` table)

Mirrors `pii_demo`: schema-less ORM, physical table created per tenant schema by migration.
`status` / `lead_source` are **text** columns (not PG `ENUM` — the P1.1 lesson), validated
app-side by `StrEnum`.

| Column | Type | Treatment / notes |
|---|---|---|
| `id` | uuid PK | app-side `uuid4` default |
| `first_name`, `last_name` | text NOT NULL | plaintext, searchable (matrix: "DB-at-rest only") |
| `email_encrypted` | bytea NOT NULL | app-layer encrypted |
| `email_blind_index` | bytea NOT NULL | HMAC blind index of normalized email (indexed) |
| `phone_encrypted` | bytea NOT NULL | app-layer encrypted (phone required at intake) |
| `phone_blind_index` | bytea NOT NULL | HMAC blind index of normalized phone (indexed) |
| `date_of_birth_encrypted` | bytea NOT NULL | app-layer encrypted |
| `age_band` | text NOT NULL | derived plaintext (`age_band_for`) |
| `zip_code` | text NOT NULL | plaintext (required; low-sensitivity, region) |
| `street_address_encrypted` | bytea NULL | app-layer encrypted (optional) |
| `product_lines_of_interest` | text[] NOT NULL | selected product-line **keys** (≥1) |
| `preferred_contact_method` | text NULL | plaintext (optional) |
| `notes` | text NULL | plaintext (optional; never in events/logs) |
| `lead_source` | text NOT NULL | `public_form` \| `agent_entered` |
| `status` | text NOT NULL | `New` \| `Working` \| `Qualified` \| `Rejected` (`Converted` reserved, P2.1) |
| `owner_user_id` | uuid NULL | the claiming/entering agent (no cross-schema FK) |
| `owner_username` | text NULL | denormalized owner display (tenant role can't read `platform.users`) |
| `duplicate_of_lead_id` | uuid NULL | the matched prior lead (set at intake when flagged) |
| `duplicate_resolution` | text NULL | `linked` \| `new` \| `rejected` (set by agent action) |
| `correlation_id` | uuid NOT NULL | minted at creation; reused by every later lead event |
| `demo_session_id` | uuid NULL | added now, left null; P1.8 owns lifecycle |
| `created_at` / `updated_at` | timestamptz | `now()` default; `updated_at` bumped on transitions |

Blind-index indexes `ix_leads_email_blind_index` / `ix_leads_phone_blind_index` are owned by
the migration (the table is schema-less and excluded from `alembic check`, per the `0006`
precedent).

### 5.3 State machine (`leads/state.py`)

```text
            (self-service intake)            (agent-entered intake)
                   │                                  │
                   ▼                                  ▼
                 New ──────── claim ──────────────► Working
                   │           (owner=self)            │
   duplicate-resolution reject │              qualify  │  reject
                   ▼                          ▼         ▼
                Rejected                  Qualified   Rejected
                                          (terminal; → Converted in P2.1)
```

- Self-service born `New` (owner null). Agent-entered born `Working` (owner = entering
  agent) — born owned is an implicit assignment, but emits **no** `lead.assigned` (no
  hand-off).
- `claim`: `New → Working`, owner = caller. `qualify`: `Working → Qualified`. `reject`:
  `Working → Rejected`. Duplicate-resolution `reject`: `New → Rejected`.
- A pure `assert_transition(current, target)` rejects any move outside the machine
  (`409`/`422` server-side).

### 5.4 Interfaces

**Events** (catalog additions; all via outbox, payloads carry entity ref + non-PII only):

| Event | When | Key payload (non-PII) | Consumers in P1.7 |
|---|---|---|---|
| `lead.created` | both intake routes | `entity_id`, `lead_source`, `status`, `product_lines_of_interest`, `age_band` | `enrichment.stub` (new binding), `sync.logger` |
| `lead.duplicate_detected` | intake match found | `entity_id`, `duplicate_of_lead_id` | `sync.logger` |
| `lead.assigned` | claim only | `entity_id`, `owner_user_id` | `sync.logger` |
| `lead.qualified` | qualify | `entity_id` | `sync.logger` |
| `lead.rejected` | reject (either path) | `entity_id`, `reason_kind` (`qualify_reject` \| `duplicate`) | `sync.logger` |

`correlation_id`: `lead.created` mints it (stored on the row); `duplicate_detected` rides
the same intake transaction and reuses it directly; `assigned`/`qualified`/`rejected` read it
back off the row so one lead's events share one correlation id (the future trace view).

**HTTP endpoints:**

- `POST /api/public/intake` — **unauthenticated**. Body: `tenant_slug`, intake fields,
  `website` (honeypot). `get_public_tenant_db(tenant_slug)`. Rate-limited per client IP
  (first `X-Forwarded-For` hop). Honeypot non-empty → silent drop (success-shaped response,
  nothing persisted). Validates, creates the lead (`New`, unowned, `public_form`), runs
  duplicate matching, publishes `lead.created` (+ `lead.duplicate_detected`). Sanitized
  response (`{ "ok": true }` / friendly confirmation) — **never** matched-lead data.
- `POST /api/leads` — auth, `require_capability(CREATE_EDIT_RECORDS)`, `get_tenant_db`.
  Creates the lead (`Working`, owner = session user, `agent_entered`), runs duplicate
  matching, publishes `lead.created` (+ `lead.duplicate_detected`). Returns the masked lead.
- `GET /api/leads?unassigned=true|false` — auth, `get_tenant_db`. Masked list; the
  `unassigned` filter (owner null & status `New`) backs the queue tab.
- `GET /api/leads/{id}` — auth, `get_tenant_db`. Masked detail (404 cross-tenant/missing).
- `POST /api/leads/{id}/claim` — auth, `require_capability(CLAIM_LEADS_MANAGE_TASKS)`.
  `New → Working`, owner = caller, `lead.assigned`.
- `POST /api/leads/{id}/qualify` — auth, `CREATE_EDIT_RECORDS`. `Working → Qualified`,
  `lead.qualified`.
- `POST /api/leads/{id}/reject` — auth, `CREATE_EDIT_RECORDS`. `Working → Rejected`,
  `lead.rejected`.
- `POST /api/leads/{id}/resolve-duplicate` — auth, `CREATE_EDIT_RECORDS`. Body
  `{ "action": "link" | "new" | "reject" }`: `link` sets `duplicate_resolution = linked`
  (keeps `duplicate_of_lead_id`); `new` clears the flag (`duplicate_resolution = new`,
  `duplicate_of_lead_id = null`); `reject` sets `New → Rejected` + `lead.rejected`
  (`reason_kind = duplicate`).
- `POST /api/leads/{id}/reveal` — auth, `require_capability(REVEAL_PII)`. Reuses the
  `pii_demo` reveal shape: one field, refuse unknown fields (422), decrypt, `await
  on_pii_revealed`, return `{ field, value }`.
- `GET /api/tenants` (extended) — each entry gains `product_lines: [{ key, label }]` (public).

**Public scoping seam** — `get_public_tenant_db(tenant_slug)`: resolve the registry config
for the slug (whitelist; unknown → 404), `SET LOCAL ROLE <db_role>` + `SET LOCAL search_path
TO <schema>`, yield. The slug-from-request is the **sole sanctioned exception** to "tenant
context only from session" (Decision #4), justified because the caller is unauthenticated
and the per-tenant role + schema boundary still physically prevent cross-tenant access.

### 5.5 Sequence — primary flows

**Self-service intake (public):** client POSTs to `/api/public/intake` with `tenant_slug` →
rate-limit check on IP → honeypot check (drop if filled) → Pydantic validation → resolve
tenant via `get_public_tenant_db` → encrypt email/phone/dob/(address), compute blind
indexes, derive `age_band` → INSERT lead (`New`, unowned) → blind-index match against tenant
leads → if matched, set `duplicate_of_lead_id` + enqueue `lead.duplicate_detected` →
enqueue `lead.created` (all on the one request transaction) → commit → sanitized `{ ok }`.

**Agent-entered intake:** same core, but `get_tenant_db` (session tenant), born `Working`
+ owner = session user, returns the masked lead.

**Queue → claim → qualify:** `GET /api/leads?unassigned=true` → agent clicks Claim →
`/claim` does `New → Working`, owner set, `lead.assigned` → `/qualify` does `Working →
Qualified`, `lead.qualified`.

**Duplicate resolution:** flagged lead shows the match → agent picks link / new / reject →
`/resolve-duplicate` updates `duplicate_resolution` (and rejects via the state machine for
`reject`).

## 6. Decisions

**D1 — Duplicate detection matches existing Leads (not Contacts).**
*Chosen:* blind-index match a new lead against prior **leads** in the tenant; flag
`duplicate_of_lead_id` + `duplicate_resolution`. *Alternatives:* pull a minimal read-only
Contact table forward; polymorphic match over both. *Rationale:* Contacts are a P2.1 entity;
matching leads is fully self-contained and demoable in P1.7 without co-owning Contact across
phases ("epics never span phases"). P2.1 adds a contacts branch + `duplicate_of_contact_id`
alongside, no rework of the lead path. "Link" records the linkage for P2.1 conversion to
honor.

**D2 — P1.7 ships its own minimal lead seed.**
*Chosen:* add a small per-tenant `DEMO_LEADS` (several unassigned `New` + one duplicate-bait)
as shared read-only seed (`demo_session_id` null). *Alternatives:* no seed (demonstrate by
submitting twice). *Rationale:* P1.7's acceptance requires a non-empty queue and a one-click
duplicate flag, but the full seed is P1.8, which *depends on* P1.7 — P1.7 cannot lean on it.
A minimal seed makes the slice demoable now; P1.8 supersedes it.

**D3 — `get_public_tenant_db` reuses the tenant role; slug-from-request is a documented carve-out.**
*Chosen:* new seam, tenant slug from the request, whitelist-validated, `SET LOCAL ROLE` the
tenant's existing CRUD role. *Alternatives:* a dedicated INSERT/SELECT-only public-intake
role per tenant; no role switch (login role + qualified INSERT). *Rationale:* the
unauthenticated public write genuinely cannot derive tenant from a session, so the slug is
the only source — and the per-tenant role + schema boundary still enforce isolation
physically. Reusing the existing role avoids a new role + grants for a single endpoint; the
endpoint code only INSERTs + SELECTs-for-match and returns a sanitized body. The
dedicated-role option remains an easy future hardening if desired.

**D4 — `demo_session_id` column now, lifecycle in P1.8.**
*Chosen:* add the nullable column to `leads` in `0009`, leave it null, keep the envelope's
`demo_session_id = None`. *Alternatives:* defer the column to P1.8; thread sessions now.
*Rationale:* the schema is cheaper to get right once (avoids a P1.8 ALTER), and the column
matches the envelope field already present — but there is no session backend to populate it,
and creation/expiry/purge is squarely P1.8's job (which depends on P1.7).

**D5 — Product lines are static keyed registry config exposed via `/api/tenants`.**
*Chosen:* `TenantConfig.product_lines` (key + label), folded into `GET /api/tenants`, stored
as `text[]` of keys on the lead (validated server-side). *Alternatives:* a seeded
`product_lines` table now. *Rationale:* product lines are fixed per-tenant config; the
registry is already the migration-safe single-source-of-truth for tenant config, and the
public form needs the list unauthenticated (which `/api/tenants` already serves). The real
catalog (products, carriers, rules) is P2 and would re-own a table built now.

**D6 — Claiming only; reassignment deferred.**
*Chosen:* build self-claim from the queue; defer Tenant-Admin reassign. *Alternatives:*
include minimal reassign now. *Rationale:* the demo presents one persona at a time, so
multi-agent reassignment isn't meaningfully demonstrable yet; reassign also needs a
cross-schema tenant-agent listing this phase doesn't otherwise require. The `lead.assigned`
event + `REASSIGN_LEADS_TASKS` capability are already in place for when it lands.

**D7 — In-app in-memory per-IP rate limiter.**
*Chosen:* a fixed-window per-IP limiter in the core app, keyed on the first `X-Forwarded-For`
hop, settings-configurable. *Alternatives:* nginx `limit_req`; a library. *Rationale:* it is
unit-testable (the gate wants tests) and visible in the abuse-controls explainer (the
security showcase), gives full local/prod parity, and adds no dependency. Single core process
makes in-memory state fine; reset-on-restart is acceptable for a demo.

**D8 — Publish-only enrichment; no enrichment UI.**
*Chosen:* P1.7 publishes `lead.created` (consumed by the existing stubs); no enrichment
results or "enriching → resolved" state on the lead. *Alternatives:* a static "pending"
placeholder. *Rationale:* the stubs are terminal/log-only; the visible enrichment story is
P1.9 (timeline) + M3 (real results). A perpetually-pending placeholder reads as broken.

**D9 — One Leads section, queue as a tab.**
*Chosen:* flip the single "Leads" nav item live → `/app/leads` (list with queue/all tabs);
detail at `/:id`; agent intake at `/app/leads/new`. *Rationale:* matches the existing
one-item nav model; `/new` is a clean deep-link target for prefill; a tab is lighter than a
second nav entry and a second list surface.

**D10 — Notes stored plaintext.**
*Chosen:* plaintext `notes` column. *Alternatives:* app-layer encrypted. *Rationale:* the
requirements' PII matrix deliberately omits notes (low-sensitivity synthetic free-text);
plaintext avoids inventing a masking/reveal policy for an unclassified field. Notes are never
placed in event payloads or logs regardless.

**D11 — Lead reads masked-by-default + audited click-to-reveal.**
*Chosen:* reuse the `pii_demo` masked read builder + the `REVEAL_PII`-gated reveal +
`on_pii_revealed`. *Alternatives:* masked only, reveal later. *Rationale:* masking is
required on every read anyway; with P1.4 (audit) + P1.6 (shell) done, the reveal pattern is
fully built and cheaply reused, making the PII-reveal-with-audit showcase real on the first
domain entity (walkthrough step 17).

**D12 — `status` / `lead_source` as text columns, not PG ENUM.**
*Chosen:* text + Python `StrEnum` validation. *Rationale:* avoids the P1.1 `sa.Enum`
double-`CREATE TYPE` migration footgun; matches existing text-backed vocabularies (`age_band`,
audit/event types).

## 7. Risks and Open Questions

- **R1 — Cross-schema owner display.** `owner_user_id` references `platform.users`, which the
  tenant role can't read. *Mitigation:* denormalize `owner_username` onto the lead at
  claim/intake time (the session identity already carries it). Accepted staleness: usernames
  are seed-fixed.
- **R2 — Public endpoint privilege.** The public route runs as the full tenant CRUD role.
  *Mitigation:* the endpoint only INSERTs + SELECTs-for-match and returns a sanitized body;
  the schema/role boundary is the isolation guarantee. A dedicated minimal-privilege role is
  recorded as an easy future hardening (D3).
- **R3 — `X-Forwarded-For` trust.** Rate limiting keys on a client-supplied header.
  *Mitigation:* nginx is the sole public entry point and sets it; the app reads the first hop.
  Documented as a demo-scale control, not a production WAF.
- **R4 — Duplicate-bait fragility.** The bait is a seeded lead; if normalization differs
  between seed and intake, the match misses. *Mitigation:* both paths route through the same
  `normalize_email`/`normalize_phone` + `compute_blind_index` (already proven in `pii_demo`);
  the acceptance suite asserts the bait flags.
- **R5 — Seed overlap with P1.8.** P1.7's minimal seed and P1.8's full seed must not collide.
  *Mitigation:* keep P1.7's lead seed insert-if-absent and clearly demarcated so P1.8 extends
  rather than conflicts.
- **Open:** none blocking — every decision is settled (§6).

## 8. Rollout / Verification

- **Migration:** `0009_leads` adds the per-tenant table + indexes + grants; reversible
  `downgrade` drops it per schema. `alembic check` drift-clean; `0009` down/up round-trip
  green. Deploys may reset + re-seed (acceptable pre-go-live), so the new seed runs on deploy.
- **No flags:** the feature is additive; the public router and lead routers are new surfaces.
  `DEMO_LOGIN_ENABLED` already gates the demo posture.
- **Backwards compatibility:** envelope unchanged (still `demo_session_id = None`); existing
  consumers unaffected (`sync.logger` already binds `#`; `enrichment.stub` gains one routing
  key). The event catalog grows by five members — additive, asserted in `test_event_catalog`.
- **Manual verification (local stack, either route):**
  1. From `/site/:slug`, submit the public form (or a prefill) → lead lands in the
     unassigned queue at `/app/leads`.
  2. From `/app/leads/new`, enter a lead as an agent → it is born owned (not in the queue).
  3. Submit the "Try a duplicate scenario" prefill → the lead is flagged; resolve it
     (link / new / reject).
  4. Claim a queued lead → `New → Working`; qualify or reject it.
  5. Open a lead's detail → PII masked; click-to-reveal a field → value shown and audited
     (`GET /api/audit` as Tenant Admin shows `pii.revealed`).
  6. Switch tenant → the other tenant's leads/queue are absent (isolation).
  7. RabbitMQ management UI: queue depth moves as `lead.*` events flow.
- **Automated:** the green gate runs the full backend `pytest` (incl. the new acceptance
  suite on the real Postgres + RabbitMQ substrate) and the full frontend Vitest, plus
  `tsc -b && vite build`.

## 9. Work Breakdown

Simplest-first; the system stays runnable/deployable after each. Many small items so the
epic plan inherits a layered shape (an L phase — expect a split at epic-plan time).

1. **Event vocabulary** — add the five `lead.*` `EventType` members; extend `enrichment.stub`
   binding to `lead.created`; update `test_event_catalog`.
2. **Lead status/source vocabulary + state machine** — `leads/state.py` (`StrEnum`s +
   `assert_transition`), pure-unit-tested.
3. **Migration `0009_leads` + `Lead` ORM** — per-tenant table, blind-index indexes, grants
   (mirror `0006`); schema-less model; `alembic` round-trip test.
4. **Product-line config** — `TenantConfig.product_lines`; fold into `GET /api/tenants`;
   catalog/registry tests.
5. **Masked lead read builder** — `leads/masking.py` (`_masked_lead`, reusing the PII
   service + maskers); unit-tested.
6. **Duplicate matcher** — `leads/matching.py` (normalize → blind index → equality query
   over tenant leads); unit + DB test (match without decryption).
7. **Agent intake (walking skeleton)** — `POST /api/leads`: create (`Working`/owned), encrypt
   fields, run matcher, enqueue `lead.created` (+ `lead.duplicate_detected`), masked
   response; the first end-to-end intake slice.
8. **Public scoping seam** — `get_public_tenant_db(tenant_slug)` + whitelist + tests.
9. **In-app rate limiter** — `leads/rate_limit.py` + config knobs; unit-tested.
10. **Public intake** — `POST /api/public/intake`: honeypot silent-drop, validation,
    `get_public_tenant_db`, create (`New`/unowned/`public_form`), matcher, `lead.created`,
    sanitized response.
11. **Lead reads** — `GET /api/leads` (+ `unassigned` filter) and `GET /api/leads/{id}`,
    masked, tenant-scoped.
12. **Claim** — `POST /api/leads/{id}/claim` (`New → Working`, owner, `lead.assigned`).
13. **Qualify / reject** — `POST .../qualify`, `.../reject` (transitions + events).
14. **Duplicate resolution** — `POST .../resolve-duplicate` (`link` / `new` / `reject`).
15. **Lead PII reveal** — `POST /api/leads/{id}/reveal` (reuse reveal shape + `on_pii_revealed`).
16. **Seed** — minimal per-tenant `DEMO_LEADS` (unassigned + bait), insert-if-absent.
17. **Frontend API client + types** — lead calls, Lead/ProductLine types.
18. **Public Shopper intake form** `[UI]` — replace `shopper-home-quote-card`; fields,
    honeypot, client validation, prefills ("Typical lead", "Try a duplicate scenario"),
    success state.
19. **Agent intake form** `[UI]` — `/app/leads/new`.
20. **Leads list + queue tab + claim** `[UI]` — `/app/leads`; flip the nav item live.
21. **Lead detail + actions** `[UI]` — `/app/leads/:id`; masked PII + click-to-reveal +
    qualify / reject / resolve-duplicate.
22. **Acceptance suite + green-gate pass** — `test_lead_intake_acceptance.py` (both routes,
    born states, dup flag + events + resolution, claim + `lead.assigned`, qualify/reject +
    events, A-vs-B isolation, blind-index match without decryption, abuse controls: rate
    limit + honeypot + validation, sanitized public response) + frontend tests; full suite
    green.
