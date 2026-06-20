# P1.7 — Lead Intake, Queue, Qualification & Duplicate Detection — Epic Plan

Source TDD: [./tdd-P1.7-lead-intake-queue-qualification-duplicate-detection.md](./tdd-P1.7-lead-intake-queue-qualification-duplicate-detection.md)

> **Review budget:** ~150 changed lines · ~8 non-generated files · one focused commit per epic. Tunable per project.

> High-level agile roadmap. Each epic's design specifics are confirmed with stakeholders at epic time (`4-plan-epic`) before any code is written.

This is an **L phase** (the TDD anticipated a layered split). The order is simplest-first: pure
vocabulary and unit-testable building blocks land first, then the first end-to-end intake slice,
then the remaining endpoints, then the frontend, then the acceptance gate. Backend is isolated
from its UI throughout; UI-bearing epics carry ` [UI]`.

## Epic 1 — Lead event vocabulary — **COMPLETED**
- **Goal:** Add the five `lead.*` event types to the catalog and bind `enrichment.stub` to also receive `lead.created`, so the rest of the phase can publish lead events through the existing outbox.
- **Rough scope:** Event catalog (the `EventType` members + consumer binding) and its catalog test. No publishing yet.
- **Open questions / decisions for stakeholders:** none expected — the five events and their payload fields are spelled out in the TDD interfaces table.
- **Depends on:** none.
- **Implementation notes:** The five `lead.*` `EventType` members now exist and `enrichment.stub` binds `lead.created`, so Epics 7/10/12-14 publish lead events through the existing outbox without re-touching the catalog.

## Epic 2 — Lead status / source vocabulary + state machine — **COMPLETED**
- **Goal:** A pure, unit-tested state machine that defines the lead's statuses and sources and rejects any transition outside the allowed moves (`New → Working → Qualified | Rejected`, plus the duplicate-reject from `New`).
- **Rough scope:** A `leads/state.py`-style module of string enums and a pure `assert_transition` guard, with unit tests. No persistence, no endpoints.
- **Open questions / decisions for stakeholders:** none expected — the machine is fully drawn in the TDD.
- **Depends on:** none.
- **Implementation notes:** Epics 12–14 catch the framework-free `InvalidLeadTransition` at the endpoint edge and map it to HTTP 409/422 — the core (`app/leads/state.py`) never imports the web framework. `Converted` and the `Qualified → Converted` transition are deferred to P2.1; do not add them in P1.7.

## Epic 3 — Lead table migration + ORM model — **COMPLETED**
- **Goal:** Create the per-tenant `leads` table (columns, blind-index indexes, grants) via a new migration and a schema-less `Lead` ORM modeled on `pii_demo`, leaving the system migratable and round-trippable.
- **Rough scope:** One new Alembic migration mirroring the `pii_demo` per-schema pattern, the ORM model, and a migration up/down round-trip test. No business logic on top.
- **Open questions / decisions for stakeholders:** none expected — the column set is fixed in the TDD data-model table.
- **Depends on:** none.
- **Implementation notes:** Shared schema-less `Lead` model (`app/models/lead.py`) + per-tenant `leads` table (`0009_leads`) are the substrate Epics 5–7 and 11–15 build on — don't re-create the model/table. Migration owns both blind-index indexes (`ix_leads_email_blind_index` / `ix_leads_phone_blind_index`); the model declares none (schema-less → excluded from `alembic check`). `demo_session_id` exists but stays null — P1.8 owns its lifecycle.

