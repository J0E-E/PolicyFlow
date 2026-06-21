# P1.8 — Seed data, demo-session lifecycle & reset — Epic Plan

Source TDD: [./tdd-P1.8-seed-data-demo-session-lifecycle-reset.md](./tdd-P1.8-seed-data-demo-session-lifecycle-reset.md)

> **Review budget:** ~150 changed lines · ~8 non-generated files · one focused commit per epic. Tunable per project.

> High-level agile roadmap. Each epic's design specifics are confirmed with stakeholders at epic time (`4-plan-epic`) before any code is written.

This is an **L phase**. The order is simplest-first behind a tracer bullet: Epic 1 fires a thin
mint → carry → tag → observe thread end-to-end to prove the demo-session identity, then the
visible countdown lands, then write-tagging, read isolation, the masked-read markers, per-session
seed instantiation + the richer shared baseline, the purge engine + its triggers (scheduler, CLI,
session reset), graceful expiry, deploy-config alignment, and finally the acceptance gate. Slices
go vertical — every UI-bearing epic ships its backend and carries ` [UI]`. The `demo_session_id`
column + the always-`None` event-envelope field already exist as P1.7 seams; this phase fills them.

## Epic 1 — Tracer bullet: mint, carry, tag, observe — **COMPLETED** (50m · 34.8M tok · 694k tok/min)
- **Goal:** Prove the demo-session identity end-to-end — a visit mints a server-side session carried in its own cookie, and an agent-created lead plus its `lead.created` event both carry that session's id.
- **Rough scope:** The `platform.demo_sessions` table (migration) + a session lifecycle module (`ensure_demo_session` reuse-or-mint, `current_demo_session` read-only resolve) + the `pf_demo_session` cookie; `assume-persona` mints/reuses on each call; thread `demo_session_id` through `create_lead` and `build_envelope` so the agent-intake path tags the row and the event. Introduces the `DEMO_SESSION_LIFETIME_SECONDS` knob (default 86400) that sets `expires_at`.
- **Open questions / decisions for stakeholders:** none — resolved at plan time. (1) `pf_demo_session` cookie mirrors `pf_session` (HttpOnly, SameSite=Lax, Secure per `session_cookie_secure`, path=/), value = the **raw** session UUID, `max_age=DEMO_SESSION_LIFETIME_SECONDS` (86400) set **once at mint** and not refreshed on reuse (fixed 24h, no sliding). (2) Log one `INFO` line **on mint only** — `session id` + `expires_at`; reuse is silent (hot path).
- **Depends on:** none.
- **Implementation notes:**
  - **Plan deviation / cross-epic fact:** `0011` also grants each tenant role (+ `platform_reader`) `USAGE ON SCHEMA platform` + `SELECT ON platform.demo_sessions`, beyond the "table only" plan. The tag path runs under `SET LOCAL ROLE tenant_<x>` (via `get_tenant_db`), which otherwise can't read the `platform` schema — without the grant the tracer fails with "permission denied for schema platform". Epic 3 (public-intake tag, runs under `get_public_tenant_db`) and Epic 4 (scoped reads) inherit this grant; Epic 9 still owns the separate `demo_purge` DELETE role + per-tenant index.
  - **Cross-epic fact:** `current_demo_session(request, db)` takes `db` (not the bare `(request)` the TDD §5.1 sketched) — it must query `platform.demo_sessions`. Epic 2's `GET /api/demo/session` and Epic 6's masked-read marker must pass a session in. It is a plain async helper, not a FastAPI `Depends` dependency.

## Epic 2 — Session-state endpoint + live masthead countdown [UI]
- **Goal:** A public read of the current demo session feeds a live `DEMO SESSION · HH:MM REMAINING` mono countdown on the workspace masthead, ticking locally from `expires_at` — replacing the static P1.6 stamp.
- **Rough scope:** Public `GET /api/demo/session` returning `{status, demo_session_id?, expires_at?, last_tenant_slug?}` (status ∈ active/expired/none) read from the cookie; the masthead countdown component consuming it. The endpoint is the shared seam later epics (graceful expiry, fresh session) reuse.
- **Open questions / decisions for stakeholders:** countdown format + behavior at/near zero; refresh cadence (pure local tick vs occasional re-fetch); explainer-popover copy (UI/UX Guide §6.5).
- **Depends on:** Epic 1.
- **Implementation notes:** _none yet_

