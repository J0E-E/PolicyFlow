# P2.4 — Renewals & Cross-sell — Technical Design Document

> **Build strategy:** Tracer bullet — chosen at design time (rationale in §6); `3-tdd-to-epic-plan` slices the epics by it and copies it to the epic-plan header (`0-conventions.md` → *Build strategies*).

## 1. Summary

Build the two post-policy opportunity-generation workflows — per-product renewal generation
(seasonal AEP sweep + anniversary job) and the Household cross-sell prompt — plus the agent task
queue that surfaces the generated work (walkthrough step 15). Renewal rules become a per-product-line
attribute; Platform-Admin buttons fire the sweeps on demand for the visitor's demo session; seeded
policies show *Renewal Due* via a read-time overlay and are never mutated; the cross-sell prompt is a
live coverage check on a new Household page. Everything reuses the existing scheduler pattern, session
layering, event/outbox bus, and workspace-control pattern — the risk is domain-rule + UX correctness,
not architecture, hence tracer bullet.

## 2. Business Requirements

Source: [brd-P2.4-renewals-cross-sell.md](./brd-P2.4-renewals-cross-sell.md). Constraints/clarifications
surfaced during design that the BRD doesn't already state:

- The BRD's renewal buckets ("MA/Part D", "Hospital Indemnity/LTC", "Life/Annuities") have **no
  matching keys** in the product-line registry; existing lines are classified instead (ADR 0003).
- There is **no demo clock** — all code reads real `datetime.now(utc)`, and today falls outside the
  Oct 15–Dec 7 AEP window; the on-demand button therefore bypasses the seasonal gate (ADR 0004).
- There are **no baseline money-path entities** seeded today (only baseline leads); the seed must
  build whole baseline chains (household → contact → opportunity → application → policy) for the
  sweeps and cross-sell to have targets in a fresh session.

## 3. Goals / Non-Goals

**Goals**
- Per-product renewal generation (AEP / anniversary / none) observable live via Platform-Admin buttons.
- Each renewal → Renewal Opportunity (`origin='renewal'`) + assigned renewal-review Task + `policy.renewal_due`.
- Idempotent generation (ADR 0001) with generated/skipped counts.
- Seeded policies untouched; *Renewal Due* shown via a session-scoped read-time overlay (ADR 0005).
- Live cross-sell prompt on a Household page (ADR 0002); one-click Opportunity.
- Agent task queue: view (own/all by role), overdue flag, record link, complete.

**Non-Goals** (per BRD §4)
- Real notification delivery (M3); issuing a policy from a Renewal Opportunity (reuses P2.3 path);
  lapse/cancel beyond the current status set; task snooze/reassign/due-date-edit/manual-create;
  a background renewal scheduler; a frozen demo clock.

## 4. Current State

- **Scheduler pattern** — [`core/app/demo/runtime.py`](../../core/app/demo/runtime.py): a FastAPI
  lifespan runs an `asyncio` loop (`run_demo_lifecycle_loop`) with a pure crossing helper
  (`crossed_nightly_reset`). The model to mirror for pure schedule predicates (no loop is wired).
- **Session layering** — [`core/app/leads/visibility.py`](../../core/app/leads/visibility.py)
  `visible_to_session`; opportunities mirror it via `_scope_to_session` /
  `_guard_opportunity_for_session` in [`opportunities/router.py`](../../core/app/opportunities/router.py)
  (foreign-session 404, seed 409).