## Epic 4 — Product-line registry config — **COMPLETED**
- **Goal:** Expose a per-tenant list of product lines (key + label) as static registry config, surfaced unauthenticated through the existing `GET /api/tenants`, so both intake forms can offer the choices and the server can validate submitted keys.
- **Rough scope:** Add a keyed `product_lines` field to the tenant registry config, fold it into the tenants response, and cover it with catalog/registry tests.
- **Open questions / decisions for stakeholders:** none — resolved at plan time.
- **Depends on:** none.
- **Implementation notes:** The snake_case product-line keys are the stored vocabulary and a cross-epic contract — Epics 7/10 validate submitted lead keys against the per-tenant set, Epics 18/19 render the labels, Epic 16's duplicate-bait seed must use these keys; renaming one is a contract change. Sunshine: `medicare_advantage`, `medicare_supplement`, `final_expense`, `dental_vision_hearing`. Florida: `term_life`, `whole_life`, `health`, `critical_illness`. Surfaced as a `product_lines: [{key, label}, ...]` array on each `GET /api/tenants` entry — the wire source Epics 17/18 read for the choices.

## Epic 5 — Masked lead read builder — **COMPLETED**
- **Goal:** A reusable builder that turns a `Lead` row into the masked shape returned on every read, reusing the PII service and the existing maskers.
- **Rough scope:** A `leads/masking.py`-style helper plus unit tests; no endpoint wiring yet.
- **Open questions / decisions for stakeholders:** none — resolved at plan time. One shared masked shape serves both list and detail (no divergent shapes, mirroring `pii_demo`'s single builder); street address reuses `mask_generic` (`***` present / `null` absent, no decrypt, like dob); blind indexes, `correlation_id`, and the always-null `demo_session_id` are excluded from the read.
- **Depends on:** Epic 3.
- **Implementation notes:** Single masked read shape lives in `app/leads/masking.py` (`build_masked_lead`, async) — Epics 7 & 11 return it verbatim and UI Epics 20/21 consume it; do **not** add a second list/detail shape. Owner + duplicate-linkage fields are in the shape (queue needs owner/status, detail needs the match); blind indexes / `correlation_id` / `demo_session_id` never reach the wire.

## Epic 6 — Duplicate matcher — **COMPLETED**
- **Goal:** A deterministic matcher that, given a new lead's normalized email/phone, finds a prior matching lead in the tenant via the blind index — without decrypting anything.
- **Rough scope:** A `leads/matching.py`-style module (normalize → blind index → equality query over tenant leads) with a unit test and a DB-backed test proving the match works without decryption.
- **Open questions / decisions for stakeholders:** none — resolved at plan time.
- **Depends on:** Epic 3.
- **Implementation notes:** `app/leads/matching.py` exposes `find_duplicate_lead(db, tenant_id, email, phone, exclude_lead_id=None) -> Lead | None` (pure; one OR equality query over the `*_blind_index` columns, no decryption); Epics 7 & 10 call it after INSERT (passing the new lead's id as `exclude_lead_id`) and set `duplicate_of_lead_id = match.id` on a hit. Match semantics are a cross-epic contract: **email OR phone** blind-index match, **oldest wins** (`created_at`, then `id`), **`Rejected` targets excluded** (`New`/`Working`/`Qualified` eligible). Epic 16's duplicate-bait must be a non-`Rejected` lead whose normalized email/phone equals the demo's duplicate-scenario intake, or it won't flag.

## Epic 7 — Agent intake (walking skeleton) — **COMPLETED**
- **Goal:** The first end-to-end intake slice: an authenticated `POST /api/leads` that creates a lead (born `Working`, owned by the entering agent, `agent_entered`), encrypts the PII fields, runs the matcher, publishes `lead.created` (plus `lead.duplicate_detected` on a match), and returns the masked lead.
- **Rough scope:** The agent lead router/create handler, request schema, and the create-path wiring of state + encryption + matcher + outbox; intake-focused tests. Reuses the building blocks from Epics 1–6.
- **Open questions / decisions for stakeholders:** none — resolved at plan time. Required: `first_name`, `last_name`, `email`, `phone`, `date_of_birth`, `zip_code`, `product_lines_of_interest` (≥1 key); optional: `street_address`, `preferred_contact_method`, `notes`. Submitted product-line keys validated against the caller's tenant registry set (unknown → 422); no other agent-route hardening (length caps/abuse controls are Epic 10's). Observability: `lead.created` (+ `lead.duplicate_detected`) only, no audit-store record on create. Create sequence extracted into a shared `leads/intake.py` core for Epic 10 to reuse.
- **Depends on:** Epics 1, 2, 3, 4, 5, 6.
- **Implementation notes:** Shared create core `app/leads/intake.py::create_lead(db, tenant_id, *, …, lead_source, status, owner_*, actor_*)` — Epic 10's public route calls it verbatim with `status=New`/`lead_source=public_form`/unowned/system-actor; it owns encrypt+fingerprint+age_band+insert+matcher+`lead.created`(+`lead.duplicate_detected`), does NOT commit (request transaction owns it), and writes NO audit record (the audit `EventType` enum has no lead member — don't add one). Product-line key-membership lives in the route, not the core, so Epic 10 must re-do its own key check; `app/tenancy/registry.py::tenant_by_schema` resolves the active schema's keys (agent route reads `SELECT current_schema()`). `CreateLeadRequest` carries only structural + ≥1-product-line validation — Epic 10 adds the public-route length caps/abuse controls.