## Epic 3 — Public intake auto-mint + tagging
- **Goal:** A self-service lead submitted on the unauthenticated Shopper surface auto-mints a demo session (if none) and is tagged with its id — so visitor-created leads on both routes now carry the session.
- **Rough scope:** `POST /api/public/intake` calls `ensure_demo_session` (sets the cookie on the response) and passes the id into the shared `create_lead`; the claim/qualify/reject/resolve-duplicate actions also carry the session id onto their events.
- **Open questions / decisions for stakeholders:** none expected — the auto-mint seam is the same one Epic 1 builds.
- **Depends on:** Epic 1.
- **Implementation notes:** _none yet_

## Epic 4 — Read isolation: visibility predicate
- **Goal:** One visitor never sees another's leads in the shared tenant schema — list, queue, and detail reads return only seed rows (`demo_session_id IS NULL`) plus the caller's own session rows; another session's row resolves to a 404, identical to the cross-tenant case.
- **Rough scope:** A small `visible_to_session` query helper applied to `list_leads` (+ queue filter) and, by post-load check, `get_lead`; `None` session ⇒ seed-only.
- **Open questions / decisions for stakeholders:** confirm the 404 (not 403) shape for a foreign-session row, to match the existing cross-tenant not-found behavior.
- **Depends on:** Epic 1.
- **Implementation notes:** _none yet_

