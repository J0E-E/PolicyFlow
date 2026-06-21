# P1.8 — Seed data, demo-session lifecycle & reset — Technical Design Document

## 1. Summary

P1.8 makes the demo a **sandboxed, self-cleaning** experience. It introduces a
first-class **demo session** — a visit-scoped, tenant-agnostic identity carried in
its own `pf_demo_session` cookie and backed by a `platform.demo_sessions` row — that
tags every visitor-created record, isolates concurrent visitors layered over a
**shared read-only seed**, drives a live masthead countdown, and is purged on a 24h
expiry, nightly, on operator demand, or by the visitor's own session-scoped reset.
The `leads.demo_session_id` column and the event-envelope field already exist as
no-op seams (always `None`); this phase fills them, adds the visibility filter that
keeps one visitor from seeing another's leads in the shared tenant schema, instantiates
a private claimable queue per session, and stands up the purge engine + its in-process
scheduler. The shippable outcome: lists/queue render non-trivially from seed alone,
concurrent visitors never collide, and expired sessions degrade gracefully.

## 2. Business Requirements

Source requirements (no per-phase BRD — this phase derives from the program plan slice
and the behavioral spec):

- [program-and-phase-plan.md](../program-and-phase-plan.md) → **P1.8** (goal, acceptance,
  isolation note, Decide-Once #9 demo-session model, Risk #5 purge cascade).
- [PolicyFlow_Requirements.md](../PolicyFlow_Requirements.md) → **Demo Sessions and Data
  Lifecycle**, **Seed Data Requirements**, **Demo Access Model** (the role switcher /
  surface toggle / Platform-Admin demo controls), **Event System** (the optional
  `demo_session_id` on events).
- [UI_UX_Guide.md](../UI_UX_Guide.md) → **§6.5** (session indicator: live mono countdown,
  "YOUR SESSION" marginal tag, overlay labels, graceful-expiry notice).

Constraints/clarifications surfaced **during this design** that the spec does not state
outright (rationale lives in §6):

- The demo session is **tenant-agnostic** and survives both role switches *and* tenant
  switches — one session per visit, not one per tenant.
- "Shared read-only seed" is honored by **never mutating** seed rows: the actionable
  queue leads are **instantiated per session**, not shared. The shared `NULL` baseline
  is read-only display/dashboard fuel.
- "Reset to canonical seed state nightly" is, given a read-only baseline, exactly
  "purge all session overlays" — **no** truncate/reseed is required.
- The nightly automatic reset can catch an active visitor; that collateral is accepted
  (pinned to a quiet hour, caught by the graceful-expiry path). Only the gentle expiry
  purge runs frequently.

## 3. Goals / Non-Goals

**Goals**
- A demo session that spans the unauthenticated Shopper surface, the authenticated Agent
  workspace, and every role/tenant switch; tagged onto every visitor-created lead.
- Concurrent-visitor isolation within a shared tenant schema (seed ∪ my-session).
- Per-session instantiation of a private, claimable queue from canonical templates.
- 24h expiry purge + nightly canonical reset + operator on-demand reset + visitor
  session-scoped reset — one purge engine, run in-process + via a CLI.
- A live masthead countdown and graceful expired/unknown-session handling (no raw
  404/500; one-click fresh session).
- Events originating in a demo session carry `demo_session_id` (the M3 sidecar-purge
  contract).

**Non-Goals**
- Sidecar-store purge cascade (enrichment/sync/notification records) — those stores gain
  the `demo_session_id` tag and purge in **M3** (Risk #5); P1.8 only purges **core**
  (leads) and readies the event contract.
- Durable cross-device session, multi-replica purge coordination (single core replica
  assumed; advisory-lock deferred), and a sliding/extendable expiry (fixed 24h).
- New domain entities (contacts/households/opportunities/policies/historical events) —
  the fuller seed lands as those entities are built (M2+). P1.8's seed expansion is
  leads-only.
- The demo Platform-Admin *renewal-sweep* / *failure-simulation* controls — only the
  **reset** control lands here; the others arrive with their domains (M2/M3).

## 4. Current State

- **The seam already exists.** [`leads/intake.py`](../../core/app/leads/intake.py) builds
  every lead with `demo_session_id=None`; [`events/envelope.py`](../../core/app/events/envelope.py)
  carries an always-`None` `demo_session_id` (Decision 11 deferred it here);
  [`models/lead.py`](../../core/app/models/lead.py) has the nullable `demo_session_id`
  column (migration `0009`).
- **Entry point.** [`demo/router.py`](../../core/app/demo/router.py) — `POST /api/demo/assume-persona`
  is the passwordless front door **and** every role switch; it revokes+re-mints the
  `pf_session` auth session each call. `GET /api/tenants` is public + DB-free.
- **Reads to filter.** [`leads/router.py`](../../core/app/leads/router.py) (`GET /api/leads`
  list+queue, `GET /api/leads/{id}`, the claim/qualify/reject/resolve-duplicate actions,
  reveal) and [`leads/matching.py`](../../core/app/leads/matching.py) (`find_duplicate_lead`)
  all currently see **every** row in the tenant schema.
- **Masked shape.** [`leads/masking.py`](../../core/app/leads/masking.py) `build_masked_lead`
  excludes `demo_session_id`; it needs to derive the session markers.
- **Scoping seams.** [`tenancy/scoping.py`](../../core/app/tenancy/scoping.py) — `get_tenant_db`
  (session-identity tenant), `get_public_tenant_db` (body-slug tenant, owns the request
  transaction). Per-concern privileged roles already exist (`outbox_relay`, `event_consumer`,
  `audit_writer`) granted by migrations — the pattern `demo_purge` follows.
- **Background-task pattern.** [`events/runtime.py`](../../core/app/events/runtime.py)
  `event_bus_lifespan` runs the relay + consumers as in-process `asyncio` tasks in the
  FastAPI lifespan — the model the `demo_lifecycle` task mirrors.
- **Seed.** [`seed.py`](../../core/app/seed.py) — `seed_demo_leads` inserts shared `NULL`
  queue leads at boot (per-lead insert-if-absent on `email_blind_index`); `entrypoint.sh`
  runs `migrate → seed → serve`. Latest migration is `0010`; P1.8 adds `0011`.
- **Frontend.** [`Masthead.tsx`](../../frontend/src/components/Masthead.tsx) renders a
  **static** "DEMO SESSION" `StampTag` (countdown is "P1.8"); the typed
  [`api/client.ts`](../../frontend/src/api/client.ts) sends `pf_session` via
  `credentials:"include"`; [`SessionProvider`](../../frontend/src/session/SessionProvider.tsx)
  restores identity via `/me`.

## 5. Proposed Design

> Diagram: [demo-session lifecycle, layered read model & purge scopes](./diagrams/tdd-seed-data-demo-session-lifecycle-reset-lifecycle.excalidraw).

### 5.1 The demo session (identity + carrier)

- New `platform.demo_sessions`: `id uuid pk`, `created_at`, `expires_at`,
  `last_tenant_slug text null` (informational; powers "fresh session preserves your
  tenant"). **Tenant-agnostic** — records carry their own `tenant_id` via their schema.
- New `pf_demo_session` cookie carries the **raw** session id (HttpOnly, SameSite=Lax,
  `path=/`, `Secure` per `session_cookie_secure`, `max_age = DEMO_SESSION_LIFETIME`).
  Independent of `pf_session`; unchanged by role switches.
- `app/demo/session.py` — the lifecycle module:
  - `ensure_demo_session(db, request, response, *, tenant_slug=None) -> DemoSessionState`
    — reuse the cookie's live session (refreshing `last_tenant_slug` when a slug is
    given); otherwise mint a fresh row + set the cookie. The single mint point
    `assume-persona`, public intake, and `POST /api/demo/session` all call.
  - `current_demo_session(request) -> DemoSessionState | None` (FastAPI dependency) —
    resolve the cookie to a **live, unexpired** session, else `None`. Read-only (no mint).
  - `DemoSessionState` = `{id, expires_at, last_tenant_slug, status}` where `status ∈
    {active, expired, none}`.

### 5.2 Tagging (write path)

- `build_envelope(..., demo_session_id: uuid|None = None)` — thread it onto the envelope
  (replaces the hardcoded `None`); `to/from_message_body` already serialize it.
- `create_lead(..., demo_session_id: uuid|None)` — set it on the row **and** pass it to
  every `build_envelope` call (`lead.created`, `lead.duplicate_detected`).
- Routes supply it: `POST /api/leads` (agent) and `POST /api/public/intake` (public, via
  `ensure_demo_session` auto-mint) pass `current_demo_session().id`. The claim/qualify/
  reject/resolve-duplicate actions pass the session id onto their events too.

### 5.3 Isolation (read path)

- `app/leads/visibility.py` → `visible_to_session(query, demo_session_id)` adds
  `WHERE demo_session_id IS NULL OR demo_session_id = :sid` (`:sid None` ⇒ seed-only).
- Applied in: `list_leads` (+ queue filter), `find_duplicate_lead`, and — by post-load
  check — `get_lead` and every action endpoint (a row not visible to the caller's session
  → `404 "lead not found"`, identical to the cross-tenant case).
- Mutating actions additionally refuse a **seed** row (`demo_session_id IS NULL`) with a
  `409` (defense-in-depth; the SPA already hides the buttons via `is_seed`).
- The seeded dup-bait stays `NULL`, so "Try a duplicate" still flags for everyone.

### 5.4 Per-session seed instantiation

- New `platform.demo_session_tenant_seed` ledger: PK `(demo_session_id, tenant_slug)`,
  `seeded_at`. Idempotency marker for "this session's queue is instantiated in this tenant."
- `assume-persona`, for a **tenant-scoped** persona, calls
  `ensure_session_leads(db, tenant_config, demo_session_id)`: if no ledger row, insert the
  canonical New queue-lead templates **+ the dup-bait** as session-tagged rows (reusing the
  encrypt/blind-index path, scoped into the tenant schema), then record the ledger row.
  Platform Admin (tenantless) skips it.
- Templates are Python data (the current `DEMO_LEADS` fillers + `JORDAN_RIVERA_BAIT`),
  refactored to be instantiated per session rather than seeded as shared `NULL` rows.
- Boot `seed_demo_leads` is repurposed: it seeds only the **shared read-only** worked/
  historical leads (`Qualified`/`Rejected`/owned) that give the list/dashboard context;
  the New/claimable set moves to instantiation.

### 5.5 Purge engine + scheduler

- `app/demo/purge.py` → `purge_sessions(scope, *, delete_session_row)` opens its **own**
  `demo_purge`-role session and, for each in-scope `demo_sessions.id`:
  - `DELETE FROM <schema>.leads WHERE demo_session_id = ANY(:ids)` for **every** tenant
    schema (registry-driven), then `DELETE` the ledger rows, then (when
    `delete_session_row`) the `demo_sessions` rows. Returns counts for logging.
  - Scopes: `Expired` (`expires_at < now()`, `delete_session_row=True`), `All`
    (`delete_session_row=True`), `Session(id)` (`delete_session_row=False`).
- `app/demo/runtime.py` → `demo_lifecycle_lifespan` (mirrors `event_bus_lifespan`): an
  `asyncio` task looping every `DEMO_PURGE_INTERVAL_SECONDS` running `purge(Expired)`, and
  firing `purge(All)` once when the wall clock crosses `DEMO_NIGHTLY_RESET_HOUR_UTC`
  (tracked by last-run date). Added to `main.py`'s lifespan stack alongside the event bus.
- `python -m app.demo.reset [--all|--expired]` — the operator on-demand CLI; reuses
  `purge_sessions`. Not reachable through the demo role switcher.

### 5.6 HTTP surface (frontend-facing)

- `GET /api/demo/session` — **public**, reads the cookie via `current_demo_session`;
  returns `{status, demo_session_id?, expires_at?, last_tenant_slug?}`. Source for the
  countdown + expiry detection on **both** surfaces.
- `POST /api/demo/session` — **public**; `ensure_demo_session(tenant_slug?)` mints/sets the
  cookie and returns the state — the one-click "fresh session" button.
- `POST /api/demo/session/reset` — `require_platform_admin`; `purge(Session(cookie id),
  delete_session_row=False)`; keeps the row + cookie + expiry. Re-seed is deferred to the
  next `assume-persona` (ledger now cleared).
- `assume-persona` gains: `ensure_demo_session` (reuse-or-mint, refresh `last_tenant_slug`)
  then `ensure_session_leads` for tenant-scoped personas — both before returning identity.

### 5.7 Masked-read markers + frontend

- `build_masked_lead(tenant_id, lead, current_session_id)` adds `is_seed`
  (`demo_session_id IS NULL`) and `is_session_record` (`== current_session_id`); the raw
  id still never leaves.
- Masthead: replace the static stamp with a live `DEMO SESSION · HH:MM REMAINING` mono
  countdown ticking locally from `expires_at`; reads `GET /api/demo/session`.
- Lists/detail: "YOUR SESSION" marginal tag on `is_session_record` rows; hide mutating
  actions on `is_seed` rows; label shared seed/overlays.
- Graceful expiry: a `DemoSessionGate`/notice — when `status != active` (or a deep-link
  lead read 404s while `status != active`), render "your previous demo session ended —
  demo data resets every 24 hours" with a one-click fresh session (`POST /api/demo/session`
  with the remembered tenant), never a raw 404/500. Stepper progress resets with the session.
- The demo Platform-Admin **reset** control surfaces in the workspace (a demo-controls
  affordance) calling `POST /api/demo/session/reset`.

### 5.8 Migration `0011` & config

- `0011`: `platform.demo_sessions`, `platform.demo_session_tenant_seed`, the `demo_purge`
  role + grants (cross-schema `DELETE`/`SELECT` on each tenant's `leads`, `DELETE`/`SELECT`
  on the two platform tables), and a per-tenant index on `leads.demo_session_id` (purge +
  filter performance). Schema-less-table hygiene per the `0009` precedent.
- Config knobs: `DEMO_SESSION_LIFETIME_SECONDS` (86400), `DEMO_PURGE_INTERVAL_SECONDS`
  (~300), `DEMO_NIGHTLY_RESET_HOUR_UTC` (4), `demo_purge` DB creds. Demo deployment sets
  `SESSION_LIFETIME_SECONDS=86400` to align the auth session to the demo session.

## 6. Decisions

**D1 — Demo session = dedicated table + own cookie.**
*Chosen:* `platform.demo_sessions` + a `pf_demo_session` cookie, independent of the 8h
`pf_session`. *Alternatives:* a column on `auth_sessions` (re-mints every role switch and
absent on the unauthenticated Shopper surface — can't span both); a stateless signed
cookie (no enumerable registry, so purge would have to `SELECT DISTINCT demo_session_id`
across every tenant table). *Rationale:* a server-side row is enumerable for purge and
authoritative for expiry; the cookie spans both same-origin surfaces and survives auth
re-mints.

**D2 — Visit-scoped, tenant-agnostic session.**
*Chosen:* one session per **visit**; reused across all role *and* tenant switches; minted
only when the cookie is absent/expired; row carries an informational `last_tenant_slug`;
purge sweeps **both** tenant schemas by `demo_session_id`. *Alternatives:* one session per
tenant (a tenant switch would orphan the prior tenant's overlay and fragment the
countdown). *Rationale:* the visitor explicitly wanted continuity across tenant switches;
a single visit identity matches how the countdown and the "your data" sandbox are
experienced.

**D3 — Read isolation via a shared app-level visibility predicate.**
*Chosen:* `demo_session_id IS NULL OR = :mine`, applied uniformly to list/queue/detail/
matcher; other sessions' rows → 404. *Alternatives:* DB-enforced RLS/policy+GUC (fights
the frozen **No RLS** decision and adds migration weight for an *in-tenant* partition);
no filter (violates "concurrent visitors never collide"). *Rationale:* schema-per-tenant
already gives the physical tenant boundary; the softer in-tenant partition is an app
concern, kept in one helper to match the codebase's explicit-seam style.

**D4 — Per-session seed instantiation (not shared, mutable seed).**
*Chosen:* instantiate canonical New queue leads + the dup-bait **per session** at
`assume-persona` (ledger-guarded); worked/historical leads stay shared `NULL` read-only.
*Alternatives:* keep seed shared but block mutations (seeded queue looks claimable but
isn't — a confusing demo); copy-on-write shadowing (complex `NOT EXISTS` on every read).
*Rationale:* gives each visitor a genuinely claimable private queue while keeping the
shared baseline literally read-only, so "concurrent visitors never collide" and "shared
read-only seed" both hold without per-read shadowing.

**D5 — One purge engine; canonical reset = purge all overlays (no truncate/reseed).**
*Chosen:* a single engine parameterized by scope (Expired / All / Session), running as a
dedicated `demo_purge` role. *Alternatives:* canonical reset via `TRUNCATE`+reseed
(heavier, briefly empties the baseline, only justified if the baseline could drift).
*Rationale:* a read-only baseline is **always** canonical, so "reset to canonical state"
reduces to "remove overlays" — the same delete the expiry path already does, just a wider
scope. One engine, three triggers, minimal surface.

**D6 — In-process lifespan scheduler + operator CLI; nightly scope=ALL pinned to a quiet
hour.** *Chosen:* a `demo_lifecycle` task (mirrors `event_bus_lifespan`) running frequent
expiry purge + a nightly scope=ALL at `DEMO_NIGHTLY_RESET_HOUR_UTC`, plus
`python -m app.demo.reset`. *Alternatives:* host cron (departs the in-process pattern,
cadence lives in crontab); a separate worker container (overkill for one periodic job);
**expiry-only automatic, wipe-all CLI-only** (never touches an active visitor, but loses
the "truly fresh every night" guarantee). *Rationale:* matches the existing background-task
pattern and the spec's explicit "nightly" reset; the active-visitor collateral is accepted
— pinned to a quiet hour and caught by the graceful-expiry path (D8), with the countdown
giving advance warning.

**D7 — Session-scoped reset keeps the session, defers re-seed.**
*Chosen:* `POST /api/demo/session/reset` (`require_platform_admin`) purges only the
caller's session data + ledger, **keeps** the `demo_sessions` row + cookie + expiry; the
next `assume-persona` re-instantiates. *Alternatives:* re-instantiate inline (needs a
"current tenant" for a tenant-agnostic session, and the Platform-Admin persona has no queue
view to show it in). *Rationale:* a clean slate with session continuity; deferring re-seed
sidesteps the tenant-ambiguity with zero downside.

**D8 — Graceful surface via a public cookie-based endpoint; client-side countdown.**
*Chosen:* public `GET /api/demo/session` (state) + `POST /api/demo/session` (fresh mint);
the masthead ticks locally from `expires_at`; a deep-link 404 cross-checks the state to
distinguish "session ended" from a plain not-found. *Alternatives:* fold state into
`/api/auth/me` (couples a surface-spanning, unauthenticated concept to the authenticated
identity, and `/me` 401s on the Shopper surface). *Rationale:* the Shopper surface is
unauthenticated, so the state must ride the demo cookie, not the auth session; local
ticking avoids per-second server chatter.

**D9 — Align the auth session to 24h in the demo deployment.**
*Chosen:* `SESSION_LIFETIME_SECONDS=86400` in the demo env (8h stays the non-demo default).
*Alternatives:* leave 8h and re-assume on delayed return (one extra passwordless click,
data preserved). *Rationale:* removes a surprise re-login inside the 24h window for a pure
env change; the demo is the build, so the realistic-8h value isn't sacrificed anywhere it
matters.

**D10 — Events originating in a demo session carry `demo_session_id`.**
*Chosen:* `build_envelope` carries it and the lead-event triggers pass it; **core** (leads)
purges now, sidecar stores in M3. *Rationale:* the spec requires it and it is the contract
the M3 sidecar-purge cascade (Risk #5) binds to — putting the tag on the wire now means the
cascade is a consumer change later, not an envelope change.

## 7. Risks and Open Questions

- **Active-visitor collateral on nightly reset (accepted, D6).** Mitigated by the quiet
  hour + countdown + graceful fresh-session. Revisit if real traffic ever overlaps the
  window.
- **Multi-replica double-run.** The in-process scheduler assumes a **single** core replica
  (true today). If core ever scales horizontally, two loops would both purge — deletes are
  idempotent, but a Postgres advisory lock around `purge(All)` should gate it. Deferred,
  noted.
- **Sidecar cascade is out of scope (Risk #5).** P1.8 purges only `leads`. `processed_events`
  and future sidecar records are **not** yet purged; the event tag readies M3. A session's
  outbox/processed rows surviving purge is acceptable (they carry no PII and self-expire
  with the demo's overall reset).
- **Instantiation timing.** Per-session instantiation fires at `assume-persona`; a visitor
  reaching a tenant-scoped lead surface without an `assume-persona` for that tenant would
  see an un-seeded queue — but the Agent workspace is *only* reachable via `assume-persona`,
  so the choke point holds. If a future surface bypasses it, fall back to the lazy
  `ensure_session_leads`-at-read variant.
- **Open:** exact count/shape of the shared read-only historical leads and the per-session
  template set (variety across statuses) — settled at epic-plan time against the
  "render non-trivially" bar.

## 8. Rollout / Verification

- **Migration:** `0011` adds two platform tables, the `demo_purge` role + grants, and the
  per-tenant `demo_session_id` index. `alembic check` drift-clean + a `0011` down/up
  round-trip, per the `0007`–`0010` precedent. Re-seed on deploy stays idempotent.
- **Config/env:** set `DEMO_*` knobs and `SESSION_LIFETIME_SECONDS=86400` for the demo
  deployment (SSM/Terraform); `demo_purge` creds wired like `outbox_relay`/`audit_writer`.
- **Backwards compatibility:** the envelope/`create_lead` signature changes are additive
  with `None` defaults; existing events deserialize unchanged (`demo_session_id` already in
  the wire shape). Pre-existing shared `NULL` leads remain valid (visible to all, read-only).
- **Manual verification (local stack):**
  1. Two browsers → pick the same tenant → each sees its **own** queue; neither sees the
     other's self-service lead (concurrent isolation).
  2. Submit the dup-bait → flags against the session's own bait copy.
  3. Masthead shows a ticking countdown; `GET /api/demo/session` returns `active`.
  4. Force-expire a session (short `DEMO_SESSION_LIFETIME`) → expiry purge removes its
     leads; a deep link to one resolves to the friendly notice; one-click fresh session
     restores a clean sandbox preserving the tenant.
  5. As role-switched Platform Admin → **reset** → own session's leads gone; switch back to
     Agent → fresh queue re-instantiated; another visitor's session untouched.
  6. `python -m app.demo.reset --all` → all sessions cleared, shared baseline intact.
- **Acceptance suite** (`test_demo_session_acceptance.py`, real Postgres + RabbitMQ): the
  visibility filter hides cross-session rows; a created lead carries the session id and so
  does its `lead.created` event; expiry/all/session purges delete exactly their scope across
  both schemas and leave the `NULL` baseline; the ledger makes instantiation idempotent;
  `GET /api/demo/session` reports active/expired/none correctly.

## 9. Work Breakdown

Simplest-first; item 1 is the **tracer bullet** — a thin end-to-end slice (mint → tag →
observe) that proves the session identity before the heavier isolation/purge work.

1. **Tracer bullet — mint, carry, tag, observe.** `platform.demo_sessions` (migration
   `0011`, table only) + `ensure_demo_session`/`current_demo_session` + the
   `pf_demo_session` cookie; `assume-persona` mints/reuses; `create_lead` + `build_envelope`
   carry `demo_session_id`; a created lead and its `lead.created` event both show the id.
2. **Public `GET /api/demo/session`** — state read from the cookie (`active`/`expired`/`none`).
3. **Masthead live countdown** `[UI]` — replace the static stamp; tick locally from
   `expires_at`.
4. **Public intake tagging + auto-mint** — `POST /api/public/intake` auto-mints and tags.
5. **Visibility predicate** — `visible_to_session` applied to list/queue + detail (404 on
   another session's row).
6. **Matcher scoping** — `find_duplicate_lead` filters to seed ∪ my-session; mutating
   actions refuse seed rows.
7. **Masked-read markers + UI** `[UI]` — `is_seed`/`is_session_record`; "YOUR SESSION" tag;
   hide actions on seed rows.
8. **Ledger + per-session instantiation** — `platform.demo_session_tenant_seed` (migration
   add) + `ensure_session_leads` at `assume-persona`; split the boot seed into shared
   historical vs per-session templates.
9. **Purge engine + `demo_purge` role** — `purge_sessions(scope, …)` + the role/grants
   (migration add); unit-proven across both schemas.
10. **In-process scheduler** — `demo_lifecycle_lifespan` (expiry interval + nightly
    scope=ALL @ quiet hour); wire into `main.py`.
11. **Operator CLI** — `python -m app.demo.reset [--all|--expired]`.
12. **Session-scoped reset** — `POST /api/demo/session/reset` (Platform-Admin), defer
    re-seed; the workspace reset control `[UI]`.
13. **Graceful expiry** `[UI]` — `POST /api/demo/session` fresh-mint button; the expiry
    notice; deep-link-404 → notice; stepper-progress reset with the session.
14. **Config + demo-deploy alignment** — `DEMO_*` knobs + `SESSION_LIFETIME_SECONDS=86400`.
15. **Acceptance suite** — `test_demo_session_acceptance.py` (isolation, tagging, purge
    scopes, idempotent instantiation, session-state reporting).
