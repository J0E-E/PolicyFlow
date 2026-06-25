# Lead Conversion (P2.1) — Epic Plan

Source TDD: [./tdd-lead-conversion.md](./tdd-lead-conversion.md)

> **Review budget:** ~300 changed lines · ~16 non-generated files · one focused commit per epic. Tunable per project.

> **Build strategy:** Tracer bullet — copied from the TDD; `4-plan-epic` orders each epic's phases by it (`0-conventions.md` → *Build strategies*). Epics 1–3 are the prerequisite substrate; **Epics 4+5 are the thinnest customer-visible end-to-end thread** (a real conversion, demoable); everything after layers on it.

> High-level agile roadmap. Each epic's design specifics are confirmed with stakeholders at epic time (`4-plan-epic`) before any code is written.

## Epic 1 — Migration 0015: the converted-world schema
- **Goal:** Add the per-tenant tables a conversion writes into — `households`, `contacts`, `opportunities`, `tasks` — plus the two converted-ref columns on `leads`, with correct grants. Down/up round-trips clean on the real Postgres substrate. No behavior yet; this is the ground every later epic stands on.
- **Rough scope:** one additive Alembic migration in the 0009 grant shape (tenant CRUD, `platform_reader` SELECT, `demo_purge` SELECT+DELETE) + ALTER `leads` ADD `converted_contact_id` / `converted_opportunity_ids`; a substrate down/up test.
- **Open questions / decisions for stakeholders:** confirm `env.py` `include_object` excludes the four schema-less tables from `alembic check` so the drift gate stays clean (the migration owns indexes).
- **Depends on:** none.
- **Implementation notes:** _none yet_

## Epic 2 — ORM twins, terminal `Converted` status, masked read
- **Goal:** Stand up the four schema-less ORM models over the new tables, add the terminal `Converted` lead status (`Qualified → Converted`, no outgoing edges so claim/qualify/reject all 409), and surface the two converted-ref fields on the masked lead read; mirror the new status in the frontend `LeadStatus` union. No conversion action yet — this is the model + read vocabulary the action will use.
- **Rough scope:** four ORM twins (schema-less, excluded from `alembic check`); `LeadStatus.CONVERTED` + the `assert_transition` edge; `Lead` model + `build_masked_lead` gain the two converted fields; FE `LeadStatus` union adds `"Converted"`.
- **Open questions / decisions for stakeholders:** confirm `converted_opportunity_ids` (`uuid[]`) serializes as a JSON array of strings on the masked read.
- **Depends on:** Epic 1.
- **Implementation notes:** _none yet_

