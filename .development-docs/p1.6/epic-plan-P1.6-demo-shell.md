# P1.6 — Demo Shell — Epic Plan

Source TDD: [./tdd-P1.6-demo-shell.md](./tdd-P1.6-demo-shell.md)

> **Review budget:** ~150 changed lines · ~8 non-generated files · one focused commit per epic. Tunable per project. (Design-token CSS, font wiring, and step/catalog/editorial content are mostly mechanical or data and don't count toward the line budget.)

> High-level agile roadmap. Each epic's design specifics are confirmed with stakeholders at epic time (`4-plan-epic`) before any code is written.

This is the project's **first interactive frontend** phase — large but deliberately
granular, with UI isolated from backend so the `frontend-design` skill fully owns each
`[UI]` surface (the program plan sized P1.6 **L**, "split likely at epic-plan time; keep
UI-bearing epics isolated"). Epics are ordered simplest-first in three layers:

- **Access-model skeleton (Epics 1–5)** — a thin end-to-end slice proving passwordless
  demo entry and the role-switch seam *before* any chrome. Backend (1–2), frontend
  infrastructure (3–4), then the first rendered slice (5).
- **Design system + app shell (Epics 6–13)** — the Guide tokens, core components, and the
  branded, persona-aware chrome the rest of the phase renders into.
- **Demo surfaces (Epics 14–21)** — real content dropped into the seams (landing,
  tenant-select, demo home, stepper, scenario panel, explainer, Simulated badge, "How it's
  built"). A trailing backend cleanup (Epic 22) aligns the seed's brand colors to the registry.

Each epic leaves the mainline working when merged — the shell stands up incrementally and
nothing dead-links. Every `[UI]` epic folds the **Guide §7 accessibility checklist**
(contrast across paper + ink, focus order, popover focus-trap, reduced-motion, ARIA) into
its acceptance, per the TDD. The **tenant-isolation / PII invariant** holds throughout:
the role switcher changes *identity*, not enforcement; the seed password never reaches the
browser; no PII crosses the new surfaces.

## Epic 1 — Tenant list endpoint + registry brand color
- **Goal:** Stand up the public, unauthenticated `GET /api/tenants` that returns the canonical tenant list (`slug`, `display_name`, `brand_primary_color`) straight from the registry — no DB read, no PII — so the pre-login tenant-selection screen has one authoritative source.
- **Rough scope:** A new demo router under `core/app/demo/` mounted in `main.py`; add `brand_primary_color` to the registry's `TenantConfig` (the authoritative Guide-aligned primary lives here). Tests assert the public shape and that no PII/DB read is involved.
- **Open questions / decisions for stakeholders:** Confirm the registry is where the authoritative `--primary` lives (vs `tenant_settings`); the Guide-aligned *values* land here but the seed's derivation from them is Epic 22's job — settle the boundary at epic time.
- **Depends on:** none.
- **Implementation notes:** _none yet_

## Epic 2 — Passwordless assume-persona endpoint
- **Goal:** Build `POST /api/demo/assume-persona {tenant_slug, role}` — the one seam serving both first entry ("assume Agent") and every role switch. It resolves a **seeded** persona deterministically, re-mints the session as that real user, and returns the same identity body as login, so "RBAC enforced per assumed role" is literally true.
- **Rough scope:** The route in the demo router; reuse existing `auth/sessions.py` (`create_session`/`revoke_session`), the `_identity_response` shape, and the RBAC role enum; registry-validate `tenant_slug`; tie-break two Agents by lowest username; route Platform Admin to the global tenantless user. Revoke + audit any prior session, mint + cookie + audit the new one. Add the `demo_login_enabled` config flag (default on). Tests: correct persona per role, 404 unknown tenant, 422 bad role, re-mint replaces prior session, capabilities match the role, audit events recorded.
- **Open questions / decisions for stakeholders:** Confirm the audit routing on a role switch (logout audited under the old tenant, login under the new) and the two-Agent tie-break rule read as intended — both are specified in the TDD; settle any naming at epic time. This is an auth-path endpoint kept whole as one coherent flow (correctness-critical) — confirm that's acceptable vs splitting mint/revoke.
- **Depends on:** none (builds on existing P1.1–P1.5 auth, sessions, registry, seed).
- **Implementation notes:** _none yet_

## Epic 3 — Frontend API client + shared types
- **Goal:** A thin, typed `fetch` wrapper (`credentials: "include"` so the `pf_session` cookie rides every call) exposing `getCurrentIdentity`, `listTenants`, `assumePersona`, `signOut`, with shared types (`Identity`, `Role`, `Capability`, `Tenant`) — the single client every later frontend epic calls.
- **Rough scope:** A new `frontend/src/api/` module: the wrapper, the four typed calls, the shared type definitions, and typed error handling. Vitest unit tests mock fetch (jsdom has no backend).
- **Open questions / decisions for stakeholders:** Confirm the typed-error shape (how a non-2xx / network failure surfaces to callers) so contexts and surfaces handle it consistently — minor; otherwise none expected.
- **Depends on:** Epic 1, Epic 2 (the endpoints it wraps).
- **Implementation notes:** _none yet_

## Epic 4 — Session context + capability helper
- **Goal:** A `SessionProvider` React context that restores identity via `/me` on mount (loading → signed-in → signed-out), exposes `identity`, `capabilities`, `assumePersona`, `signOut`, and a `useCapability(cap)` helper that reads the server-returned matrix — the shared session state every authed surface consumes.
- **Rough scope:** A new context module under `frontend/src/` wrapping the Epic 3 client; the load/refresh lifecycle and the capability helper. Tests cover the three states and that `assumePersona`/`signOut` refresh identity. (No rendered surface — infrastructure.)
- **Open questions / decisions for stakeholders:** Confirm the signed-out vs error distinction (a clean "not signed in" vs a failed `/me`) — affects how the guard in Epic 5 redirects; settle at epic time.
- **Depends on:** Epic 3.
- **Implementation notes:** _none yet_

## Epic 5 — Guarded /app + thin end-to-end slice [UI]
- **Goal:** Prove the whole access model end-to-end in the browser: a public/`/app` routing split behind a `RequireSession` guard (skeleton while `/me` resolves, redirect to `/` when signed-out), a thin select-tenant that lists `/api/tenants` and on click assumes Agent, and an `/app` that shows "signed in as <role> · <tenant>" from `/me`.
- **Rough scope:** The routing split in `App.tsx`, the `RequireSession` guard, a minimal (un-branded) select-tenant and demo-home using existing base styles. Tests: select → assume → demo home; guard redirects a signed-out visitor from `/app`.
- **Open questions / decisions for stakeholders:** none expected — this is the walking skeleton; branding and real content arrive in later epics.
- **Depends on:** Epic 3, Epic 4.
- **Implementation notes:** _none yet_

## Epic 6 — Design tokens + IBM Plex Mono [UI]
- **Goal:** Build out the Guide token layer the rest of the phase needs: tenant brand **ramps** as `[data-tenant]` blocks, **persona accent** tokens as `[data-persona]` blocks plus the Platform-Admin brand-drain, the state colors + containers, the ink-console tokens, and the missing elevation / z-index / radius / motion / row-height values. Load IBM Plex Mono.
- **Rough scope:** `styles/tokens.css` additions keyed by slug/persona (authoritative `--primary` comes from the backend; supporting ramp tokens are frontend design data per the Guide); the font in `index.html`. Mostly additive CSS values.
- **Open questions / decisions for stakeholders:** **Which ink-console token subset to land now vs defer** (a TDD §7 open question) — settle the minimum needed by the "How it's built" diagram (Epic 21) without front-loading the full console system.
- **Depends on:** none (foundational; sequenced after the skeleton).
- **Implementation notes:** _none yet_

## Epic 7 — Button variants [UI]
- **Goal:** A `Button` component covering the Guide's Filled / Tonal / Outlined / Text variants with proper focus ring and a unique `id` per element, replacing the existing ad-hoc `.button-tonal`.
- **Rough scope:** The component under `frontend/src/components/`, plus refactoring current `.button-tonal` usages onto it. Tests cover the variants and disabled/focus states.
- **Open questions / decisions for stakeholders:** Confirm the variant-name mapping to the Guide and that every existing button usage migrates now (vs incrementally) — settle at epic time.
- **Depends on:** Epic 6.
- **Implementation notes:** _none yet_

## Epic 8 — Card + StampTag [UI]
- **Goal:** Two small presentational primitives — `Card` (the Guide container) and `StampTag` (status + overline stamp) — that later surfaces (tenant cards, nav markers, "How it's built" cards, the Simulated badge) build on.
- **Rough scope:** Both components under `frontend/src/components/`, each with a unique `id` and ARIA where relevant. Tests cover the StampTag status/overline variants.
- **Open questions / decisions for stakeholders:** Confirm the StampTag status set needed now (which states render in P1.6 vs arrive with feature phases) — settle at epic time.
- **Depends on:** Epic 6.
- **Implementation notes:** _none yet_

## Epic 9 — Popover / MarginNote primitive [UI]
- **Goal:** The anchored, focus-trapped, Esc-closes popover primitive that is the shared substrate for both the explainer and the Simulated-badge popovers later — built once, correctly, with full keyboard a11y.
- **Rough scope:** A `Popover`/`MarginNote` component under `frontend/src/components/`: anchoring, focus trap, Esc + outside-click close, ARIA wiring. Hand-rolled (no new deps, per TDD Decision 6). Tests: open/close/Esc + focus trap.
- **Open questions / decisions for stakeholders:** Confirm hand-rolled focus-trap is acceptable vs a tiny dependency (the TDD says no new deps) — this is fiddly, correctness-critical interaction code; confirm the keyboard contract at epic time.
- **Depends on:** Epic 6.
- **Implementation notes:** _none yet_

## Epic 10 — App-shell masthead + theming wiring [UI]
- **Goal:** The branded app-shell masthead — wordmark + tenant seal mark + 3px letterhead rule + persona indicator + placeholder session indicator + notification-bell placeholder + "How it's built" link — plus the data-attribute theming effect that sets `data-tenant`/`data-persona` on the app root from the current identity, so the Guide's declarative theming (including Platform-Admin inversion) takes over.
- **Rough scope:** The masthead component(s) under the shell, and the small identity→data-attribute effect. Renders within the guarded `/app` zone. Tests cover the theming attributes and the placeholder affordances.
- **Open questions / decisions for stakeholders:** Confirm the tenant seal-mark asset/source and the placeholder session-indicator copy (P1.8 owns the live countdown). Settle masthead layout specifics against the Guide at epic time.
- **Depends on:** Epic 5, Epic 6, Epic 7.
- **Implementation notes:** _none yet_

## Epic 11 — Role switcher [UI]
- **Goal:** The four personas as annotated chips (accent + glyph) in the masthead; selecting one calls `assumePersona`, animates the accent (~200ms), and re-identifies — Platform Admin inverts the masthead and drains tenant brand ("PLATFORM OPERATIONS — OUTSIDE TENANT SCOPE"). RBAC is enforced because the visitor now *is* that seeded user.
- **Rough scope:** The switcher component in the masthead, wired to the session context's `assumePersona`. Tests: switching re-themes (`data-persona`, Platform-Admin inversion) and re-identifies.
- **Open questions / decisions for stakeholders:** Confirm the persona glyph set and the exact Platform-Admin inversion copy against the Guide — settle at epic time.
- **Depends on:** Epic 4, Epic 10.
- **Implementation notes:** _none yet_

## Epic 12 — Left nav [UI]
- **Goal:** The role-conditional left navigation with an active marker and future sections shown as **disabled / "coming in a later step"** — previewing the app's structure honestly without dead links.
- **Rough scope:** The nav component in the shell, reading role/capabilities from the session context; future items rendered inert. Tests: role-conditional sections render and future items are disabled.
- **Open questions / decisions for stakeholders:** Confirm which sections to preview and their "coming later" labels (which feature phase each points at) — settle at epic time.
- **Depends on:** Epic 10.
- **Implementation notes:** _none yet_

## Epic 13 — Read-Only "VIEW ONLY" lock tag [UI]
- **Goal:** The persistent "VIEW ONLY" lock tag shown on every screen while the Read-Only persona is active (Guide §2.4) — a constant, unmistakable signal of the persona's posture.
- **Rough scope:** A small persona-conditional chrome element keyed off `data-persona`/identity, placed so it persists across surfaces. Tests: the tag shows for Read-Only and not for other personas.
- **Open questions / decisions for stakeholders:** Confirm placement and whether any persona besides Read-Only carries a persistent posture tag — settle at epic time.
- **Depends on:** Epic 10.
- **Implementation notes:** _none yet_

## Epic 14 — Landing page + global footer [UI]
- **Goal:** Replace the placeholder landing with real editorial orientation (Guide §6.13): what PolicyFlow is and why, "simulated & safe to click," the time commitment, and one CTA into tenant selection — plus the global footer (repo + author links) shown on every page.
- **Rough scope:** The landing page and a shared footer component, using the Epic 7 Button for the CTA. Public route. Tests cover the CTA route and footer presence.
- **Open questions / decisions for stakeholders:** Final orientation **copy** (Guide §6.13) is settled at epic time — confirm tone/length and the exact repo/author links.
- **Depends on:** Epic 6, Epic 7.
- **Implementation notes:** _none yet_

## Epic 15 — Select-tenant page (branded) [UI]
- **Goal:** Upgrade the thin select-tenant slice into the real branded screen: per-tenant cards with specialization blurbs and the "why two tenants" (differentiation + isolation proof), each visibly branded; selecting a tenant assumes Agent and routes to `/app`.
- **Rough scope:** The branded cards (Epic 8 `Card`) fed by `listTenants()`, with frontend editorial blurbs keyed by slug and a slot for the explainer (seeded in Epic 19). Tests: branded render + select → assume → `/app`.
- **Open questions / decisions for stakeholders:** The specialization blurbs and why-two-tenants **copy** (frontend editorial, keyed by slug) — confirm at epic time.
- **Depends on:** Epic 5, Epic 8.
- **Implementation notes:** _none yet_

## Epic 16 — Demo home host [UI]
- **Goal:** Turn the placeholder `/app` into the real "demo home" — in-app orientation hosting the active guided stepper, inside the real shell chrome — the landing pad after tenant pick.
- **Rough scope:** The demo-home surface within the guarded `/app` zone, providing orientation content and the host/slot the stepper mounts into. Tests cover the orientation render within the shell.
- **Open questions / decisions for stakeholders:** Confirm the in-app orientation **copy** and how it relates to the landing orientation (avoid duplication) — settle at epic time.
- **Depends on:** Epic 5, Epic 10.
- **Implementation notes:** _none yet_

## Epic 17 — Guided stepper docket [UI]
- **Goal:** The dismissible 21-step guided docket with per-step "what you're seeing / how it's built" notes and deep links; links whose destinations don't exist yet render **inert / "available in a later step."** Progress is in-memory (durable, session-aware persistence is P1.8).
- **Rough scope:** The docket component (dismiss, step navigation, in-memory progress, inert deep-link handling) plus seeding the 21 steps' notes/links. Mounts into the Epic 16 host. Tests cover dismiss, progress, and inert links.
- **Open questions / decisions for stakeholders:** The 21-step **content** is settled at epic time. **Whether to split the docket component from the 21-step content catalog** into two epics if the combined size runs materially over budget — decide at `4-plan-epic` once the real size is known.
- **Depends on:** Epic 16.
- **Implementation notes:** _none yet_

## Epic 18 — Scenario-reference panel [UI]
- **Goal:** The scenario-reference catalog (Guide §6.9) — every magic input / Platform-Admin demo control / demo time control with its trigger + expected outcome, each marked with the phase/step where it becomes live — reachable from the stepper and a help icon.
- **Rough scope:** The panel surface and its catalog entries (StampTag markers for "live in phase/step"), with entry points from the stepper and a help affordance. Tests cover the catalog render and the "live in" markers.
- **Open questions / decisions for stakeholders:** The exact catalog entries to list now and how each is marked (the four prefill **buttons** land on the intake form in P1.7) — confirm the entry set at epic time.
- **Depends on:** Epic 8, Epic 17.
- **Implementation notes:** _none yet_

## Epic 19 — Explainer affordance [UI]
- **Goal:** The `ExplainerIcon` + `ExplainerPopover` (PATTERN / HOW POLICYFLOW DOES IT / REAL VS SIMULATED / CRM PARALLEL), seeded with **real foundational copy** on the surfaces that already exist — landing, tenant-switch, role switcher, and the session model.
- **Rough scope:** The icon + popover (built on the Epic 9 primitive) and seeding it on the four named surfaces with real copy. Tests: popover open/close/Esc + focus trap, and that seeded affordances render on their surfaces.
- **Open questions / decisions for stakeholders:** The real foundational **copy** per surface and confirmation of the four popover sections — settle at epic time.
- **Depends on:** Epic 9; seeds onto Epics 10, 11, 14, 15.
- **Implementation notes:** _none yet_

## Epic 20 — "Simulated" badge component [UI]
- **Goal:** The reusable "Simulated" badge — the dashed-border stamp plus an "official notice" popover (WHAT IS MOCKED / WHAT IS REAL / THE ADAPTER SEAM) — shipped with one representative usage, so every later phase can mark a simulated surface consistently.
- **Rough scope:** The badge component (Epic 8 StampTag styling + Epic 9 popover) and a representative usage (the "How it's built" real-vs-simulated legend is the natural home). Tests cover the badge + popover.
- **Open questions / decisions for stakeholders:** Confirm the representative usage location and the official-notice **copy** — settle at epic time.
- **Depends on:** Epic 8, Epic 9.
- **Implementation notes:** _none yet_

## Epic 21 — "How it's built" page shell [UI]
- **Goal:** The public "How it's built" page: the showcase-pattern index seeded as deep-link cards for the **real P1.1–P1.5 patterns** (auth/RBAC, schema-per-tenant isolation, envelope encryption + blind index, append-only audit, transactional outbox + event bus), the project motivation, an annotated architecture-diagram placeholder (ink console) with a real-vs-simulated legend, and author + repo links. Content grows per phase.
- **Rough scope:** The public page (Epic 8 Card for the pattern index, Epic 20 Simulated badge in the legend, ink tokens from Epic 6). Tests cover the pattern-index render and links.
- **Open questions / decisions for stakeholders:** The architecture-diagram (ink-console) scope — tied to the Epic 6 ink-token open question — and the five pattern cards' **copy**; settle the minimum diagram now vs deferred at epic time.
- **Depends on:** Epic 6, Epic 8, Epic 20.
- **Implementation notes:** _none yet_

## Epic 22 — Brand-color alignment (seed ← registry)
- **Goal:** Align the seed's brand colors to the Guide via a single source: the seed derives each tenant's `brand_primary_color` from the registry (Sunshine `#9C4A1E`, Florida `#0F6A72`, Guide §2.3) instead of its hardcoded placeholders, so `/api/tenants` and the seed never diverge.
- **Rough scope:** `app/seed.py` reads the brand primary from the registry rather than its own constants; confirm the registry holds the Guide-aligned values (added in Epic 1). No migration — applied on the next seed / DB-reset. Tests assert the seed-vs-registry consistency.
- **Open questions / decisions for stakeholders:** none expected — the values and the single-source approach are fixed by TDD Decision 8.
- **Depends on:** Epic 1.
- **Implementation notes:** _none yet_