- **Workspace-control pattern** — `WorkspaceResetControl.tsx` + `POST /api/demo/session/reset`
  (`require_platform_admin`, resolves the caller's demo session, 409 if none) in
  [`demo/router.py`](../../core/app/demo/router.py). Demo session tracks `last_tenant_slug`.
- **Models** — [`Opportunity`](../../core/app/models/opportunity.py) (has `origin`,
  `target_close_date`, `source_lead_id NOT NULL`, no policy link); [`Policy`](../../core/app/models/policy.py)
  (`status` plain text default `Active`, `opportunity_id`, `contact_id`, only date is `issued_at`, no
  `product_line`); [`Task`](../../core/app/models/task.py) (`due_date`/`status` nullable placeholders
  "P2.4 fills", polymorphic `related_entity_*`, no `task.created` event); `Household`/`Contact`
  (contact carries `owner_user_id`).
- **Registry** — [`tenancy/registry.py`](../../core/app/tenancy/registry.py) `ProductLine`
  (`requires_medicare_age`, `application_step` precedent for a new flag); Sunshine
  `{medicare_advantage, medicare_supplement, final_expense, dental_vision_hearing}`, Florida
  `{term_life, whole_life, health, critical_illness}`.
- **Events** — [`events/catalog.py`](../../core/app/events/catalog.py) `EventType` + `CONSUMER_BINDINGS`;
  `sync.logger` binds `#`, so a new event needs no new binding. Emit pattern: `build_envelope` +
  `enqueue_event` on the request transaction ([`opportunities/service.py`](../../core/app/opportunities/service.py)).
- **State machine** — `AUTOMATION_OWNED_STAGES = {Application Started, Submitted, Approved, Policy Active}`
  in [`opportunities/state.py`](../../core/app/opportunities/state.py); `'New'` is manually reachable.
- **Households** — only a name-search picker (`GET /api/households?q=`,
  [`leads/households_router.py`](../../core/app/leads/households_router.py)); **no** detail page/endpoint.
  **No** policies-list endpoint (policy surfaces via `PolicySummary` on opportunity detail,
  [`policies/read.py`](../../core/app/policies/read.py) `serialize_policy`). **No** tasks router.
- **Migration head** — `0019`; seed creates baseline leads only ([`core/app/seed.py`](../../core/app/seed.py)).

## 5. Proposed Design

### 5.1 Renewal rules (registry)
- Add `renewal_rule: str = "none"` to `ProductLine` (mirrors `requires_medicare_age`); classify all
  lines per ADR 0003. New pure module `app/renewals/rules.py`:
  - `in_aep_window(today) -> bool` (Oct 15 ≤ today ≤ Dec 7).
  - `anniversary_within(issued_at, today, days=60) -> bool` (next yearly anniversary of `issued_at`
    is ≤ `days` away).
  - `renewal_deadline(rule, cycle_year, anniversary_date) -> date` (AEP → Dec 7 of cycle year;
    anniversary → the anniversary date).
  - `renewal_cycle_key(rule, ...) -> str` (`aep-<year>` / `anniv-<year>`).
  All clock-free/DB-free, unit-tested (MA=aep, ancillary/health=anniversary-60d, life=never).

### 5.2 Data model (migration 0020)
- `opportunities`: add `source_policy_id UUID NULL`, `renewal_cycle TEXT NULL`; **relax
  `source_lead_id` to nullable**. `origin` gains values `'renewal'` and `'cross_sell'` (text, no enum).
- Partial unique index `(source_policy_id, renewal_cycle, demo_session_id) WHERE origin='renewal'`
  (race guard; session in the key so concurrent sessions renewing the same seeded policy don't collide).
- Policy `status` gains a valid value `'Renewal Due'` (no schema change — plain text; a guard allows
  only `Active → Renewal Due`, session-owned rows only).

### 5.3 Events
- Add `EventType.POLICY_RENEWAL_DUE = "policy.renewal_due"`; **no** new `CONSUMER_BINDINGS` entry
  (rides `sync.logger` `#`). Catalog test asserts the new member + unchanged bindings.
- Each generated renewal, in one request transaction (outbox), emits **both** `opportunity.created`
  (new renewal opp) and `policy.renewal_due`, on a **new** `correlation_id` (uuid4), `causation_id=None`.
  Payloads (non-PII):
  - `opportunity.created`: `{entity_id, contact_id, household_id, origin:'renewal', source_policy_id}`.
  - `policy.renewal_due`: `{entity_id: policy_id, opportunity_id, contact_id, household_id, renewal_kind:'aep'|'anniversary', due_date}`.
- Cross-sell accept emits `opportunity.created` `{entity_id, contact_id, household_id, origin:'cross_sell', source_policy_id}` on a new `correlation_id`.

### 5.4 Renewal generation (`app/renewals/service.py`)
- `generate_renewals(db, tenant_config, *, rule, demo_session_id) -> {generated, skipped}`:
  1. Select active (`status in {Active, Renewal Due}`) policies on `renewal_rule == rule` lines,
     **session-visible** (baseline ∪ session), joined `policy → opportunity` for `product_line` + owner.
  2. For each, filter by the rule's window (anniversary → `anniversary_within`; AEP → **no** date gate
     on the button, ADR 0004; none → never selected).
  3. Compute `cycle_key`; skip if an opportunity exists with matching `source_policy_id + renewal_cycle`
     in session scope (any stage — covers closed/lost, ADR 0001) → `skipped++`.
  4. Else create the Renewal Opportunity (`origin='renewal'`, stage `'New'`, `owner_*` from the
     originating opportunity, `contact_id`/`household_id` from the policy's contact, `source_policy_id`,
     `renewal_cycle`, `target_close_date = renewal_deadline`), the renewal-review Task, and the two
     events; if the policy is **session-owned**, write `status='Renewal Due'` (baseline policies never
     written — overlay handles them). `generated++`.

### 5.5 Renewal-review Task
- `task_type='renewal_review'`, `related_entity_type='opportunity'`, `related_entity_id=renewal_opp.id`,
  `assignee_user_id/username` = owning agent, `body` = "Review renewal for `<policy_number>` (`<label>`)",
  `due_date = target_close_date`, `status='open'`, `demo_session_id`, new `correlation_id` shared with
  the renewal chain. (No `task.created` event — matches the model's contract.)

### 5.6 Renewal Due overlay (ADR 0005)
- Read-time derivation wherever a policy status renders: `serialize_policy` gains an
  `overlay_renewal_due: bool` input → returns `status='Renewal Due'` when the stored status is
  `Renewal Due` **or** (policy is baseline `demo_session_id IS NULL` **and** the caller's session has a
  renewal opportunity with `source_policy_id = policy.id`). Applied on the opportunity-detail policy
  view and the new Household page.

### 5.7 Sweep endpoints (`app/renewals/router.py`)
- `POST /api/renewals/aep-sweep`, `POST /api/renewals/anniversary-sweep`; both `require_platform_admin`,
  resolve the caller's demo session (409 if none) and its `last_tenant_slug` (409 if none), open a
  scoped write session for that one tenant (the `ensure_session_leads` pattern), call
  `generate_renewals` for the rule, return `{generated, skipped}`. Single-tenant scope (ADR/§6).

### 5.8 Task queue (`app/tasks/router.py`)
- `GET /api/tasks`: Agent → own non-completed tasks; Tenant Admin & Read-Only → all (`?assignee=`
  filter); scoped by `visible_to_session`; ordered `due_date` ascending (overdue/soonest first, nulls
  last); each row `{id, task_type, body, due_date, is_overdue, related_entity_type, related_entity_id,
  assignee_username, status}`, `is_overdue = due_date < now`.
- `POST /api/tasks/{id}/complete`: `require_capability(CREATE_EDIT_RECORDS)` + (assignee or Tenant
  Admin) else 403; session write-isolation (foreign 404 / seed 409); sets `status='completed'`
  (`updated_at` stamps completion — no `completed_at` column).

### 5.9 Household page + cross-sell (`GET /api/households/{id}`, `POST /api/households/{id}/cross-sell`)
- Detail read returns `{household, contacts[], policies[] (active, overlay-aware), cross_sell[]}`.
  `cross_sell` = one entry per uncovered tenant product line; covered = tenant lines with ≥1 active
  policy (via `policy → opportunity.product_line`); suppressed when all covered or no active policy
  (ADR 0002). Session-scoped visibility.
- Accept `{product_line}` → creates `origin='cross_sell'` Opportunity (stage `'New'`, the uncovered
  line, `owner_*` + `contact_id` + `source_policy_id` from the household's **most-recently-issued
  active policy**, session-tagged), emits `opportunity.created`. Guard: `CREATE_EDIT_RECORDS` +
  owner/Tenant-Admin; validates the line is genuinely uncovered (else 409).

### 5.10 Frontend
- Platform-Admin workspace: two sweep buttons beside `WorkspaceResetControl`, showing the
  `{generated, skipped}` result. New **Task Queue** page + nav entry (list, overdue badge, record link,
  Complete). New **Household** detail page + nav/route (contacts, active policies with *Renewal Due*
  badge, cross-sell prompt cards with one-click Accept, suppressed when covered). All elements carry
  unique descriptive `id`s.

### 5.11 Primary flow (AEP thread)
Platform Admin (in the visitor's session, `last_tenant_slug=sunshine`) clicks **run AEP sweep now** →
`generate_renewals(rule=aep)` over Sunshine's session-visible active `medicare_advantage` policies →
for the seeded MA policy: new Renewal Opportunity + renewal-review Task + `opportunity.created` +
`policy.renewal_due` (all one txn, new correlation) → button shows `{generated:1, skipped:0}`. Switch
to the owning Agent (same session): the opportunities board shows the renewal card, the task queue
lists the renewal Task, the policy reads *Renewal Due* (overlay). Re-run → `{generated:0, skipped:1}`.

## 6. Decisions

**D1 — Renewal rule = per-product-line attribute, mapped by plausible behavior (ADR 0003)**
- *Chosen:* `renewal_rule` on `ProductLine`; aep=`{medicare_advantage}`, anniversary=`{medicare_supplement,
  dental_vision_hearing, health, critical_illness}`, none=`{final_expense, term_life, whole_life}`.
- *Alternatives:* MedSupp also AEP; add BRD-literal Part D/Hospital Indemnity/LTC/Annuities lines.
- *Rationale:* the registry has none of the BRD's bucket names; classifying existing lines (vs new
  lines + seed + quote templates) lets Sunshine alone show all three threads, at near-zero new surface.

**D2 — On-demand-only sweeps; button bypasses the AEP calendar; no demo clock (ADR 0004)**
- *Chosen:* buttons are the whole runtime; AEP button generates regardless of date; schedule semantics
  are pure tested predicates; no background loop.
- *Alternatives:* also wire a background renewal loop; introduce a frozen demo "today".
- *Rationale:* FR4 needs no scheduled firing observed; today is outside the AEP window so a
  calendar-honoring button couldn't demo; a background job auto-mutating data risks the
  byte-identical-seed guarantee and multi-session nondeterminism.

**D3 — Renewal links via nullable columns on `opportunities`; owner from the originating opportunity**
- *Chosen:* add `source_policy_id` (nullable), relax `source_lead_id` to nullable, `origin` gains
  `'renewal'`; owner copied via `policy.opportunity_id`; entry stage `'New'`.
- *Alternatives:* owner from `contact.owner_user_id`; a separate renewals link table.
- *Rationale:* one cheap migration on the existing table (the `target_close_date`/`requires_medicare_age`
  precedent); `'New'` is not automation-owned so the P2.3 lockdown is a non-issue; policy has no owner,
  so the originating opportunity is the truthful owner source.

**D4 — Idempotency via a dedicated `renewal_cycle` column (implements ADR 0001)**
- *Chosen:* nullable `renewal_cycle` (`aep-<year>`/`anniv-<year>`); session-scoped skip check on
  `(source_policy_id, renewal_cycle)`, any stage; partial unique index incl. `demo_session_id`.
- *Alternatives:* derive the cycle from `target_close_date`'s year (no column).
- *Rationale:* an explicit key makes the skip check a clean equality and testable; session in the index
  key keeps concurrent sessions independent.

**D5 — `Renewal Due` overlay derived at read from the session's renewal opportunity (ADR 0005)**
- *Chosen:* baseline policy shows *Renewal Due* when the session holds a renewal opp for it; no stored
  flag/table; session-created policies take the real guarded write.
- *Alternatives:* a session-scoped overlay table.
- *Rationale:* the renewal opp is already the authoritative signal; deriving is DRY, keeps seeded rows
  byte-identical, and mirrors ADR 0002's live-check.

**D6 — Renewal events: `opportunity.created` + `policy.renewal_due`, new correlation, no new binding**
- *Chosen:* both events per renewal on a fresh `correlation_id`; add `POLICY_RENEWAL_DUE`; ride
  `sync.logger`.
- *Alternatives:* only `policy.renewal_due`; reuse the policy's correlation_id.
- *Rationale:* keeps the "every opportunity emits opportunity.created" invariant; BRD §7 wants a new
  linked correlation; `#` binding needs no new consumer (P2.2/P2.3 precedent).

**D7 — Task queue: two-state `open`/`completed`, completion via `updated_at`, all non-completed shown**
- *Chosen:* no `completed_at` column; queue lists every non-completed assigned task (note-tasks +
  renewal tasks); role-scoped read, guarded complete.
- *Alternatives:* add `completed_at`; show only renewal tasks.
- *Rationale:* BRD excludes snooze/reassign/etc., so minimal state suffices; `updated_at` already
  records the change; surfacing legacy note-tasks is a free win.

**D8 — Cross-sell on a new Household page; owner/contact from the triggering (most-recent active) policy**
- *Chosen:* build `GET /api/households/{id}` + page; coverage via `policy→opportunity`; accept creates
  `origin='cross_sell'` opp owned by the most-recent active policy's agent, its contact, `source_policy_id` set.
- *Alternatives:* owner from `contact.owner_user_id`; fold the prompt onto an existing surface.
- *Rationale:* the BRD says "on the Household page" (none exists); "triggering policy's owning agent" is
  literal, and most-recent-active is a deterministic pick when a household holds several.

**D9 — Single-tenant sweep scope (`last_tenant_slug`)**
- *Chosen:* sweep the one tenant the visitor was exploring, over its session-visible active policies.
- *Alternatives:* cross-tenant fan-out like the purge engine.
- *Rationale:* the demo is linear (the visitor is in one tenant); a single scoped write session is far
  simpler than cross-schema fan-out, and the seed guarantees targets per tenant. Low cost to revisit.

**D10 — Build strategy = tracer bullet, AEP thread first**
- *Chosen:* thinnest customer-visible thread (AEP sweep → renewal opp + task + overlay + idempotent
  re-run) end-to-end first, then anniversary, cross-sell, task queue.
- *Alternatives:* walking skeleton.
- *Rationale:* the architecture already exists and is proven; the risk is domain-rule + UX correctness;
  matches the program plan's M2 lock.

## 7. Risks and Open Questions

- **Baseline seed size** — whole money-path chains in both tenants are net-new seed surface; keep them
  minimal and idempotent, and assert byte-identical after the threads (acceptance).
- **Anniversary back-dating drift** — `issued_at` is computed relative to seed-run `now`, so it is not
  byte-identical across re-seeds (acceptable, matches `policy_number`'s C6 note); *within* a run it is
  static.
- **Overlay everywhere** — every surface that renders a policy status must pass the overlay flag; a
  missed surface would show stale `Active`. Mitigation: route all policy status rendering through the
  overlay-aware `serialize_policy`.
- **Cross-schema write from a tenantless persona** — the sweep must set the tenant's write role
  correctly (reuse the `ensure_session_leads` scoped-session pattern) or it 403s/writes to the wrong schema.
- **Open:** exact seed personas/households per tenant (owning agents for the MA/anniversary policies,
  which household is partial vs full) — settled at `4-plan-epic` for the seed epic.

## 8. Rollout / Verification

- **Migration 0020** (additive: nullable columns + relaxed `source_lead_id` + partial unique index) —
  forward-only, no backfill; the green gate runs `alembic check` (schema-less tables excluded as today).
- **Manual verify** (fresh demo session, Sunshine): assume Platform Admin → run AEP sweep → see
  `{1,0}`; assume Agent → board shows the renewal card, task queue lists the Task, policy reads
  *Renewal Due*; complete the Task → it clears; re-run sweep → `{0,1}`. Repeat with the anniversary
  button on the back-dated policy; confirm the `final_expense` policy generates nothing. Open a
  partially-covered Household → see the prompt → accept → Opportunity created owned by the policy's
  agent; open a fully-covered Household → no prompt. Confirm seeded rows unchanged.
- **Backwards compatibility** — new event type is additive; existing consumers unaffected (`sync.logger`
  `#`); no existing endpoint changes shape (policy reads gain an overlay-derived status only).

## 9. Work Breakdown

Ordered simplest-first, tracer-bullet (item 5 is the thinnest customer-visible end-to-end slice).
Favor small items so the epic plan inherits a layered shape.

1. **Renewal rules + pure predicates** — `renewal_rule` on `ProductLine` + classification (ADR 0003);
   `app/renewals/rules.py` (`in_aep_window`, `anniversary_within`, `renewal_deadline`,
   `renewal_cycle_key`); unit tests.
2. **Migration 0020** — `opportunities.source_policy_id`/`renewal_cycle` nullable, `source_lead_id`
   relaxed, partial unique index; `'renewal'`/`'cross_sell'` origins; `'Renewal Due'` policy status allowed.
3. **Event vocabulary** — add `POLICY_RENEWAL_DUE` (no new binding); catalog test.
4. **Renewal generation core** — `app/renewals/service.py::generate_renewals` (select → window filter →
   idempotency skip → create opp + task + events; session-owned real status write); unit-tested against a seeded fixture.
5. **[UI] AEP sweep tracer** — `POST /api/renewals/aep-sweep` (platform-admin, session + `last_tenant_slug`
   scoped) + Platform-Admin workspace button + `{generated, skipped}`; **includes** the derive-at-read
   overlay for the seeded MA policy on one read surface; idempotent re-run. *The customer-visible slice.*
6. **Overlay hardening** — session-created real `Active → Renewal Due` write (guarded) + overlay applied
   on every policy-status surface via `serialize_policy`.
7. **[UI] Anniversary sweep** — `POST /api/renewals/anniversary-sweep` over anniversary-line policies in
   the 60-day window; `final_expense`/life generates nothing (test-verified).
8. **Task queue backend** — `GET /api/tasks` (role-scoped, ordered, overdue) + `POST /api/tasks/{id}/complete`;
   session isolation.
9. **[UI] Task queue page** — nav entry, list, overdue badge, record link, Complete.
10. **Household detail backend** — `GET /api/households/{id}` (contacts, active overlay-aware policies,
    live cross-sell suggestions) + `POST /api/households/{id}/cross-sell` accept.
11. **[UI] Household page + cross-sell prompt** — nav/route, one card per uncovered line, one-click
    Accept, suppressed when covered.
12. **Seed baseline chains** — both tenants: MA (Sunshine), anniversary-line (back-dated), none-line,
    partial + full cross-sell households; idempotent.
13. **Acceptance suite** — three threads end-to-end + task-queue completion + seeded-rows-byte-identical assertion.