## Epic 3 — Event vocabulary for conversion
- **Goal:** Add the four conversion event types to the catalog so the conversion action can emit them; consumer bindings stay as-is (`sync.logger`'s `#` auto-reacts, `enrichment.stub` does not), keeping the lead timeline honest.
- **Rough scope:** four new `EventType` members (`lead.converted`, `contact.created`, `household.created`, `opportunity.created`); extend the `test_event_catalog` expectation. `CONSUMER_BINDINGS` unchanged.
- **Open questions / decisions for stakeholders:** none expected.
- **Depends on:** none.
- **Implementation notes:** _none yet_

## Epic 4 — Atomic convert action (new-household path)
- **Goal:** The core customer-value transaction. `POST /api/leads/{id}/convert` turns a held Qualified lead into a new Household + Contact + one Opportunity per confirmed product line + a note-Task (when the lead has notes), freezes the lead `Converted`, and emits the four event types — all in one request transaction (atomic, no commit), every created entity carrying the lead's `correlation_id` + `demo_session_id`.
- **Rough scope:** a new conversion service mirroring the `create_lead` outbox idiom on the request session; the `POST /convert` endpoint with guards in order (capability → session-guard refusing seed → holder → `Qualified` transition); `ConvertLeadRequest` (new-household mode only here, ≥1 valid tenant product-line key); returns the masked frozen lead.
- **Open questions / decisions for stakeholders:** none expected (the link branch and the ≥1-or-blocked product-line UI land in later epics).
- **Depends on:** Epics 1, 2, 3.
- **Implementation notes:** _none yet_

## Epic 5 — Convert affordance → frozen lead [UI]
- **Goal:** Make a real conversion demoable end-to-end. A Convert affordance on a Qualified, held lead leads to a minimal confirm, calls `convertLead`, and lands back on the frozen lead detail showing the `Converted` stamp with mutating actions hidden. *(The tracer bullet is now complete.)*
- **Rough scope:** Convert affordance gated on `status==="Qualified"` + holder + `create_edit_records` + `!is_seed`; a minimal confirm step; `convertLead` api client + `ConvertLeadRequest` wire type; frozen-lead detail reflects `Converted`; every rendered element gets a unique `id`.
- **Open questions / decisions for stakeholders:** none expected (the richer review screen replaces the minimal confirm next).
- **Depends on:** Epic 4.
- **Implementation notes:** _none yet_

## Epic 6 — Review-and-confirm screen [UI]
- **Goal:** Replace the minimal confirm with the real `/app/leads/:id/convert` review-and-confirm page: read-only mapped contact details, product-line confirm/choose (the lead's lines pre-checked; when the lead has none the agent picks ≥1; commit blocked at zero), new-household default.
- **Rough scope:** the dedicated convert route; reuse the masked lead read for display; product-line confirm/choose UI with the ≥1-or-blocked rule; commit → `POST /convert` → frozen lead.
- **Open questions / decisions for stakeholders:** none expected.
- **Depends on:** Epic 5.
- **Implementation notes:** _none yet_

## Epic 7 — "Converted to" summary panel [UI]
- **Goal:** Prove the created customer is visible without building detail pages: a "Converted to" panel on a `Converted` lead showing the contact name, household name, and opportunities by product-line label + stage.
- **Rough scope:** `GET /api/leads/{id}/conversion` (non-PII display fields; 409/404 when the lead isn't converted); the panel on the frozen lead detail.
- **Open questions / decisions for stakeholders:** none expected.
- **Depends on:** Epic 5.
- **Implementation notes:** _none yet_

## Epic 8 — Household link path [UI]
- **Goal:** Let the agent link the new Contact into an existing Household instead of creating one: a session-scoped household search backs a create-new-vs-link picker, and the convert action gains its link branch (reuse the chosen household, no `household.created` event).
- **Rough scope:** `GET /api/households?q=` (tenant-scoped, `visible_to_session`, members = the household's contacts' plaintext names); picker UI (create-new default vs link); `ConvertLeadRequest` link mode; the `convert_lead` link branch.
- **Open questions / decisions for stakeholders:** household-search match limit + ordering — reuse the lead-list cap idiom; settle the exact cap at epic time.
- **Depends on:** Epics 4, 6.
- **Implementation notes:** _none yet_

## Epic 9 — Duplicate pre-select [UI]
- **Goal:** For a lead flagged as a duplicate of a *converted* prior, pre-select that prior's Household in the picker (agent can override); graceful "new household" default when the prior isn't converted.
- **Rough scope:** `GET /api/leads/{id}/conversion-prefill` (resolve `duplicate_of_lead_id → prior converted_contact_id → household_id` server-side; null otherwise); the screen pre-selects it with override allowed.
- **Open questions / decisions for stakeholders:** none expected.
- **Depends on:** Epic 8.
- **Implementation notes:** _none yet_

## Epic 10 — Isolation + frozen-read hardening
- **Goal:** Close the cross-cutting isolation invariant for the new entities and finish freezing a `Converted` lead: purge sweeps the four new tables per session, `resolve-duplicate` refuses a `Converted` lead, and the household search is confirmed session-scoped (a second session/tenant sees and purges none of it).
- **Rough scope:** `purge.py` + `PurgeCounts` extend to `opportunities`/`tasks`/`contacts`/`households`; a `resolve-duplicate` frozen guard (409); confirm `visible_to_session` on the household search.
- **Open questions / decisions for stakeholders:** none expected.
- **Depends on:** Epics 4, 8.
- **Implementation notes:** _none yet_

## Epic 11 — Acceptance suite
- **Goal:** Prove the whole phase end-to-end on the real substrate: happy-path conversion (all entities + freeze + four event types incl. `opportunity.created` ×N, shared `correlation_id`), duplicate pre-select + new-Contact, forced-failure rollback (monkeypatch a mid-convert step), cross-session isolation + purge; plus the FE acceptance block for the convert flow + frozen panel.
- **Rough scope:** the named `test_lead_conversion_acceptance.py`; a frontend acceptance block for the convert flow + frozen panel.
- **Open questions / decisions for stakeholders:** none expected.
- **Depends on:** Epics 1–10.
- **Implementation notes:** _none yet_
