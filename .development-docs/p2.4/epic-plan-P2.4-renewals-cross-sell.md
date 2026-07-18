# Renewals & Cross-sell — Epic Plan

Source TDD: [./tdd-P2.4-renewals-cross-sell.md](./tdd-P2.4-renewals-cross-sell.md)

> **Review budget:** ~300 changed lines · ~16 non-generated files · one focused commit per epic. Tunable per project.

> **Build strategy:** Tracer bullet — copied from the TDD; shapes the epic breakdown only, never phase order inside an epic (`0-conventions.md` → *Build strategies*).

> High-level agile roadmap. Each epic's design specifics are confirmed with stakeholders at epic time (`4-plan-epic`) before any code is written.

> **Ordering note (deliberate deviation from TDD §9):** the TDD lists the seed as WBS item 12, but the AEP tracer (WBS item 5) demos *against a seeded MA policy* — a forward dependency, since there are no baseline money-path entities seeded today. Seed is data, not behavior, and depends only on the migration, so it moves **before** the tracer (Epic 5) here. Every vertical slice then has data to demo against. QA-checklist epics are unaffected (their diff is a document, not a live run).

## Section 1 — Renewal generation & overlay

## Epic 1 — Renewal rules + pure predicates — **COMPLETED** (15m · 10.1M tok · 636k tok/min)
- **Goal:** A `renewal_rule` attribute on every product line (aep / anniversary / none, classified per ADR 0003) plus a pure, clock-free/DB-free rules module (`in_aep_window`, `anniversary_within`, `renewal_deadline`, `renewal_cycle_key`), fully unit-tested.
- **Rough scope:** Product-line registry + a new `app/renewals/rules.py` + its unit tests. No endpoints, no DB.
- **Open questions / decisions for stakeholders:** none expected — classification and predicate semantics settled in the TDD (D1/ADR 0003) and confirmable by the unit tests (MA=aep, ancillary/health=anniversary-60d, life=never).
- **Depends on:** none.
- **Implementation notes:**
  - Contract for Epic 4: `renewal_deadline`/`renewal_cycle_key` raise `ValueError` on a non-renewing rule (`"none"`) — callers must pass only `"aep"`/`"anniversary"`.
  - Anniversary semantics: a Feb-29 issue date observes its anniversary on **Feb 28** in a non-leap year (matters for Epic 4/8 window filtering).

## Epic 2 — Migration 0020 (renewal / cross-sell schema) — **COMPLETED** (16m · 11.5M tok · 702k tok/min)
- **Goal:** Additive migration: `opportunities.source_policy_id` + `renewal_cycle` (both nullable), `source_lead_id` relaxed to nullable, `origin` gains `'renewal'` / `'cross_sell'`, and the partial unique index guarding one renewal opportunity per policy per cycle per session (ADR 0001/0004). Policy `status` allows a new `'Renewal Due'` value (plain text, no schema change).
- **Rough scope:** One forward-only Alembic migration + model field additions. No behavior yet — mainline stays working on additive nullable columns.
- **Open questions / decisions for stakeholders:** none expected — schema settled in TDD §5.2 (D3/D4).
- **Depends on:** none.
- **Implementation notes:**
  - Contract for Epic 4/6/8: the idempotency backstop is the partial unique index `ux_opportunities_one_renewal_per_policy_cycle` on `(source_policy_id, renewal_cycle, demo_session_id) WHERE origin = 'renewal'` — it binds only when a row's `origin = 'renewal'`, so `generate_renewals` must set that origin for the DB guard to fire. `source_lead_id` is now nullable (renewal/cross-sell opportunities leave it null; conversion still sets it).

## Epic 3 — Renewal event vocabulary — **COMPLETED** (11m · 11.1M tok · 975k tok/min)
- **Goal:** Add `EventType.POLICY_RENEWAL_DUE = "policy.renewal_due"` to the catalog with **no** new consumer binding (rides `sync.logger` `#`), and a catalog test asserting the new member plus unchanged bindings.
- **Rough scope:** The events catalog + its test. No emitters yet.
- **Open questions / decisions for stakeholders:** none — resolved at plan time.
- **Depends on:** none.
- **Implementation notes:**
  - Contract for Epic 4: `POLICY_RENEWAL_DUE` carries **no dedicated consumer binding** — it rides the `#`-binding `sync.logger` alone (D6), so the emitter needs **no `CONSUMER_BINDINGS` / broker-topology change**. Emitters set a **new** `correlation_id` and `causation_id=None`.