## Epic 5 — Matcher scoping + seed-row write guard
- **Goal:** Duplicate detection respects session isolation (a visitor's submission only flags against seed ∪ their own rows), and mutating actions refuse to alter a shared seed row.
- **Rough scope:** Apply the visibility predicate inside `find_duplicate_lead`; add a defense-in-depth `409` when a claim/qualify/reject/resolve-duplicate targets a `demo_session_id IS NULL` seed row. The seeded dup-bait stays `NULL` so "Try a duplicate" still flags for everyone.
- **Open questions / decisions for stakeholders:** none expected — predicate and guard are specified in the TDD.
- **Depends on:** Epic 4.
- **Implementation notes:** _none yet_

## Epic 6 — Masked-read session markers + list/detail UI [UI]
- **Goal:** The UI distinguishes shared seed rows from "your session" rows — masked reads expose `is_seed` and `is_session_record` (never the raw id), lists/detail show a "YOUR SESSION" marginal tag, and mutating actions hide on seed rows.
- **Rough scope:** Add the two derived markers to `build_masked_lead` (given the caller's session id); render the tag + label shared seed/overlays + hide actions on `is_seed` in the leads list and detail views.
- **Open questions / decisions for stakeholders:** exact placement/wording of the "YOUR SESSION" tag and the seed/overlay labels (UI/UX Guide §6.5).
- **Depends on:** Epic 4.
- **Implementation notes:** _none yet_

## Epic 7 — Per-session seed instantiation + ledger
- **Goal:** Each tenant-scoped persona gets a private, genuinely claimable New queue instantiated from canonical templates on first `assume-persona`, idempotently — so concurrent visitors each work their own queue without touching shared seed.
- **Rough scope:** A `platform.demo_session_tenant_seed` ledger (migration) as the per-(session, tenant) idempotency marker; `ensure_session_leads` inserts the canonical New queue templates + the dup-bait as session-tagged rows (reusing the encrypt/blind-index path into the tenant schema) when no ledger row exists; refactor the boot seed module to split shared-historical from per-session templates. Platform Admin (tenantless) skips it.
- **Open questions / decisions for stakeholders:** exact count/shape of the per-session template set (variety/product lines per tenant) — settled here against the "render non-trivially" bar; whether the ledger or a separate migration carries this table's number.
- **Depends on:** Epic 4.
- **Implementation notes:** _none yet_

## Epic 8 — Shared read-only historical seed expansion
- **Goal:** Lists and dashboards render non-trivially from seed alone — the shared `NULL` baseline gains a richer set of worked/historical leads (Qualified / Rejected / owned) per tenant that give context without being claimable.
- **Rough scope:** Expand the shared-historical side of the boot seed (the side Epic 7 split out) with a curated cross-status lead set per tenant; these stay `NULL` (read-only, visible to all).
- **Open questions / decisions for stakeholders:** exact count/shape of the shared historical set per tenant (status mix, owners) — the other half of the TDD's open seed-shape question.
- **Depends on:** Epic 7.
- **Implementation notes:** _none yet_

## Epic 9 — Purge engine + `demo_purge` role + operator CLI
- **Goal:** One engine purges a session's leads (and ledger rows) across every tenant schema, parameterized by scope (Expired / All / Session), runnable by hand — the foundation every reset trigger reuses.
- **Rough scope:** `purge_sessions(scope, *, delete_session_row)` opening its own dedicated-role session, deleting session-tagged `leads` across all registry tenant schemas then the ledger then (when asked) the `demo_sessions` rows, returning counts; the `demo_purge` DB role + cross-schema grants + a per-tenant `demo_session_id` index (migration); and `python -m app.demo.reset [--all|--expired]` reusing the engine (not reachable through the demo role switcher). Unit-proven across both schemas.
- **Open questions / decisions for stakeholders:** structured logging on each purge run (scope, per-tenant counts, session ids) — the observability decision for this destructive path; confirm core-only scope (sidecar cascade is M3, Risk #5).
- **Depends on:** Epic 7.
- **Implementation notes:** _none yet_

## Epic 10 — In-process purge scheduler
- **Goal:** Expired sessions self-clean and the demo resets to canonical state nightly without manual action — a background task runs frequent expiry purges and a once-a-night scope=All at a quiet hour.
- **Rough scope:** A `demo_lifecycle` lifespan task (mirroring the event-bus lifespan) looping every `DEMO_PURGE_INTERVAL_SECONDS` running `purge(Expired)` and firing `purge(All)` once per crossing of `DEMO_NIGHTLY_RESET_HOUR_UTC`; wired into the app's lifespan stack. Introduces those two knobs.
- **Open questions / decisions for stakeholders:** none expected — cadence + quiet-hour are config; the accepted active-visitor nightly collateral and the deferred multi-replica advisory lock are recorded in TDD §7 (single-replica assumed here).
- **Depends on:** Epic 9.
- **Implementation notes:** _none yet_

## Epic 11 — Session-scoped reset + workspace reset control [UI]
- **Goal:** A visitor's role-switched Platform Admin can wipe their own session's data to a clean slate from the workspace — without touching any other visitor and keeping their session/cookie/countdown alive.
- **Rough scope:** `POST /api/demo/session/reset` (`require_platform_admin`) running `purge(Session(cookie id), delete_session_row=False)` — keeps the row + cookie + expiry, defers re-seed to the next `assume-persona` (ledger now cleared); a demo-controls reset affordance in the workspace calling it.
- **Open questions / decisions for stakeholders:** placement/affordance of the reset control + its confirm interaction (it deletes the caller's leads).
- **Depends on:** Epic 9.
- **Implementation notes:** _none yet_

## Epic 12 — Graceful expiry [UI]
- **Goal:** An expired or unknown session never shows a raw 404/500 — the visitor sees a friendly "your previous demo session ended — demo data resets every 24 hours" notice with one click to a fresh session that preserves their tenant.
- **Rough scope:** Public `POST /api/demo/session` (`ensure_demo_session` with the remembered tenant) as the fresh-mint button; a `DemoSessionGate`/notice rendered when state is non-active or a deep-link lead read 404s while state is non-active (cross-checking the Epic 2 endpoint to tell "session ended" from a plain not-found); stepper progress resets with the session.
- **Open questions / decisions for stakeholders:** notice copy + visual treatment (UI/UX Guide §6.5); whether the stepper-progress reset is small enough to stay in this slice or split if it grows.
- **Depends on:** Epic 2, Epic 4.
- **Implementation notes:** _none yet_

## Epic 13 — Demo-deployment config alignment
- **Goal:** The demo deployment runs the lifecycle correctly out of the box — the `DEMO_*` knobs are set, the auth session is aligned to 24h so no surprise re-login lands inside the demo window, and the purge role's creds are wired like the other privileged roles.
- **Rough scope:** Consolidate/confirm the `DEMO_*` knobs (defaults introduced by their consuming epics), set `SESSION_LIFETIME_SECONDS=86400` for the demo env (8h stays the non-demo default), and wire `demo_purge` DB creds through SSM/Terraform alongside the existing privileged-role creds.
- **Open questions / decisions for stakeholders:** confirm the 24h auth-session alignment (TDD D9) is acceptable for the demo deployment only.
- **Depends on:** Epic 10.
- **Implementation notes:** _none yet_

## Epic 14 — Acceptance suite
- **Goal:** A named acceptance suite proves the phase contract on the real substrate — cross-session rows hidden, created lead + its event carry the session id, expiry/all/session purges delete exactly their scope across both schemas leaving the `NULL` baseline intact, instantiation is idempotent via the ledger, and `GET /api/demo/session` reports active/expired/none correctly.
- **Rough scope:** `test_demo_session_acceptance.py` (real Postgres + RabbitMQ) covering the isolation predicate, write-tagging, the three purge scopes across both tenant schemas, ledger idempotency, and session-state reporting.
- **Open questions / decisions for stakeholders:** none expected — the acceptance bar is enumerated in TDD §8.
- **Depends on:** Epics 1–12.
- **Implementation notes:** _none yet_
