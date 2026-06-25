# Lead Conversion (P2.1) — Technical Design Document

> **Build strategy:** Tracer bullet — chosen at design time (rationale in §6); `3-tdd-to-epic-plan` copies this to the epic plan and `4-plan-epic` honors it (`0-conventions.md` → *Build strategies*).

## 1. Summary
Let an agent turn a **Qualified** lead they hold into a live customer in one atomic action: create a Contact, place it in a Household (new or linked), open one Opportunity per product line of interest (owned by the agent), carry the lead's notes over as a note-Task, and freeze the lead `Converted` — all in one database transaction that also emits the conversion events through the existing transactional outbox. This is Milestone 2's first phase: it births the core CRM entities (Contact, Household, Opportunity, Task) every later sales workflow builds on, and delivers the demo's "step 7" moment. The design reuses the proven P1.x seams wholesale (the `create_lead` transactional-outbox idiom, P1.3 field encryption, the per-tenant schema-less ORM + migration pattern, the demo-session isolation/purge backbone), so the **architecture is low-risk and the UX/flow is where the risk sits** — hence the tracer bullet.

## 2. Business Requirements
Source: [./brd-lead-conversion.md](./brd-lead-conversion.md) — the agreed requirements, not re-narrated here. Clarifications surfaced during this design that the BRD doesn't state outright:

- **Holder gate is new.** No existing lead action checks ownership; `convert` adds an explicit `owner_user_id == caller` check (BRD FR §1).
- **Confirmed product lines = any valid tenant key, ≥1.** The agent confirms the lead's recorded lines or, when the lead has none, chooses from the tenant's lines; the server validates each against the tenant's key set (the existing `POST /api/leads` check) and rejects an empty set. Not required to be a strict subset of the lead's recorded lines.
- **Pre-select requires a converted prior.** The duplicate pre-select resolves `duplicate_of_lead_id → prior lead's converted_contact_id → contact.household_id`. If the prior lead isn't converted, there's nothing to pre-select — the screen defaults to "new household" (graceful, the agent may still link manually).
- **No `task.created` event.** BRD §6 announces exactly four kinds (lead converted, contact created, household created when new, opportunity created ×N); the note-Task is created silently.
- **No Contact/Household/Opportunity detail pages this phase.** Created entities are proven visible through a conversion-summary panel on the frozen lead and through the household picker's member list; full detail views are P2.2+/P2.5.
- **`Converted` is terminal + read-only.** No outgoing state-machine edges; mutating endpoints refuse a converted lead.
- **Forced failure is test-level.** Atomicity is proven by a test that makes a mid-conversion step raise; no production failure-injection input (that's M3 sidecar simulation).

## 3. Goals / Non-Goals
**Goals**
- One atomic action converts a held Qualified lead into Contact + Household (new or linked) + one Opportunity per product line + (optional) note-Task; freezes the lead `Converted`, stamped with what it became.
- Emit `contact.created`, `household.created` (new only), `opportunity.created` ×N, `lead.converted` — all in the same transaction via the outbox, all carrying the lead's `correlation_id` + `demo_session_id`.
- Every created entity stays tenant-scoped + demo-session-tagged; a second session/tenant sees and purges none of it.
- The created customer is visibly proven (summary panel + household picker) without building full entity detail views.

**Non-Goals**
- Opportunity stage transitions / per-tenant stage config (P2.2); premium/quote wiring (P2.3).
- Rich Task queue / due dates / assignment routing (P2.4).
- Contact merge/dedup; address-based household matching; renaming households; un-converting.
- Contact/Household/Opportunity masked detail views + their own timelines (P2.2+/P2.5).
- Seeding a converted baseline (the duplicate pre-select is exercised by a live two-step).

## 4. Current State
Relevant existing code the design reuses or extends:

- [core/app/leads/intake.py](../../core/app/leads/intake.py) — `create_lead`: the transactional-outbox create idiom (encrypt → insert → flush → enqueue, no commit) the conversion service mirrors.
- [core/app/leads/router.py](../../core/app/leads/router.py) — the lead action endpoints + `_guard_loaded_lead_for_session` (foreign session 404 / seed 409) the `convert` endpoint reuses; the `POST /api/leads` tenant product-line key check.
- [core/app/leads/state.py](../../core/app/leads/state.py) — `LeadStatus` / `LeadSource` StrEnums + `assert_transition`; gains `CONVERTED` + the `Qualified→Converted` edge.
- [core/app/models/lead.py](../../core/app/models/lead.py) — the schema-less ORM twin pattern; gains `converted_contact_id` / `converted_opportunity_ids`.
- [core/app/leads/masking.py](../../core/app/leads/masking.py) — `build_masked_lead`; gains the two converted-ref fields.
- [core/app/events/catalog.py](../../core/app/events/catalog.py) — `EventType` + `CONSUMER_BINDINGS`; gains four members. `sync.logger` binds `#` (auto-reacts, no broker/consumer change); `enrichment.stub` binds only `record.created`/`lead.created` (does not react).
- [core/app/events/envelope.py](../../core/app/events/envelope.py) / [outbox.py](../../core/app/events/outbox.py) — `build_envelope` + `enqueue_event`, reused verbatim.
- [core/app/pii/service.py](../../core/app/pii/service.py) + [pii/masking.py](../../core/app/pii/masking.py) — `encrypt_field` / `age_band_for`; the Contact reuses them (no blind index).
- [core/alembic/versions/0009_leads.py](../../core/alembic/versions/0009_leads.py) — the per-tenant `CREATE TABLE` + grant shape migration 0015 follows.
- [core/app/demo/purge.py](../../core/app/demo/purge.py) — the per-session delete sweep + `PurgeCounts`; extended to the four new tables. `DEMO_PURGE_ROLE` in [tenancy/registry.py](../../core/app/tenancy/registry.py).
- [core/app/leads/visibility.py](../../core/app/leads/visibility.py) — `visible_to_session` (NULL baseline + caller's session) the household search reuses.
- [frontend/src/pages/LeadDetailPage.tsx](../../frontend/src/pages/LeadDetailPage.tsx) + [LeadActionsSection.tsx](../../frontend/src/pages/LeadActionsSection.tsx) — the lead detail surface gaining the Convert affordance + "Converted to" panel.
- [frontend/src/api/types.ts](../../frontend/src/api/types.ts) + the api client — the wire-shape mirror + call sites for the new endpoints.

Latest migration is `0014`; latest event types end at `lead.rejected`. Tenants/product lines come from `tenancy/registry.py`.

## 5. Proposed Design

### 5.1 Data model (migration 0015, per tenant schema; schema-less ORM twins)
- **`households`** — `id`, `name` text (auto `"<LastName> Household"`), `correlation_id`, `demo_session_id`, `created_at`/`updated_at`. No owner (account-like, shared across its contacts).
- **`contacts`** — `id`, `household_id`; plaintext `first_name`/`last_name`/`zip_code`/`age_band`; encrypted `bytea` `email_encrypted`/`phone_encrypted`/`date_of_birth_encrypted`/`street_address_encrypted` (P1.3, per-tenant key + tenant-id AAD); `lead_source`; `owner_user_id`/`owner_username` (converting agent); `source_lead_id`; `correlation_id`; `demo_session_id`; timestamps. **No blind-index columns** (contact dedup is out of scope).
- **`opportunities`** — `id`, `contact_id`, `household_id` (rollup), `product_line` text (the key), `stage` text default `'New'` (no state-machine call — P2.2 owns transitions), `owner_user_id`/`owner_username`, `estimated_annual_premium` numeric NULL (P2.3), `target_close_date` date NULL (P2.2/P2.3), `origin` text `'conversion'`, `source_lead_id`, `correlation_id`, `demo_session_id`, timestamps.
- **`tasks`** — `id`, polymorphic `related_entity_type` text / `related_entity_id` uuid (`'contact'` here), `task_type` text (`'note'`), `body` text (plaintext, carried from `lead.notes`), `assignee_user_id`/`assignee_username` (converting agent), `due_date` timestamptz NULL (P2.4), `status` text NULL (P2.4), `correlation_id`, `demo_session_id`, timestamps.
- **`leads`** ALTER ADD `converted_contact_id` uuid NULL, `converted_opportunity_ids` uuid[] NULL.
- **Grants** (per table, the 0009 shape): tenant `db_role` SELECT/INSERT/UPDATE/DELETE; `platform_reader` SELECT; **`demo_purge` SELECT+DELETE** on all four.
- All four ORM models are schema-less (resolved via `search_path`, excluded from `alembic check`), so the migration **owns** any indexes.

### 5.2 State machine + masked read
- `LeadStatus.CONVERTED = "Converted"`; `assert_transition` allows `Qualified → Converted` only; `Converted` is terminal (no outgoing edges → claim/qualify/reject all 409 on a converted lead).
- `build_masked_lead` adds `converted_contact_id` / `converted_opportunity_ids` (raw uuid strings / array, or `null`). No new PII.

### 5.3 Events (catalog additions)
`LEAD_CONVERTED = "lead.converted"`, `CONTACT_CREATED = "contact.created"`, `HOUSEHOLD_CREATED = "household.created"`, `OPPORTUNITY_CREATED = "opportunity.created"`. `CONSUMER_BINDINGS` unchanged (`sync.logger`'s `#` catches them; `enrichment.stub` does not). `test_event_catalog` expectation extended.

Payloads (non-PII refs only — never names/contact values):
- `contact.created` → `{entity_id: contact.id, household_id, source_lead_id}`
- `household.created` (new only) → `{entity_id: household.id}`
- `opportunity.created` ×N → `{entity_id: opp.id, contact_id, household_id, product_line}`
- `lead.converted` → `{entity_id: lead.id, converted_contact_id, converted_opportunity_ids}`

All built with `build_envelope(correlation_id=lead.correlation_id, causation_id=None, demo_session_id=…)` and enqueued via `enqueue_event` on the request session.

### 5.4 Conversion service — `app/leads/conversion.py` `convert_lead(...)`
Runs on the caller's request session, **no commit** (the request transaction makes it atomic), mirroring `create_lead`. In order:
1. **Household** — `new`: insert a Household, name `f"{contact_last_name} Household"`, stamped with the lead's `correlation_id` + `demo_session_id`; emit `household.created`. `link`: load the chosen `household_id` (session-visible; else error), reuse it, no event, no re-stamp.
2. **Contact** — encrypt the lead's PII fields onto a new Contact (reuse `encrypt_field`; `age_band` re-derived/carried), `household_id` set, owner = converting agent, `source_lead_id` = lead.id, `correlation_id`/`demo_session_id` from the lead; flush; emit `contact.created`.
3. **Opportunities** — one per confirmed product line: insert with `contact_id`/`household_id`, `stage='New'`, `origin='conversion'`, owner = agent, `source_lead_id`, correlation/session; flush; emit `opportunity.created` per row.
4. **Note-Task** — only when `lead.notes` is non-empty: insert a `tasks` row (`related_entity_type='contact'`, `related_entity_id=contact.id`, `task_type='note'`, `body=lead.notes`, assignee = agent). No event.
5. **Freeze the lead** — `status='Converted'`, `converted_contact_id=contact.id`, `converted_opportunity_ids=[…]`; flush; emit `lead.converted`.

Returns the (now-frozen) `Lead`. No audit record (the audit enum has no member; observed via the outbox events).

### 5.5 Endpoints (in `leads/router.py` unless noted)
- **`POST /api/leads/{id}/convert`** → 200 `{lead: <masked frozen>}`. Guards in order: `require_capability(CREATE_EDIT_RECORDS)`; `_guard_loaded_lead_for_session(refuse_seed=True)`; **holder** (`owner_user_id == caller` else 403); status via `assert_transition(Qualified→Converted)` (else 409). Body `ConvertLeadRequest`: `{household: {mode:"new"} | {mode:"link", household_id}, product_lines: [key,…]}`; ≥1 product line + each a valid tenant key (else 422); `household_id` required when `mode="link"`. Calls `convert_lead`.
- **`GET /api/households?q=`** → `{households: [{id, name, members: [{first_name, last_name}]}]}`. Tenant-scoped, name-`ILIKE`-match, **`visible_to_session`** applied (NULL baseline + caller's session). Members = the household's contacts (plaintext names only). Backs the link picker.
- **`GET /api/leads/{id}/conversion-prefill`** → `{preselected_household: {id, name} | null}`. For a flagged lead, resolves the chain server-side; null otherwise. Same lead-visibility guard as `get_lead`.
- **`GET /api/leads/{id}/conversion`** → `{contact: {id, first_name, last_name}, household: {id, name}, opportunities: [{id, product_line, stage}]}` for a converted lead (else 409/404). Non-PII display fields; feeds the frozen-lead panel.
- **Frozen read-only:** `resolve-duplicate` gains a guard refusing a `Converted` lead (409); claim/qualify/reject already 409 via the state machine.

### 5.6 Isolation + purge
- Created entities inherit the lead's `demo_session_id`, so `visible_to_session` + the foreign-session 404 guard cover reads.
- `purge.py` deletes from `opportunities`, `tasks`, `contacts`, `households` (then `leads`) `WHERE demo_session_id = ANY(:ids)`; `PurgeCounts` gains the four counts. `0015` grants `demo_purge` the needed DELETE.

### 5.7 Frontend
- **Convert affordance** on lead detail: shown for `status==="Qualified"` + holder + `create_edit_records` + `!is_seed` → links to `/app/leads/:id/convert`.
- **`/app/leads/:id/convert`** review-and-confirm page: read-only mapped contact details (reuse the masked lead read); household choice (create-new default, or search+link via `GET /api/households`); product-line confirm/choose (lead's lines pre-checked; if none, must pick ≥1; commit blocked at zero); pre-select resolved via `conversion-prefill`. Commit → `POST .../convert` → navigate to the frozen lead detail.
- **"Converted to" panel** on a `Converted` lead detail (reads `GET .../conversion`): contact name, household name, opportunities by product-line label + stage. Status stamp flips to `Converted`; mutating actions hidden.
- `api/types.ts` + client gain `ConvertLeadRequest`, the household/prefill/summary shapes, and `convertLead`/`searchHouseholds`/`getConversionPrefill`/`getConversionSummary`. Every rendered element gets a unique `id`.

## 6. Decisions

**D1 — Contact PII: mirror the Lead, omit blind indexes.**
Chosen: Contact re-encrypts email/phone/DOB/street with P1.3 and keeps plaintext names/zip/age_band, but has **no** blind-index columns. Alternatives: full mirror incl. blind index (forward-compat); reference the lead's PII (no copy). Rationale: contact merge/dedup is explicitly out of scope, so the only thing blind indexes buy (fingerprint matching) has no consumer this phase — carrying unused crypto columns is dead weight; referencing the lead couples Contact lifetime to a frozen lead and breaks the "Contact is the customer of record" model.

**D2 — Task: polymorphic shell, plaintext body.**
Chosen: one `tasks` table with `(related_entity_type, related_entity_id)`, `task_type`, plaintext `body`. Alternatives: encrypted body; two FK columns without polymorphism. Rationale: the domain model names Task as polymorphic across Lead/Contact/Opportunity/Policy, so the shape must be polymorphic from birth or every later phase re-migrates; the body is agent-authored free text identical in sensitivity to `lead.notes`/`rejection_reason`, both already plaintext, so encryption would be inconsistent and unjustified.

**D3 — Opportunity carries both FKs + placeholder value fields.**
Chosen: `contact_id` + `household_id` (rollup), `stage` text `'New'`, nullable premium/close-date, `origin`/`source_lead_id`. Alternative: contact_id only, re-derive the rest. Rationale: the domain model defines the Household rollup as normative and P2.2/P2.3/P2.4 all read these columns; adding them now is one migration vs three later, and a literal `'New'` avoids pulling the P2.2 stage machine forward.

**D4 — One migration (0015) for all four tables + the lead ALTER.**
Chosen: a single per-tenant migration. Alternative: one migration per table. Rationale: the 0007 (audit) and 0008 (event-bus) precedents both create a phase's multiple per-tenant tables in one migration; splitting adds churn with no isolation or reversibility benefit.

**D5 — `POST /convert`, holder + Qualified guarded, `convert_lead` core, 200 + masked frozen lead.**
Chosen: a single action endpoint returning the frozen lead; created entities are side effects stamped on the lead. Alternatives: 201 returning all created entities; drop the holder check. Rationale: the lead is the addressed resource and the only entity with a masked-read builder this phase, so returning it (with refs) avoids building throwaway masked builders for entities whose detail views don't exist yet; the holder check is mandated by FR §1.

**D6 — Four new event types, non-PII payloads, shared `correlation_id`, `causation_id` None.**
Chosen: reuse the lead's `correlation_id` on every event, leave causation None (matches existing lead events). Alternative: chain `causation_id` to the `lead.converted` event id. Rationale: the M2 invariant is correlation propagation; causation is reserved for renewals (a *new* correlation in P2.4). Chaining causation would force `lead.converted` to be built first and diverge from every existing lead event, for trace detail P2.5 doesn't need within a single atomic action.

**D7 — Extend purge to all five tables + reuse `visible_to_session`.**
Chosen: the purge sweep and the new reads both ride the existing isolation backbone. Alternative: purge only, defer read-scoping. Rationale: tenant+session isolation is the program's cross-cutting invariant and an explicit acceptance criterion (a second session sees none of it); an un-scoped household search would leak another session's household names, failing it — so read-scoping isn't deferrable.

**D8 — Duplicate pre-select resolves via the chain; no new seed.**
Chosen: resolve `duplicate_of_lead_id → converted_contact_id → household_id` server-side; graceful "new" default when the prior isn't converted; acceptance/demo does a live two-step. Alternative: seed a converted baseline per tenant. Rationale: seeding converted entities is real scope (build entities + freeze the prior + arguably backfill events) for a secondary acceptance path; the live two-step proves the same behavior and keeps the tracer-bullet small.

**D9 — Build strategy: tracer bullet.**
Chosen: thinnest customer-visible convert first, then layer. Alternative: walking skeleton. Rationale: the architecture is almost entirely reused proven seams (outbox create idiom, P1.3 crypto, schema-per-tenant, purge) — there's little integration risk to de-risk with a skeleton — whereas the conversion *flow/UX* (household picker, product-line confirm, pre-select, the frozen "what it became" moment) is the unknown, so the fastest feedback comes from a working end-to-end conversion early.

## 7. Risks and Open Questions
- **Frozen read-only completeness.** A `Converted` lead must reject every mutation. The state machine covers claim/qualify/reject; `resolve-duplicate`'s `link`/`new` branches mutate without a status guard — mitigated by the explicit frozen guard (§5.5). Verified by an acceptance assertion.
- **Linking a baseline household from a session.** A session-tagged contact may link to a NULL-baseline household; on purge the contact/opp are deleted but the baseline household survives (correct). The household search must still only *surface* session-visible households — covered by `visible_to_session`.
- **`uuid[]` round-trip.** `converted_opportunity_ids` is a Postgres `uuid[]` (the `product_lines_of_interest` text[] precedent); confirm the masked read serializes it as a JSON array of strings.
- **Migration drift gate.** The four schema-less tables must be excluded from `alembic check` like `Lead`/`PiiDemoRecord` (the migration owns indexes) — confirm `env.py include_object` covers them.
- **Open:** none at the design level; the household picker's match limit/ordering is a minor implementation detail (reuse the lead-list cap idiom).

## 8. Rollout / Verification
- **Migrations:** `0015` is additive (new tables + nullable lead columns + grants); down-migration drops the four tables and the two columns. `alembic check` drift-clean + `0015` down/up round-trip green on the real-Postgres substrate.
- **No feature flag / backwards compat:** purely additive; existing lead lifecycle untouched except the new terminal status and the additive masked-read fields (the FE union mirrors them by hand — add `"Converted"` to `LeadStatus`).
- **Manual verification (walkthrough step 7):** sign in as the holding agent of a Qualified lead → Convert → (new household, confirm product lines) → commit → land on the frozen lead showing `Converted` + the "Converted to" panel (contact, household, opportunities); the lead timeline shows `lead.converted` + its `sync.logger` reaction. Duplicate path: convert lead A, then convert a duplicate B flagged against A → B's household pre-selected, a *new* Contact created. Forced failure: lead stays `Qualified`, nothing created. Second session/tenant: sees none of it; session reset/purge removes all created rows.
- **Green gate** before merge (full backend + frontend suites + `tsc -b && vite build`), incl. the named `test_lead_conversion_acceptance.py`.

## 9. Work Breakdown
Ordered simplest-first, tracer-bullet (item 4+5 is the thinnest customer-visible end-to-end thread; everything after layers on it). Favor small items.

1. **Migration 0015** — `households`/`contacts`/`opportunities`/`tasks` per tenant + grants (tenant CRUD, `platform_reader` SELECT, `demo_purge` SELECT+DELETE) + ALTER `leads` ADD `converted_contact_id`/`converted_opportunity_ids`; substrate down/up test.
2. **ORM + state + masked read** — four schema-less ORM twins; `LeadStatus.CONVERTED` + `Qualified→Converted` edge (terminal); `Lead` model + `build_masked_lead` gain the two converted fields; FE `LeadStatus` union adds `"Converted"`.
3. **Catalog** — four new `EventType` members + `test_event_catalog` expectation.
4. **`convert_lead` core + `POST /convert`** — atomic new-household + Contact + N opportunities (from the lead's lines) + note-Task (if notes) + freeze + emit the four event types (shared `correlation_id`), on the request transaction; endpoint guards cap/session/holder/Qualified; `ConvertLeadRequest` (new-household mode only here).
5. **Frontend tracer** — Convert affordance on a Qualified held lead → minimal confirm → `convertLead` → frozen lead detail with `Converted` stamp. *(Now a real conversion is demoable end-to-end.)*
6. **Review-and-confirm screen** — `/app/leads/:id/convert`: read-only mapped details + product-line confirm/choose (≥1-or-blocked) + new-household default; replaces the minimal confirm.
7. **Conversion summary** — `GET /api/leads/{id}/conversion` + the "Converted to" panel on the frozen lead.
8. **Household link path** — `GET /api/households?q=` (session-scoped, members) + picker UI (create-new vs link) + `ConvertLeadRequest` link mode + `convert_lead` link branch.
9. **Duplicate pre-select** — `GET /api/leads/{id}/conversion-prefill` (resolve the chain) + screen pre-selects it (override allowed).
10. **Isolation hardening** — `purge.py` + `PurgeCounts` extend to the four tables; `resolve-duplicate` frozen guard; confirm household-search session scoping.
11. **Acceptance suite** — `test_lead_conversion_acceptance.py`: happy path (all entities + freeze + four event types incl. `opportunity.created` ×N, correlation shared), duplicate pre-select + new-Contact, forced-failure rollback (monkeypatch a mid-convert step), cross-session isolation + purge; FE acceptance block for the convert flow + frozen panel.