## Epic 4 — Renewal generation core — **COMPLETED** (28m)
- **Goal:** The `generate_renewals` service — select session-visible active policies on a given rule's lines, filter by the rule's window, skip on the idempotency key (any stage, ADR 0001), else create the Renewal Opportunity + renewal-review Task + both events (new correlation), and write the real `Renewal Due` status for session-owned policies. Returns `{generated, skipped}`. Unit-tested against a seeded pytest fixture.
- **Rough scope:** New `app/renewals/service.py` + unit tests over a test fixture (not the app seed). No HTTP surface yet.
- **Open questions / decisions for stakeholders:** none — resolved at plan time.
- **Depends on:** Epic 1 (rules/predicates), Epic 2 (schema), Epic 3 (event type).
- **Implementation notes:**
  - **Contract for Epic 6/8:** `generate_renewals(db, tenant_config, *, tenant_id, rule, demo_session_id, today=None) -> {generated, skipped}` — the sweep router passes `identity.tenant_id` (a distinct param: the outbox envelope needs it and `TenantConfig` carries no id) and does **not** commit (the service runs on the caller's scoped write session). Each renewal emits its events under a **system actor** (`actor_user_id/role=None`), since the sweep is automation, not the triggering admin.
  - Added a public `next_anniversary(issued_at, today) -> date` to Epic 1's `app/renewals/rules.py` (`anniversary_within` refactored to call it) so the Feb-29→Feb-28 leap rule stays in one place — a touch outside this epic's "new service.py" scope, needed for the anniversary deadline + cycle year.
  - _(review, deferred nits)_ (a) the per-policy create body is inlined rather than a `_create_renewal` helper; (b) `_emit` duplicates `leads/conversion.py`'s private `_emit` (differs only in system actor) — fold into a shared `events.outbox` emit if a third caller ever appears.

## Epic 5 — Seed baseline money-path chains — **COMPLETED** (51m · 44.9M tok · 866k tok/min)
- **Goal:** Idempotent seed of whole baseline chains (household → contact → opportunity → application → policy) in **both** tenants, giving the sweeps and cross-sell real targets in a fresh session: a Sunshine MA policy (AEP), a back-dated anniversary-line policy inside the 60-day window, a none-line policy, and partially- and fully-covered cross-sell households (plus baseline note-tasks for the queue). Seeded rows stay byte-identical across re-seeds (except the documented back-dating drift).
- **Rough scope:** `core/app/seed.py` — new baseline entity chains, both tenants; idempotent and minimal.
- **Open questions / decisions for stakeholders:** none — resolved at plan time.
- **Depends on:** Epic 2 (migration present).
- **Implementation notes:**
  - **Sweep / cross-sell targets:** _Sunshine_ Ramirez household — `medicare_advantage` (recent → the **sole** Sunshine MA policy, so Epic 6 stays `{1,0}`/`{0,1}`), `medicare_supplement` (back-dated so its anniversary is ~30d out → inside the 60-day window → Epic 8 renews), `final_expense` (none → no renewal); `dental_vision_hearing` left uncovered → the **partial** cross-sell household (Epic 13 prompts). _Florida_ Familia household — all four lines covered → **fully-covered** (Epic 13 prompt suppressed), `health`/`critical_illness` issued **out-of-window** + life lines → Epic 8 generates nothing.
  - **Why full-coverage is Florida's:** a Sunshine full household needs a 2nd `medicare_advantage` policy and breaks Epic 6's `{1,0}`; Florida has no MA line so it can't add an AEP target. `agent.one` owns every renewal-target policy in both tenants → each generated renewal-review Task has a deterministic assignee (Epic 10/11); Sunshine note-tasks split `agent.one`/`agent.two` to exercise the role-scoped queue.
  - **Chain root / no-FK:** money-path tables carry **no DB foreign keys** (app-enforced) — so `application.selected_quote_id` (NOT NULL) takes a synthetic uuid (**no** quotes seeded), and each contact chains to a minimal `Converted` backing lead (`contact.source_lead_id` NOT NULL). Epic 16 acceptance asserts byte-identical re-seed over these chains (except the documented anniversary back-dating drift, TDD §7).
  - **Cross-epic gotcha for Epic 6/8:** baseline money-path policies are `demo_session_id IS NULL`, so they are visible to **every** session's `generate_renewals` sweep — any DB test that runs a sweep against the shared container must first clear `policies`/`opportunities` (done in `test_renewal_generation._scoped_session`). `test_seed_leads`'s historical-lead counts now filter `status <> 'Converted'` to exclude the backing leads.
  - **Deferred nit (Epic 16):** `seed_baseline_money_paths` sets `selected_quote_id = uuid.uuid4()` and `decided_at = datetime.now(...)` per chain — harmless under skip-based re-seed idempotency (rows never regenerate) and outside the re-seed fingerprint (id / policy_number / issued_at), but two **fresh-DB** seeds differ there. If Epic 16 ever widens its byte-identical assertion past same-DB re-seed, derive both deterministically.

## Epic 6 — AEP sweep tracer [UI] — **COMPLETED** (1h 0m · 64.1M tok · 1.1M tok/min)
- **Goal:** *The thinnest customer-visible slice.* `POST /api/renewals/aep-sweep` (Platform-Admin, scoped to the caller's demo session + `last_tenant_slug`) runs `generate_renewals` for the AEP rule, bypassing the calendar (ADR 0004); a Platform-Admin workspace button fires it and shows `{generated, skipped}`; the seeded MA policy reads *Renewal Due* via the derive-at-read overlay on **one** read surface; a re-run reports `{0, 1}` (idempotent).
- **Rough scope:** New `app/renewals/router.py` (AEP endpoint), a sweep button beside `WorkspaceResetControl`, and the overlay flag on one policy-read surface. Reuses the P1.8 scoped-write-session and workspace-control patterns.
- **Open questions / decisions for stakeholders:** none — resolved at plan time.
- **Depends on:** Epic 4 (generation core), Epic 5 (seeded MA policy).
- **Implementation notes:**
  - **Contract for Epic 7/8 (overlay seam):** shipped `serialize_policy(policy, *, overlay_renewal_due=False)` + the read surface `GET /api/opportunities/{id}/policy`. Overlay predicate (ADR 0005): baseline policy (`demo_session_id IS NULL`) ∧ the caller's session holds an `origin='renewal'` opportunity with `source_policy_id = policy.id` — the `origin='renewal'` qualifier is load-bearing (cross-sell, Epic 13, also sets `source_policy_id`). The predicate is **inlined** in `opportunities/router.py::get_opportunity_policy`; `serialize_policy` is currently applied on this surface + submit only. Epic 7 threads `overlay_renewal_due` through EVERY policy-status render and may lift the predicate into a shared helper. `get_opportunity_policy` passes `medicare_id_masked=None`; Epic 7/11 add masking if needed.
  - **Contract for Epic 8 (sweep endpoint):** `POST /api/renewals/aep-sweep` — `require_platform_admin`, reads `tenant_id` from `platform.tenants` on the login role **before** `get_public_tenant_db(last_tenant_slug)` scoping (scoped role can't see `platform`), then scoped write + block-exit commit (core never commits). Scope comes from the demo session, not the body (no session → 409, no `last_tenant_slug` → 409). Epic 8's anniversary-sweep mirrors it with `rule="anniversary"`.
  - **Gotcha for Epic 8 (committing renewals in shared-container tests):** `generate_renewals` writes renewal opportunities with `source_lead_id = NULL`; committed through a sweep endpoint they persist in the shared test container and **break 0020's migration round-trip** (downgrade restores `source_lead_id NOT NULL`). Epic 6's committing test files (`test_aep_sweep_endpoint`, `test_opportunity_policy_read`) add a `cleanup_committed_renewals` teardown deleting `origin='renewal'` opps + `renewal_review` tasks across both schemas — Epic 8's tests must do the same. (Pure service tests in `test_renewal_generation` avoid it via rolled-back `_scoped_session`.)
  - **Observability (ADR 0006):** the Platform-Admin sweep writes **no** audit record; the outbox trail (`opportunity.created` + `policy.renewal_due` per renewal) is the record. The same answer stands for the Epic 10 task-complete and Epic 13 cross-sell observability questions.
  - **UI convention:** `StampTag` has **no** `attention` status — *Renewal Due* maps to `warning` (already styled). `PolicySummary` gained a `statusHue` (`Renewal Due`→`warning`, else `success`); badge text comes straight from `policy.status`. Epic 11/14 *Renewal Due* badges reuse this.
  - _(review, deferred nits — carried to Epic 8)_
    - `cleanup_committed_renewals` teardown is duplicated verbatim in `test_aep_sweep_endpoint.py` + `test_opportunity_policy_read.py`; Epic 8's anniversary-sweep commits renewals too and needs the same cleanup — promote the fixture to `conftest.py` when the third copy appears.
    - that teardown clears committed `origin='renewal'` opps + `renewal_review` tasks but **not** the outbox event rows (`opportunity.created` + `policy.renewal_due`) the sweep also commits — harmless today, but clear those alongside in Epic 8 so any future event-count test doesn't see a polluted shared container.
    - `core/app/policies/read.py` — the overlay `status = "Renewal Due" if … else …` line runs ~95 chars; backend lint (black) isn't in the configured gate but would rewrap it.

## Epic 7 — Overlay hardening — **COMPLETED** (26m · 19.5M tok · 747k tok/min)
- **Goal:** Route **every** policy-status render through the overlay-aware `serialize_policy` so no surface shows stale `Active`, and take the real guarded `Active → Renewal Due` write for session-created policies (ADR 0005). Baseline rows stay untouched (overlay only).
- **Rough scope:** `serialize_policy` overlay flag threaded through all policy-status surfaces + the guarded status-write path. Backend-focused (touches the surfaces from Epic 6 and any others).
- **Open questions / decisions for stakeholders:** none — resolved at plan time.
- **Depends on:** Epic 6 (thin overlay established).
- **Implementation notes:**
  - **Plan/scope deviation (auto, vetted):** Epic 7 shipped **no product-code change** — Epics 4 (guarded `Active → Renewal Due` write, `renewals/service.py`) and 6 (the only current overlay render surface, `get_opportunity_policy`) already met both goal clauses, so the in-charter work was a **verify + lock** pass (audit the two `serialize_policy` surfaces; add the precision test the suite missed). A speculative single-caller helper extraction was adversarially refuted (premature; wrong per-policy shape for Epic 13's list consumer) and dropped.
  - **Contract for Epic 13/14 (overlay):** lift the inlined `get_opportunity_policy` predicate into a shared helper shaped for **set/batch** lookup over the household's `source_policy_id`s (avoid N+1 across the policy list) — don't copy the per-policy inline; and keep the `origin='renewal'` qualifier load-bearing — a `cross_sell` opp also sets `source_policy_id`, so the overlay must keep ignoring non-renewal origins (now test-locked).
  - **Gotcha for Epic 13 (committing cross-sell in shared-container tests):** an `origin='cross_sell'` opportunity carries `source_lead_id = NULL` too, so committing one into the shared container **breaks 0020's migration round-trip** (downgrade restores `source_lead_id NOT NULL`). Epic 7 added a `cleanup_committed_cross_sell` teardown in `test_opportunity_policy_read.py` (deletes `origin='cross_sell'` opps across both schemas; no cross-sell tasks to clear) — Epic 13's committing cross-sell tests must mirror it.

## Epic 8 — Anniversary sweep [UI]
- **Goal:** `POST /api/renewals/anniversary-sweep` over anniversary-line policies inside the 60-day window + a Platform-Admin button, reusing the generation core; the seeded back-dated policy renews, and `final_expense`/life policies generate nothing (test-verified).
- **Rough scope:** The anniversary endpoint + a second workspace button. Reuses Epic 4's core and Epic 6's button pattern.
- **Open questions / decisions for stakeholders:** none expected.
- **Depends on:** Epic 4 (core), Epic 5 (back-dated anniversary policy).
- **Implementation notes:** _none yet_

## Epic 9 — QA checklist: Renewal generation & overlay
- **Goal:** Write the section's QA checklist — exhaustive user-facing test scenarios for both sweeps, idempotent re-runs, the *Renewal Due* overlay on every policy surface, seeded-rows-untouched, and the none-line/life no-renewal cases. Expected use plus edge cases (no demo session → 409, wrong tenant, re-run skip counts, expired session), `- [ ]` steps with expected results, no code refs.
- **Rough scope:** `qa-checklist-P2.4-renewals-cross-sell-renewal-generation-and-overlay.md`.
- **Open questions / decisions for stakeholders:** none expected.
- **Depends on:** Epics 1–8.
- **Implementation notes:** _none yet_

## Section 2 — Agent task queue

## Epic 10 — Task queue backend
- **Goal:** `GET /api/tasks` (Agent → own non-completed; Tenant Admin & Read-Only → all, `?assignee=` filter; session-scoped; ordered soonest-due/overdue-first, nulls last; each row carries `is_overdue`) and `POST /api/tasks/{id}/complete` (capability + assignee/Tenant-Admin guarded, session write-isolation, sets `status='completed'` via `updated_at`). Two-state open/completed (D7).
- **Rough scope:** New `app/tasks/router.py` (no tasks router exists today) + reads over the existing Task entity. Surfaces renewal-review Tasks and legacy note-tasks alike.
- **Open questions / decisions for stakeholders:** **observability** — should task completion write an audit record (P1.4)? Confirm the role-scoping read matches the P2.2/P2.3 precedent.
- **Depends on:** Epic 5 (seeded note-tasks + renewal tasks to list).
- **Implementation notes:** _none yet_

## Epic 11 — Task queue page [UI]
- **Goal:** A Task Queue page + nav entry: the list with an overdue badge, a link to the related record, and a one-click Complete that clears the task.
- **Rough scope:** New page + route + nav entry + the data layer to `GET /api/tasks` / complete. All elements carry unique descriptive `id`s.
- **Open questions / decisions for stakeholders:** UI/UX Guide components for the list rows, overdue badge, and Complete action — confirmed at plan time (frontend-design craft within the Guide).
- **Depends on:** Epic 10.
- **Implementation notes:** _none yet_

## Epic 12 — QA checklist: Agent task queue
- **Goal:** Write the section's QA checklist — viewing (own vs all by role), the overdue flag, the record link, completing a task, and edge cases (empty queue, Read-Only cannot complete, completing another agent's task as Agent → 403, expired session). `- [ ]` steps with expected results, no code refs.
- **Rough scope:** `qa-checklist-P2.4-renewals-cross-sell-agent-task-queue.md`.
- **Open questions / decisions for stakeholders:** none expected.
- **Depends on:** Epics 10–11.
- **Implementation notes:** _none yet_

## Section 3 — Household & cross-sell

## Epic 13 — Household detail backend + cross-sell accept
- **Goal:** `GET /api/households/{id}` returning `{household, contacts[], active overlay-aware policies[], cross_sell[]}` where cross-sell is a **live** coverage check — one suggestion per uncovered tenant product line, suppressed when all covered or no active policy (ADR 0002) — and `POST /api/households/{id}/cross-sell` accepting a line to create an `origin='cross_sell'` Opportunity owned by the most-recently-issued active policy's agent (guarded; re-validates the line is genuinely uncovered → 409).
- **Rough scope:** Household detail + cross-sell endpoints (only a name-search picker exists today). Coverage via the `policy → opportunity.product_line` join; session-scoped visibility.
- **Open questions / decisions for stakeholders:** **observability** — should a cross-sell accept write an audit record (P1.4), beyond the `opportunity.created` event? Coverage edge cases confirmed against the seed at plan time.
- **Depends on:** Epic 2 (`cross_sell` origin), Epic 5 (seeded partial/full households).
- **Implementation notes:** _none yet_

## Epic 14 — Household page + cross-sell prompt [UI]
- **Goal:** A Household detail page + nav/route showing contacts, active policies with a *Renewal Due* badge (overlay-aware), and cross-sell prompt cards with one-click Accept — suppressed when the household is fully covered.
- **Rough scope:** New page + route + nav entry + data layer to the Epic 13 endpoints. All elements carry unique descriptive `id`s.
- **Open questions / decisions for stakeholders:** UI/UX Guide components for the policy list, *Renewal Due* badge, and cross-sell cards — confirmed at plan time (frontend-design craft within the Guide).
- **Depends on:** Epic 13, Epic 7 (overlay-aware policy rendering).
- **Implementation notes:** _none yet_

## Epic 15 — QA checklist: Household & cross-sell
- **Goal:** Write the section's QA checklist — opening a partially-covered household and accepting a cross-sell suggestion, a fully-covered household showing no prompt, a household with no active policy, the *Renewal Due* badge on a renewed policy, and edge cases (accept an already-covered line → 409, permissions, expired session). `- [ ]` steps with expected results, no code refs.
- **Rough scope:** `qa-checklist-P2.4-renewals-cross-sell-household-and-cross-sell.md`.
- **Open questions / decisions for stakeholders:** none expected.
- **Depends on:** Epics 13–14.
- **Implementation notes:** _none yet_

## Epic 16 — Acceptance suite
- **Goal:** Automated acceptance proving all three threads end-to-end (AEP sweep, anniversary sweep, cross-sell accept), task-queue completion, and the byte-identical-seed assertion after the threads run.
- **Rough scope:** A named acceptance test module over the real substrate; no product code changes expected.
- **Open questions / decisions for stakeholders:** none expected.
- **Depends on:** the feature epics (Epics 5–14).
- **Implementation notes:** _none yet_