## Epic 8 — Public tenant scoping seam — **COMPLETED** (25m)
- **Goal:** A `get_public_tenant_db(tenant_slug)` seam that resolves an unauthenticated request to a tenant by slug (whitelist-validated; unknown → 404) and runs under that tenant's existing role + schema, the sole sanctioned exception to "tenant context only from session."
- **Rough scope:** A new scoping dependency in the tenancy layer plus tests covering the whitelist guard and the role/schema set. No endpoint consumes it yet.
- **Open questions / decisions for stakeholders:** none — resolved at plan time.
- **Depends on:** none.
- **Implementation notes:** Epic 10 consumes `get_public_tenant_db` (in `app/tenancy/scoping.py`) via `async with` around the shared `create_lead` core — it is an `@asynccontextmanager`, not a `Depends` (the slug comes from the request body, not an injectable). The seam owns the request transaction (the core doesn't commit), resolves schema/role from the registry via `tenant_by_slug` (no `platform.tenants` read — the lookup IS the whitelist), and returns **404** on an unknown slug, so Epic 10 needn't pre-validate the slug.

## Epic 9 — In-app per-IP rate limiter — **COMPLETED** (19m)
- **Goal:** A unit-testable fixed-window per-IP rate limiter in the core app, keyed on the first `X-Forwarded-For` hop and configurable via settings, ready for the public intake route to use.
- **Rough scope:** A `leads/rate_limit.py`-style limiter plus the config knobs and unit tests. Not yet attached to any endpoint.
- **Open questions / decisions for stakeholders:** none — resolved at plan time. Default **5 requests / 60s** per IP (knobs `PUBLIC_INTAKE_RATE_LIMIT`=5, `PUBLIC_INTAKE_RATE_LIMIT_WINDOW_SECONDS`=60.0 in `config.py`). Limiter is a stateful `RateLimiter` with `is_allowed(client_ip) -> bool` (True=proceed; soft control flow, not a raise — so Epic 10 picks 429 vs silent drop); fixed-window via `floor(now/window)`, injected `now` defaulting to `time.monotonic` for sleep-free tests; first `limit` hits per window allowed, then blocked, count resets on rollover; no active eviction (in-memory, reset-on-restart per D7). IP keying via a pure `client_ip_from_forwarded_for(header) -> str | None` (first hop stripped, `None` when absent/empty) — Epic 10 owns the missing-header fallback.
- **Depends on:** none.
- **Implementation notes:** `app/leads/rate_limit.py` is framework-free (no endpoint wiring). Epic 10 consumes it directly — `client_ip_from_forwarded_for(header)` for the IP key and the module-level `public_intake_rate_limiter.is_allowed(client_ip)` for the gate (True=proceed) — and owns both the no-header fallback (helper returns `None`) and the over-limit response (429 vs silent drop), since `is_allowed` is a soft bool, not a raise.

## Epic 10 — Public intake endpoint — **COMPLETED** (1h 44m)
- **Goal:** The unauthenticated `POST /api/public/intake`: rate-limit and honeypot checks (honeypot filled → silent success-shaped drop), strict validation, tenant-by-slug scoping, lead creation (`New`, unowned, `public_form`), matcher, `lead.created` (plus `lead.duplicate_detected`), and a sanitized response that never leaks matched-lead data.
- **Rough scope:** The public router and its request schema, wiring the rate limiter + scoping seam + the shared intake core from Epic 7; tests for the abuse controls and the sanitized response.
- **Open questions / decisions for stakeholders:** none — resolved at plan time. Separate strict `PublicIntakeRequest` (the agent's `CreateLeadRequest` stays lenient). Length caps: slug 64 / names 100 / email 254 / phone 32 / zip 10 / street 200 / contact-method 20 / notes 1000 / honeypot 200. Formats (all → 422): light email regex `^[^@\s]+@[^@\s]+\.[^@\s]+$`, phone 10–15 digits after stripping, US zip `^\d{5}(-\d{4})?$`, `date_of_birth` strictly past & ≥ 1900-01-01 (no age floor), `preferred_contact_method` ∈ {email, phone, text}, 1–10 product lines (per-tenant key membership re-checked in the route). Honeypot field `website`: non-empty after trim → identical-to-success drop (nothing persisted/published). Over-limit → **429**; missing `X-Forwarded-For` → **fail open** (proceed). Sanitized success = **200 `{"ok": true}`** on both the real-create and drop paths — never the lead.
- **Depends on:** Epics 7, 8, 9.
- **Implementation notes:** Public-route contract for the UI/client epics: honeypot field is named `website` (Epic 18's Shopper form renders a hidden input with that exact name); sanitized success is **200 `{"ok": true}`** — never the masked lead — so Epic 17 types the response as `{ok}` and Epic 18 drives success off it. `PublicIntakeRequest` lives beside the agent `CreateLeadRequest` in `app/leads/schemas.py`; the route (`app/leads/public_router.py`) re-checks product-line key membership itself (the schema can't — needs tenant context). Test gotcha for Epics 18/22: the strict `phone` rule (10–15 digits after stripping non-digits) means `test_lead_intake.unique_contact`'s **hex**-suffixed phone folds to <10 digits → 422 — public tests need a **numeric**-suffix phone.

## Epic 11 — Lead reads (list + detail) — **COMPLETED** (22m)
- **Goal:** Authenticated, tenant-scoped, masked `GET /api/leads` (with an `unassigned` filter backing the queue) and `GET /api/leads/{id}` (404 on cross-tenant/missing).
- **Rough scope:** The two read endpoints reusing the masked read builder, plus tests for the filter and tenant isolation.
- **Open questions / decisions for stakeholders:** none — resolved at plan time. **Ordering:** newest first — `created_at` DESC, tie-broken by `id` (deterministic, stable across requests); the `unassigned` filter shares it. **Sizing:** a simple safety cap, **no pagination** — one `.limit(LEAD_LIST_LIMIT)` (named constant, **200**) over the newest-first query; real paging is a deliberate non-goal (small demo seed). **`unassigned` filter:** query param `unassigned: bool = False` — `true` restricts to the queue (`owner_user_id IS NULL` **and** `status == New`), default/`false` returns all leads (the two-tab UI sends only absent/`true`). **Auth/shape:** both reads ride `require_authenticated` + `get_tenant_db` (any authenticated tenant user reads the masked shape — Read-Only included), reuse `build_masked_lead` verbatim, and return `{"leads": […]}` (list) / `{"lead": …}` (detail); a missing/cross-tenant id → 404 `"lead not found"`, mirroring `pii_demo` get.
- **Depends on:** Epics 3, 5.
- **Implementation notes:** Read-side wire contract Epic 17 types and Epic 20's queue tab builds on: `{"leads": […]}` (list) / `{"lead": …}` (detail) of the masked shape, list is newest-first capped at 200, and `unassigned=true` is the queue filter `owner_user_id IS NULL AND status == 'New'`. Test seam for Epics 13–15/20–21: lead states the create endpoint can't make (unowned `New`, unowned `Rejected`, explicit `created_at`) are inserted via a schema-qualified superuser `INSERT` through the encryption path (`tests/test_lead_reads.py::insert_lead`); `login_agent_for_slug` logs in a *specific* tenant's seeded Agent where `login_as` only ever picks the first persona for a role.

## Epic 12 — Claim — **COMPLETED** (17m)
- **Goal:** `POST /api/leads/{id}/claim` moves a lead `New → Working`, sets the owner to the caller, and publishes `lead.assigned`.
- **Rough scope:** The claim action endpoint (capability-gated) using the state machine, plus tests for the transition and the event.
- **Open questions / decisions for stakeholders:** none expected.
- **Depends on:** Epics 2, 7.
- **Implementation notes:** Claim's `New → Working` + `lead.assigned` lives inline in `app/leads/router.py` (`claim_lead`, returns **200** — no resource created), reusing the row's `correlation_id` for the event. Epics 13/14 follow the same load→guard(`assert_transition`)→transition→publish→masked shape and map `InvalidLeadTransition` → **409** exactly as claim does (cross-epic contract).

## Epic 13 — Qualify / reject — **COMPLETED** (30m)
- **Goal:** `POST /api/leads/{id}/qualify` (`Working → Qualified`) and `POST /api/leads/{id}/reject` (`Working → Rejected`), each publishing its event with the right `reason_kind`.
- **Rough scope:** The two terminal-transition endpoints using the state machine, plus tests for the transitions and events.
- **Open questions / decisions for stakeholders:** none — resolved at plan time. Reject **captures an optional free-text reason** (≤1000 chars) stored in a new `rejection_reason text` column (migration `0010`), kept separate from intake `notes`; surfaced in the masked read like `notes` but **never** in the `lead.rejected` event (payload stays `entity_id` + `reason_kind`). A reason-less reject is allowed — `reason_kind = qualify_reject` always categorizes it. Both endpoints gate on `CREATE_EDIT_RECORDS` (**not** claim's `CLAIM_LEADS_MANAGE_TASKS`); `lead.qualified` payload is `entity_id` only. Both follow claim's load→`assert_transition`→transition→publish→masked inline pattern, mapping `InvalidLeadTransition` → 409.
- **Depends on:** Epics 2, 7.
- **Implementation notes:** New `rejection_reason` column (migration `0010`) + masked-read field are a cross-epic surface — Epic 17 mirrors the field, Epic 21 shows it on the detail page. `lead.rejected` payload is `entity_id` + `reason_kind`: this path emits `qualify_reject`; Epic 14's duplicate-reject reuses the event with `reason_kind = duplicate` and sets **no** `rejection_reason`. Reject **guards `current is Working` explicitly** (the machine legally allows `New → Rejected`) so the `New → Rejected` move stays Epic 14's — Epic 14 must not route it here.

## Epic 14 — Duplicate resolution — **COMPLETED** (33m)
- **Goal:** `POST /api/leads/{id}/resolve-duplicate` with `link` / `new` / `reject` — `link` records the linkage, `new` clears the flag, `reject` moves `New → Rejected` and publishes `lead.rejected` with `reason_kind = duplicate`.
- **Rough scope:** The resolution endpoint handling the three actions (reusing the state machine for reject), plus tests for each branch.
- **Open questions / decisions for stakeholders:** none — resolved at plan time. **Auth/shape:** auth + `CREATE_EDIT_RECORDS`, `get_tenant_db`, body `{ "action": "link" | "new" | "reject" }` (a strict `ResolveDuplicateRequest`; unknown action → 422), returns **200** `{"lead": …}` (no resource created); missing/cross-tenant id → 404. **Flag precondition (all three actions):** the lead must be flagged — `duplicate_of_lead_id IS NULL` → **409** (`"lead is not flagged as a duplicate"`); the endpoint exists only to resolve a flag. **`link`:** set `duplicate_resolution = "linked"`, keep `duplicate_of_lead_id`; no event. **`new`:** set `duplicate_resolution = "new"`, clear `duplicate_of_lead_id = null`; no event. **`reject`:** guard `current is New` explicitly (→ **409** otherwise, mirroring Epic 13's `Working` guard so the start-state partition holds: Epic 13 owns `Working → Rejected`, Epic 14 owns `New → Rejected`), then `assert_transition(New, Rejected)`, set `status = Rejected` **and** `duplicate_resolution = "rejected"` (keep `duplicate_of_lead_id`), publish `lead.rejected` with `{entity_id, reason_kind: "duplicate"}` reusing the row's `correlation_id`; sets **no** `rejection_reason`. A flagged `Working` lead is rejected via Epic 13's `/reject` instead. No migration / no masking change — the columns (0009) and masked fields already exist.
- **Depends on:** Epics 2, 7.
- **Implementation notes:** `app/leads/router.py::resolve_duplicate_lead` — wire contract for Epic 17 (`{"action": "link"|"new"|"reject"}` via strict `ResolveDuplicateRequest` `Literal`, 200 `{"lead": …}`) and Epic 21 (the detail page's three resolve controls). `reject` reuses `lead.rejected` with `reason_kind = "duplicate"`, sets no `rejection_reason`, and owns `New → Rejected` (Epic 13 owns `Working → Rejected`). Shared test seam Epics 16/22 build on: `tests/test_lead_reads.py::insert_lead` gained a `duplicate_of_lead_id` kwarg and `test_lead_intake.py::read_lead_row` now also selects `duplicate_resolution`.

## Epic 15 — Lead PII reveal — **COMPLETED** (22m)
- **Goal:** `POST /api/leads/{id}/reveal` reusing the `pii_demo` reveal shape — one field at a time, unknown fields refused (422), decrypt, await the `on_pii_revealed` audit seam, return the single value.
- **Rough scope:** The reveal endpoint (capability-gated) wired to the existing reveal + audit seam, plus tests including the audit emission.
- **Open questions / decisions for stakeholders:** none — resolved at plan time. **Revealable set** = all four encrypted columns (`email`, `phone`, `date_of_birth`, `street_address`) — every encrypted field is revealable. **No deny-list** (leads have no `mock_medicare_id`-equivalent) → only `REVEALABLE_FIELDS` plus one generic `422 "field is not revealable"` for any other name. **`entity_type = "lead"`** on the audit record + `pii.revealed` event. **Schema** = a lead-local `RevealLeadRequest` (`field: str`, plain `str` not enum) in `app/leads/schemas.py`, mirroring `pii_demo.RevealRequest` rather than importing it (keeps `leads` free of any `pii_demo` dependency, as every other lead schema does).
- **Depends on:** Epics 3, 7.
- **Implementation notes:** Reveal contract for **Epic 21**'s detail page (one click-to-reveal control per field): `POST /api/leads/{id}/reveal`, body `{"field": str}`, 200 `{"field", "value"}`; revealable set `email` / `phone` / `date_of_birth` / `street_address`, any other field → 422 `"field is not revealable"`, absent `street_address` → `value: null`. No deviations.

## Epic 16 — Minimal lead seed
- **Goal:** A small per-tenant lead seed (several unassigned `New` leads plus one duplicate-bait) so the queue is non-empty and the duplicate scenario lights up now; insert-if-absent so P1.8's full seed extends rather than collides.
- **Rough scope:** Add the lead rows to the existing idempotent seed, routing PII through the same normalize + blind-index path so the bait reliably flags.
- **Open questions / decisions for stakeholders:** the seed content — how many leads, and the bait lead's identity (which must match an intake the demo will submit).
- **Depends on:** Epics 3, 6.
- **Implementation notes:** _none yet_

## Epic 17 — Frontend API client + lead types
- **Goal:** Typed frontend client calls and Lead/ProductLine types mirroring the wire, so the UI epics have a ready data layer. Renders nothing.
- **Rough scope:** Add the lead calls to the API client and the snake-case mirror types. No components.
- **Open questions / decisions for stakeholders:** none expected — the types mirror the settled wire shapes.
- **Depends on:** Epics 7, 10, 11, 12, 13, 14, 15.
- **Implementation notes:** _none yet_

## Epic 18 — Public Shopper intake form [UI]
- **Goal:** Replace the `shopper-home-quote-card` seam with the public intake form — fields, honeypot, client-side validation, prefill buttons ("Typical lead", "Try a duplicate scenario"), and a success state — submitting to the public intake endpoint.
- **Rough scope:** The Shopper-surface form component and its wiring to the public endpoint + product-line list; component tests.
- **Open questions / decisions for stakeholders:** form layout, field grouping, the exact prefill payloads, validation messaging, and success-state copy (design at plan time, within the UI/UX Guide).
- **Depends on:** Epics 4, 10, 17.
- **Implementation notes:** _none yet_

## Epic 19 — Agent intake form [UI]
- **Goal:** An authenticated agent intake form at `/app/leads/new` that creates a lead via the agent endpoint and lands the agent on the new lead.
- **Rough scope:** The intake page/route and its form, reusing the API client; component tests.
- **Open questions / decisions for stakeholders:** form layout and field set presentation, and where the agent lands after submit (design at plan time).
- **Depends on:** Epics 7, 17.
- **Implementation notes:** _none yet_

## Epic 20 — Leads list + queue tab + claim [UI]
- **Goal:** The `/app/leads` page with an all-leads list and an unassigned-queue tab plus one-click Claim, and flipping the "Leads" nav item live.
- **Rough scope:** The leads list page (tabs + claim action) wired to the read + claim endpoints, and the nav flip; component tests.
- **Open questions / decisions for stakeholders:** list columns, the masked fields shown, tab and empty-state presentation (design at plan time).
- **Depends on:** Epics 11, 12, 17.
- **Implementation notes:** _none yet_

## Epic 21 — Lead detail + actions [UI]
- **Goal:** The `/app/leads/:id` detail page showing masked PII with audited click-to-reveal, and the qualify / reject / resolve-duplicate actions.
- **Rough scope:** The detail page and its action controls wired to the detail, transition, resolve, and reveal endpoints; component tests.
- **Open questions / decisions for stakeholders:** detail layout, action placement, the reveal interaction, and how the flagged-duplicate match is surfaced (design at plan time).
- **Depends on:** Epics 11, 13, 14, 15, 17.
- **Implementation notes:** _none yet_

## Epic 22 — Acceptance suite + green-gate pass
- **Goal:** A backend acceptance suite exercising the whole slice end-to-end on the real substrate — both intake routes, born states, the duplicate flag + events + resolution, claim + `lead.assigned`, qualify/reject + events, tenant A-vs-B isolation, blind-index match without decryption, and the abuse controls (rate limit, honeypot, validation, sanitized public response) — plus the frontend tests, with the full green gate passing.
- **Rough scope:** The integration acceptance test file and any remaining frontend test coverage; correctness-critical, kept whole (atomic integration coverage, not force-split despite size).
- **Open questions / decisions for stakeholders:** none expected — the assertions are enumerated in the TDD work breakdown.
- **Depends on:** Epics 1–21.
- **Implementation notes:** _none yet_
