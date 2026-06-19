# P1.7 — Lead Intake, Queue, Qualification & Duplicate Detection — Epic Plan

Source TDD: [./tdd-P1.7-lead-intake-queue-qualification-duplicate-detection.md](./tdd-P1.7-lead-intake-queue-qualification-duplicate-detection.md)

> **Review budget:** ~150 changed lines · ~8 non-generated files · one focused commit per epic. Tunable per project.

> High-level agile roadmap. Each epic's design specifics are confirmed with stakeholders at epic time (`4-plan-epic`) before any code is written.

This is an **L phase** (the TDD anticipated a layered split). The order is simplest-first: pure
vocabulary and unit-testable building blocks land first, then the first end-to-end intake slice,
then the remaining endpoints, then the frontend, then the acceptance gate. Backend is isolated
from its UI throughout; UI-bearing epics carry ` [UI]`.

## Epic 1 — Lead event vocabulary
- **Goal:** Add the five `lead.*` event types to the catalog and bind `enrichment.stub` to also receive `lead.created`, so the rest of the phase can publish lead events through the existing outbox.
- **Rough scope:** Event catalog (the `EventType` members + consumer binding) and its catalog test. No publishing yet.
- **Open questions / decisions for stakeholders:** none expected — the five events and their payload fields are spelled out in the TDD interfaces table.
- **Depends on:** none.
- **Implementation notes:** _none yet_

## Epic 2 — Lead status / source vocabulary + state machine
- **Goal:** A pure, unit-tested state machine that defines the lead's statuses and sources and rejects any transition outside the allowed moves (`New → Working → Qualified | Rejected`, plus the duplicate-reject from `New`).
- **Rough scope:** A `leads/state.py`-style module of string enums and a pure `assert_transition` guard, with unit tests. No persistence, no endpoints.
- **Open questions / decisions for stakeholders:** none expected — the machine is fully drawn in the TDD.
- **Depends on:** none.
- **Implementation notes:** _none yet_

## Epic 3 — Lead table migration + ORM model
- **Goal:** Create the per-tenant `leads` table (columns, blind-index indexes, grants) via a new migration and a schema-less `Lead` ORM modeled on `pii_demo`, leaving the system migratable and round-trippable.
- **Rough scope:** One new Alembic migration mirroring the `pii_demo` per-schema pattern, the ORM model, and a migration up/down round-trip test. No business logic on top.
- **Open questions / decisions for stakeholders:** none expected — the column set is fixed in the TDD data-model table.
- **Depends on:** none.
- **Implementation notes:** _none yet_

## Epic 4 — Product-line registry config
- **Goal:** Expose a per-tenant list of product lines (key + label) as static registry config, surfaced unauthenticated through the existing `GET /api/tenants`, so both intake forms can offer the choices and the server can validate submitted keys.
- **Rough scope:** Add a keyed `product_lines` field to the tenant registry config, fold it into the tenants response, and cover it with catalog/registry tests.
- **Open questions / decisions for stakeholders:** the actual product-line keys and labels each demo tenant offers (the registry content) — not enumerated in the TDD.
- **Depends on:** none.
- **Implementation notes:** _none yet_

## Epic 5 — Masked lead read builder
- **Goal:** A reusable builder that turns a `Lead` row into the masked shape returned on every read, reusing the PII service and the existing maskers.
- **Rough scope:** A `leads/masking.py`-style helper plus unit tests; no endpoint wiring yet.
- **Open questions / decisions for stakeholders:** which fields appear (and how masked) in the list shape vs the detail shape, if they differ.
- **Depends on:** Epic 3.
- **Implementation notes:** _none yet_

## Epic 6 — Duplicate matcher
- **Goal:** A deterministic matcher that, given a new lead's normalized email/phone, finds a prior matching lead in the tenant via the blind index — without decrypting anything.
- **Rough scope:** A `leads/matching.py`-style module (normalize → blind index → equality query over tenant leads) with a unit test and a DB-backed test proving the match works without decryption.
- **Open questions / decisions for stakeholders:** match semantics — does an email match *or* a phone match flag a duplicate, or must both match? (And which match wins when both exist.)
- **Depends on:** Epic 3.
- **Implementation notes:** _none yet_

## Epic 7 — Agent intake (walking skeleton)
- **Goal:** The first end-to-end intake slice: an authenticated `POST /api/leads` that creates a lead (born `Working`, owned by the entering agent, `agent_entered`), encrypts the PII fields, runs the matcher, publishes `lead.created` (plus `lead.duplicate_detected` on a match), and returns the masked lead.
- **Rough scope:** The agent lead router/create handler, request schema, and the create-path wiring of state + encryption + matcher + outbox; intake-focused tests. Reuses the building blocks from Epics 1–6.
- **Open questions / decisions for stakeholders:** the exact required-vs-optional field set and any agent-route validation beyond what the public route hardens.
- **Depends on:** Epics 1, 2, 3, 4, 5, 6.
- **Implementation notes:** _none yet_

## Epic 8 — Public tenant scoping seam
- **Goal:** A `get_public_tenant_db(tenant_slug)` seam that resolves an unauthenticated request to a tenant by slug (whitelist-validated; unknown → 404) and runs under that tenant's existing role + schema, the sole sanctioned exception to "tenant context only from session."
- **Rough scope:** A new scoping dependency in the tenancy layer plus tests covering the whitelist guard and the role/schema set. No endpoint consumes it yet.
- **Open questions / decisions for stakeholders:** none expected — the seam and its carve-out are decided in the TDD (D3).
- **Depends on:** none.
- **Implementation notes:** _none yet_

## Epic 9 — In-app per-IP rate limiter
- **Goal:** A unit-testable fixed-window per-IP rate limiter in the core app, keyed on the first `X-Forwarded-For` hop and configurable via settings, ready for the public intake route to use.
- **Rough scope:** A `leads/rate_limit.py`-style limiter plus the config knobs and unit tests. Not yet attached to any endpoint.
- **Open questions / decisions for stakeholders:** the default limit and window values (the TDD names the knobs but not the numbers).
- **Depends on:** none.
- **Implementation notes:** _none yet_

## Epic 10 — Public intake endpoint
- **Goal:** The unauthenticated `POST /api/public/intake`: rate-limit and honeypot checks (honeypot filled → silent success-shaped drop), strict validation, tenant-by-slug scoping, lead creation (`New`, unowned, `public_form`), matcher, `lead.created` (plus `lead.duplicate_detected`), and a sanitized response that never leaks matched-lead data.
- **Rough scope:** The public router and its request schema, wiring the rate limiter + scoping seam + the shared intake core from Epic 7; tests for the abuse controls and the sanitized response.
- **Open questions / decisions for stakeholders:** the exact server-side validation rules and length limits for the public route.
- **Depends on:** Epics 7, 8, 9.
- **Implementation notes:** _none yet_

## Epic 11 — Lead reads (list + detail)
- **Goal:** Authenticated, tenant-scoped, masked `GET /api/leads` (with an `unassigned` filter backing the queue) and `GET /api/leads/{id}` (404 on cross-tenant/missing).
- **Rough scope:** The two read endpoints reusing the masked read builder, plus tests for the filter and tenant isolation.
- **Open questions / decisions for stakeholders:** default list ordering, and whether the demo needs pagination or a simple capped list.
- **Depends on:** Epics 3, 5.
- **Implementation notes:** _none yet_

## Epic 12 — Claim
- **Goal:** `POST /api/leads/{id}/claim` moves a lead `New → Working`, sets the owner to the caller, and publishes `lead.assigned`.
- **Rough scope:** The claim action endpoint (capability-gated) using the state machine, plus tests for the transition and the event.
- **Open questions / decisions for stakeholders:** none expected.
- **Depends on:** Epics 2, 7.
- **Implementation notes:** _none yet_

## Epic 13 — Qualify / reject
- **Goal:** `POST /api/leads/{id}/qualify` (`Working → Qualified`) and `POST /api/leads/{id}/reject` (`Working → Rejected`), each publishing its event with the right `reason_kind`.
- **Rough scope:** The two terminal-transition endpoints using the state machine, plus tests for the transitions and events.
- **Open questions / decisions for stakeholders:** whether reject captures a human reason/notes beyond the event's `reason_kind`.
- **Depends on:** Epics 2, 7.
- **Implementation notes:** _none yet_

## Epic 14 — Duplicate resolution
- **Goal:** `POST /api/leads/{id}/resolve-duplicate` with `link` / `new` / `reject` — `link` records the linkage, `new` clears the flag, `reject` moves `New → Rejected` and publishes `lead.rejected` with `reason_kind = duplicate`.
- **Rough scope:** The resolution endpoint handling the three actions (reusing the state machine for reject), plus tests for each branch.
- **Open questions / decisions for stakeholders:** none expected — the three actions and their effects are spelled out in the TDD.
- **Depends on:** Epics 2, 7.
- **Implementation notes:** _none yet_

## Epic 15 — Lead PII reveal
- **Goal:** `POST /api/leads/{id}/reveal` reusing the `pii_demo` reveal shape — one field at a time, unknown fields refused (422), decrypt, await the `on_pii_revealed` audit seam, return the single value.
- **Rough scope:** The reveal endpoint (capability-gated) wired to the existing reveal + audit seam, plus tests including the audit emission.
- **Open questions / decisions for stakeholders:** none expected — the reveal contract is the proven `pii_demo` shape.
- **Depends on:** Epics 3, 7.
- **Implementation notes:** _none yet_

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
