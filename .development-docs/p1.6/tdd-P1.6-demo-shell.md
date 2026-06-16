# P1.6 — Demo Shell — Technical Design Document

> Phase **P1.6** of the [Program & Phase Plan](../program-and-phase-plan.md#p16--demo-shell-ui).
> One phase = one TDD = one epic plan. Behavior spec:
> [PolicyFlow_Requirements.md](../PolicyFlow_Requirements.md); design source of truth:
> [UI_UX_Guide.md](../UI_UX_Guide.md). This TDD decides **how**, not **what**.

## 1. Summary

P1.6 turns the static P0.1 placeholder SPA into a **real, signed-in demo experience**.
A cold visitor lands on an orientation page, picks one of the two seeded tenants, is
**auto-signed-in as that tenant's seeded Agent without typing credentials**, sees
tenant-branded chrome, and can **flip personas** (Agent / Tenant Admin / Read-Only /
Platform Admin) with RBAC still enforced server-side per assumed role. Alongside the
access model, this phase stands up the **shells** for the self-explaining-demo surfaces
— the guided stepper, the explainer popover, the "Simulated" badge, the
scenario-reference panel, and the "How it's built" page — so every later phase drops
content into seams that already exist. The backend work is small (two endpoints, no new
tables); the bulk is the first interactive frontend: an API client, identity/brand/persona
React contexts, an authed-vs-public routing split, and the build-out of the Guide's core
component library on the existing token CSS.

## 2. Business Requirements

Lifted from [Requirements §Demo Experience](../PolicyFlow_Requirements.md) (Landing &
Orientation, Demo Access Model, Engineering Explainers, Guided Demo) and the
[Phase Plan P1.6 entry](../program-and-phase-plan.md#p16--demo-shell-ui):

- **Landing & orientation** before tenant selection: what PolicyFlow is, why it was
  built, that everything is simulated and safe to click, the time commitment, and one CTA
  into tenant selection.
- **Tenant selection** describing each tenant's specialization and why two tenants exist
  (the differentiation + isolation proof), each visibly branded.
- **Demo access model:** selecting a tenant auto-creates a session signed in as a seeded
  **Agent** — no credentials typed.
- **Role switcher:** flip between Agent, Tenant Admin, Read-Only, Platform Admin within
  the session; RBAC stays fully server-enforced per assumed role (the switcher changes
  identity, not enforcement).
- **Demo-surface shells, content per phase:** guided-stepper docket, explainer affordance,
  "Simulated" badge component, scenario-reference panel, and the "How it's built" page —
  shells in P1.6; copy/CRM-parallel/showcase-index entries delivered with each phase's
  slice. P1.6 seeds the **already-real** P1.1–P1.5 foundational patterns.
- **Visible tenant differentiation** on the same chrome: brand color, masthead wordmark +
  seal, the 3px letterhead rule (product lines / stage labels / mappings arrive with their
  feature phases).
- **Tenant isolation invariant** (project cross-cutting axis): identity changes, not
  enforcement; no PII crosses the new surfaces; the seed password never reaches the browser.

## 3. Goals / Non-Goals

**Goals**

- A visitor can land → read orientation → pick a tenant → be signed in as that tenant's
  seeded Agent → switch personas, all in the browser on the local stack.
- Tenant-branded + persona-aware app shell (masthead, theming, role switcher, nav).
- Rendering shells for stepper, explainer, Simulated badge, scenario panel, and
  "How it's built," the last seeded with real P1.1–P1.5 patterns.
- Establish the frontend foundations later phases inherit: API client, contexts, routing
  guard, and the Guide's core component library.

**Non-Goals** (owning phase named)

- Demo-session **sandboxing & lifecycle** — `demo_session_id` tagging, 24h purge, nightly
  reset, the live countdown indicator, graceful expired-session handling → **P1.8**.
  (P1.6's masthead carries a static placeholder session indicator.)
- **Feature pages** — leads, intake form + prefill **buttons**, queue, contacts,
  households, opportunities, policies, dashboards → **P1.7 / P2 / P4**.
- **Per-record event timeline & correlation trace** → **P1.9 / P2.5**.
- **Notification center / outbox, CRM viewer, DLQ list** → **M3 / M4**.
- Real explainer/CRM-parallel/showcase **copy for not-yet-built surfaces** (ships per slice).
- Tenant Admin config-**editing** UIs (stretch); the role switcher's persona set is the
  fixed seeded matrix.

## 4. Current State

- **Frontend** ([frontend/src](../../frontend/src)) is a static P0.1 placeholder: React
  18.3 SPA + `react-router-dom` 6, two pages ([LandingPage](../../frontend/src/pages/LandingPage.tsx),
  [SelectTenantPage](../../frontend/src/pages/SelectTenantPage.tsx)) wrapped by a shared
  [PageLayout](../../frontend/src/components/PageLayout.tsx). **No API client, no state,
  no auth, no tenant theming, no app shell.** Styles are a light subset of the Guide
  ([tokens.css](../../frontend/src/styles/tokens.css), [pages.css](../../frontend/src/styles/pages.css))
  — surfaces, outline, text, fonts, spacing, radius, motion, focus ring only. **No** tenant
  brand ramps, persona tokens, state colors, or ink-console tokens. Fonts loaded: Besley
  600, Public Sans 400/500/600 — **no IBM Plex Mono** yet ([index.html](../../frontend/index.html)).
  Vitest + Testing Library configured ([App.test.tsx](../../frontend/src/App.test.tsx)).
- **Backend auth** ([core/app/auth](../../core/app/auth)) is complete through P1.5:
  `POST /api/auth/login` (username **+ password** → `pf_session` httponly cookie),
  `/logout`, `/me`. Login/`me` return `{user:{id,username,role,tenant_id}, capabilities:[…]}`
  via [`_identity_response`](../../core/app/auth/router.py). Sessions are opaque tokens,
  SHA-256-hashed in `platform.auth_sessions`, 8h default lifetime
  ([sessions.py](../../core/app/auth/sessions.py)); `create_session`/`revoke_session` are
  reusable. RBAC matrix + `require_capability`/`require_platform_admin`
  ([rbac.py](../../core/app/auth/rbac.py), [dependencies.py](../../core/app/auth/dependencies.py)).
- **Seed** ([seed.py](../../core/app/seed.py)) creates 2 tenants and 9 personas: per tenant
  `agent.one`, `agent.two`, `admin`, `readonly` (emails `@sunshine.example` /
  `@florida.example`) + 1 global tenantless `platform.admin@policyflow.example`; all share
  `settings.seed_user_password`. Per-tenant `tenant_settings` hold `brand_primary_color`,
  `brand_logo_url`, `welcome_message` (current colors `#F5A623` / `#2E86C1` — **to be
  aligned to the Guide**).
- **Tenant registry** ([registry.py](../../core/app/tenancy/registry.py)) is the single
  source of truth for which tenants exist (`slug`, `display_name`, `schema_name`,
  `db_role`, `email_domain`). Example guarded reads:
  [tenant/router.py](../../core/app/tenant/router.py),
  [platform/router.py](../../core/app/platform/router.py). App mounts routers in
  [main.py](../../core/app/main.py). nginx proxies `/api/` → `core:8000`
  ([nginx.conf](../../frontend/nginx.conf)); **dev is the local docker stack**.

## 5. Proposed Design

> **Diagram:** [demo entry & role-switch flow](diagrams/tdd-P1.6-demo-flow.png)
> (`diagrams/tdd-P1.6-demo-flow.excalidraw`) — the one endpoint serving both first entry
> and every role switch, persona resolution + session re-mint, and the data-attribute
> theming branch (tenant-scoped vs Platform Admin).

### 5.1 Backend — two small, no-table-change endpoints

A new router `app/demo/router.py`, mounted in [main.py](../../core/app/main.py):

**`GET /api/tenants`** — public, unauthenticated. Returns the canonical tenant list from
the **registry** (no DB read, no PII): `{"tenants": [{"slug", "display_name",
"brand_primary_color"}, …]}`. `brand_primary_color` is added to `TenantConfig` (registry),
aligned to the Guide §2.3 `--primary`, so the registry is the single source for the
authoritative primary that both this endpoint and the seed derive from. The pre-login
tenant-selection screen calls this.

**`POST /api/demo/assume-persona`** — the passwordless demo front door **and** the role
switcher, one seam. Body `{"tenant_slug": str, "role": Role}`:

1. Validate `role` (Pydantic enum) and, for tenant-scoped roles, `tenant_slug` against the
   registry (unknown → 404).
2. Resolve the **seeded persona deterministically**: a tenant-scoped role → the seeded
   `User` with `(tenant_id, role)`, breaking the two-Agent tie by lowest username
   (`agent.one`); `platform_admin` → the single tenantless `User` with
   `role = PLATFORM_ADMIN` (tenant_slug ignored — Platform Admin is outside tenant scope).
   It only ever resolves **seeded personas**; an arbitrary username can never be assumed.
3. If the caller already holds a `pf_session`, resolve its identity, `revoke_session`, and
   audit `auth.logout`/success for it (a real identity change).
4. `create_session` for the resolved persona, set the `pf_session` cookie, audit
   `auth.login`/success routed by the persona's `tenant_id`, and return the **same identity
   body** as login (`_identity_response` reused).

Because each persona is a **distinct seeded user**, "RBAC enforced per assumed role" is
literally true — the visitor *is* that user; no second "assumed-role" concept exists. A
config flag `demo_login_enabled` (default **on**) is the seam to disable the front door in
a hypothetical non-demo deployment; the demo app keeps it on.

No migration is required by P1.6 logic. The only seed/registry change is the **brand-color
alignment** (§6 Decision 8): move the authoritative `brand_primary_color` into the
registry, align it to the Guide, and have the seed derive it from there. Existing
`tenant_settings` rows are not load-bearing for the masthead (the ramp is frontend-owned),
so a fresh seed / DB-reset picks up the aligned value with no online migration.

### 5.2 Frontend — architecture

- **API client** (`src/api/`): a thin `fetch` wrapper, `credentials: "include"` (so the
  `pf_session` cookie rides every call), JSON in/out, typed errors. Typed calls:
  `getCurrentIdentity()` (`GET /api/auth/me`), `listTenants()`, `assumePersona(slug, role)`,
  `signOut()`. Shared types (`Identity`, `Role`, `Capability`, `Tenant`).
- **Contexts** (React Context = built-in shared state, no new deps):
  - **SessionProvider** — restores identity via `/me` on mount (loading → signed-in →
    signed-out), exposes `identity`, `capabilities`, `assumePersona`, `signOut`. A
    `useCapability(cap)` helper reads the matrix the server already returns.
  - **Theming is data-attribute-driven, not a context value**: a small effect sets
    `data-tenant="<slug>"` and `data-persona="<role>"` on the app root from the current
    identity. The CSS does the rest (§5.3) — including the Platform-Admin brand-drain and
    masthead inversion the Guide §2.4 already specifies declaratively.
- **Routing** ([App.tsx](../../frontend/src/App.tsx)): **public** routes `/`,
  `/select-tenant`, `/how-its-built`; a **guarded `/app/*` zone** behind a `RequireSession`
  guard that shows a skeleton while `/me` resolves and redirects to `/` when signed-out.
  Tenant-pick lands on **`/app`** — a placeholder **"demo home"** hosting in-app orientation
  + the active stepper inside the real shell chrome (feature pages arrive P1.7+).
- **State approach:** React Context + the fetch wrapper — **no new dependencies**. (TanStack
  Query is deferred to P1.7, when real list/detail data justifies a server-state cache.)

### 5.3 Frontend — design tokens & component library

- **Token CSS build-out** ([styles/tokens.css](../../frontend/src/styles/tokens.css)):
  add the Guide tokens P1.6 surfaces need — tenant brand **ramps** as `[data-tenant="…"]`
  blocks (`--primary`, `--on-primary`, `--primary-container`, `--on-primary-container`),
  **persona accent** tokens as `[data-persona="…"]` blocks plus the Platform-Admin
  brand-drain override (§2.4), the **state** colors + containers (§2.2), ink-console tokens
  (§2.1, for the "How it's built" diagram and future consoles), and the missing
  elevation / z-index / `radius-lg`,`radius-full` / `motion-fast`,`motion-slow` / row-height
  values. The **authoritative `--primary` per tenant comes from the backend
  (`/api/tenants`)**; the **supporting ramp tokens are frontend design data keyed by slug**,
  per the Guide (Decision 4). Add **IBM Plex Mono** to [index.html](../../frontend/index.html).
- **Core components** (Guide §5) — build only what P1.6 surfaces use, each with a unique
  `id` per [CLAUDE.md](../../.claude/CLAUDE.md) and proper ARIA: **Button** (Filled/Tonal/
  Outlined/Text — refactor the existing `.button-tonal`), **Card**, **StampTag** (status +
  overline), **Popover/MarginNote** (focus-trapped, Esc-closes, anchored — the substrate for
  both the explainer and the Simulated-badge popovers). The **Dialog** is deferred until a
  surface needs it (PII-reveal confirm, conversion — later phases).

### 5.4 Frontend — surfaces (the demo shell)

- **Landing** — real editorial content (Guide §6.13): orientation, "simulated & safe,"
  time commitment, single CTA. Footer with repo + author links (global, every page).
- **Select-tenant** — fetch `/api/tenants`, render branded cards with specialization blurbs
  + why-two-tenants (blurbs are frontend editorial copy keyed by slug); select →
  `assumePersona(slug, "agent")` → `/app`.
- **App shell** — **Masthead** (wordmark + tenant seal mark + 3px letterhead rule +
  persona indicator + role switcher + **placeholder** session indicator + notification-bell
  placeholder + "How it's built" link); **LeftNav** (role-conditional sections with future
  items **disabled / "coming in a later step,"** active marker); the Read-Only persona's
  persistent **"VIEW ONLY"** lock tag (§2.4).
- **Role switcher** (§6.7) — the four personas as annotated chips (accent + glyph, §2.4);
  selecting one calls `assumePersona` and animates the accent (200ms); Platform Admin
  inverts the masthead and drains tenant brand ("PLATFORM OPERATIONS — OUTSIDE TENANT SCOPE").
- **Guided stepper** (§6.6) — the dismissible 21-step docket with per-step "what you're
  seeing / how it's built" notes and deep links; links whose destinations don't exist yet
  render **inert / "available in a later step."** Progress is **in-memory** (durable,
  session-aware persistence → P1.8).
- **Scenario-reference panel** (§6.9 catalog) — reachable from the stepper and a help icon;
  lists every magic input / Platform-Admin demo control / demo time control with its trigger
  + expected outcome, each marked with the phase/step where it becomes live. (The four
  prefill **buttons** themselves land on the intake form in **P1.7**.)
- **Explainer affordance** (§6.2) — `ExplainerIcon` + `ExplainerPopover` (PATTERN / HOW
  POLICYFLOW DOES IT / REAL VS SIMULATED / CRM PARALLEL), seeded on the surfaces that exist
  now (landing, tenant switch, role switcher, session model) with **real** foundational copy.
- **"Simulated" badge** (§6.3) — the dashed-border stamp + "official notice" popover
  (WHAT IS MOCKED / WHAT IS REAL / THE ADAPTER SEAM), shipped as a reusable component with a
  representative usage (the "How it's built" diagram's real-vs-simulated legend).
- **"How it's built"** (§6.13) — public page shell: the showcase-pattern index seeded as
  deep-link cards for the **real P1.1–P1.5 patterns** (auth/RBAC, schema-per-tenant
  isolation, envelope encryption + blind index, append-only audit, transactional outbox +
  event bus), the project motivation, an annotated architecture diagram placeholder (ink
  console) with a real-vs-simulated legend, and author + repo links. Content grows per phase.

### 5.5 Primary flows

**Tenant entry:** Landing → CTA → Select-tenant (`GET /api/tenants`) → click a tenant →
`POST /api/demo/assume-persona {slug, "agent"}` → server resolves `agent.one`, mints
`pf_session`, audits `auth.login` → SPA reads `/me`, sets `data-tenant`/`data-persona`,
routes to `/app` with the branded shell + active stepper.

**Role switch:** Role switcher → pick persona → `POST /api/demo/assume-persona {currentSlug,
role}` → server revokes the old session (audits `auth.logout`), mints a session for the
target seeded persona (audits `auth.login`) → SPA refreshes identity, re-themes
(`data-persona`, Platform-Admin inversion), animates the accent. RBAC is enforced because
the visitor now *is* that seeded user.

## 6. Decisions

1. **Demo session = auth-session-as-seeded-persona in P1.6.** *Chosen:* a real server-side
   login as a seeded persona; lifecycle (tagging, purge, countdown, expiry) deferred to
   P1.8; masthead shows a placeholder indicator. *Alternatives:* build session lifecycle
   now (rejected — couples P1.6 to P1.8's purge/expiry semantics). *Rationale:* matches the
   phase boundary; keeps the shell a clean seam.

2. **Passwordless demo login + role switch via one `POST /api/demo/assume-persona`.**
   *Chosen:* a single endpoint taking `{tenant_slug, role}`; tenant-pick is "assume Agent."
   *Alternatives:* two named endpoints (more seams/tests for near-identical work); extend
   `/api/auth/login` with a demo mode (pollutes the production auth seam). *Rationale:* one
   seam, one test surface; the seed password never leaves the server.

3. **Role switch re-mints the session as the real seeded user.** *Chosen:* revoke the old
   session, mint a new one as the distinct seeded persona. *Alternatives:* one session + a
   server-tracked "assumed role" (a second identity concept that can drift from the seeded
   users). *Rationale:* "changes identity, not enforcement" becomes literally true; RBAC is
   enforced for free because you *are* that user.

4. **Brand ramp is frontend design data keyed by slug; backend owns the primary.**
   *Chosen:* `/api/tenants` (from the registry) supplies the authoritative `--primary`; the
   frontend supplies the supporting ramp tokens per slug via `[data-tenant]` CSS.
   *Alternatives:* widen `tenant_settings` to the full ramp (a migration + DB-baked design
   values for two fixed tenants). *Rationale:* the Guide stays the single source for the
   ramp; no migration; honors the "seed supplies the brand, app sets the tokens" model.

5. **Public `GET /api/tenants` for the pre-login screen, served from the registry.**
   *Chosen:* an unauthenticated endpoint returning `slug`, `display_name`,
   `brand_primary_color` (no PII, no DB read). *Alternatives:* hardcode the tenants in the
   SPA (drifts from the seed/registry). *Rationale:* one authoritative source the demo-login
   also validates against; trivially safe.

6. **React Context + a fetch wrapper; no new dependencies.** *Chosen:* contexts + thin
   client for P1.6's few calls. *Alternatives:* TanStack Query now (overkill before there's
   list/detail data). *Rationale:* fits the surface; adopt a server-state cache in P1.7.

7. **Public routes + a guarded `/app` zone; tenant-pick lands on a placeholder demo home.**
   *Chosen:* `/`, `/select-tenant`, `/how-its-built` public; `/app/*` behind a session
   guard. *Alternatives:* flat conditional rendering (messy as nav/feature pages grow).
   *Rationale:* clean separation that scales into P1.7+.

8. **Align brand colors to the Guide, sourced from the registry.** *Chosen:* Sunshine
   `#9C4A1E`, Florida `#0F6A72` (Guide §2.3) held in the registry, derived by the seed.
   *Alternatives:* keep the P1.2 placeholder colors (violate the Guide's AA + hue-distance
   law). *Rationale:* the Guide is the design source of truth; a single registry source feeds
   both `/api/tenants` and the seed.

9. **Stepper progress is in-memory in P1.6.** *Chosen:* ephemeral React state.
   *Alternatives:* `localStorage` now (the "reset with the session, never point at purged
   records" semantics belong to P1.8 → likely rework). *Rationale:* defer persistence to the
   phase that owns session lifecycle.

10. **Seed the "How it's built" page + explainers with the real P1.1–P1.5 patterns.**
    *Chosen:* index the foundational patterns that genuinely exist. *Alternatives:* empty
    shells (forgoes the engineering-transparency payoff that's already earned).
    *Rationale:* the patterns are real and demonstrable today.

11. **Left-nav renders with future sections disabled.** *Chosen:* show the eventual sections
    as "coming in a later step." *Alternatives:* omit the nav (the shell reads as less of a
    real app) or fully build it (destinations don't exist). *Rationale:* previews structure
    honestly without dead links.

12. **Build only the components P1.6 surfaces use.** *Chosen:* Button, Card, StampTag,
    Popover/MarginNote, plus the shell pieces; defer Dialog and others to first need.
    *Rationale:* keeps a large UI phase from sprawling; later phases add components behind
    the same tokens.

## 7. Risks and Open Questions

- **Passwordless front door is intentional and public.** *Mitigation:* it resolves **only
  seeded personas** over the fixed role enum on **synthetic** data; tenant_slug is
  registry-validated; `demo_login_enabled` is the off-switch. No real credential path is
  weakened (the production `AuthProvider` seam is untouched).
- **Large UI phase.** P1.6 is `L` ("split likely at epic-plan time"). *Mitigation:* the §9
  breakdown is granular and simplest-first; `3-tdd-to-epic-plan` isolates `[UI]` epics; use
  `split-epic` for any epic materially over the review budget.
- **Brand-color alignment vs idempotent seed.** Existing `tenant_settings` rows won't update
  on a re-seed (insert-if-absent), but the masthead brand is frontend-owned, so stale rows
  don't affect P1.6 visuals; a fresh seed / DB-reset picks up the aligned registry value.
- **Standalone `vite` dev lacks the `/api` proxy** (dev is the docker stack, where nginx
  proxies). *Mitigation:* document "run the stack"; optionally add a `vite` `server.proxy`
  for DX (not required). Component tests mock the API client (jsdom has no real backend).
- **Accessibility (Guide §7) across paper + ink, persona chrome, and popovers.**
  *Mitigation:* fold the §7 QA checklist into each UI epic's acceptance.
- **Open:** exact ink-console token subset needed now vs deferred — settle per the
  "How it's built" diagram epic (don't front-load the full console system).

## 8. Rollout / Verification

- **No online migration.** The only data change is the registry/seed **brand-color
  alignment**, applied on the next seed/DB-reset (deploys may re-seed canonical state, per
  Requirements §Deployment).
- **Backwards compatibility:** `/api/auth/*` is unchanged; the demo endpoints are additive.
  The frontend gains routes and chrome; the public placeholders are replaced by real content.
- **Manual verification (local stack):** Walkthrough steps **1–2** (land → orientation →
  pick tenant → signed in as Agent), the role-switch beat of step **17** (flip to Read-Only:
  masking-free chrome shows the VIEW ONLY lock; flip to Platform Admin: masthead inverts),
  the chrome half of step **18** (the two tenants differ on the same masthead), and step
  **21** (the "How it's built" shell with the real-pattern index). Confirm the seed password
  never appears in any network payload.
- **Automated (build-loop targeted runs; full suites at commit via pre-commit):**
  - **pytest** (`core/`, via `./.venv/Scripts/python.exe -m pytest`): `/api/tenants` public
    shape; `assume-persona` mints a session as the correct seeded persona (Agent→`agent.one`,
    Platform Admin→global), 404 on unknown tenant, 422 on bad role, re-mint replaces a prior
    session, the resulting identity's capabilities match the role, audit events recorded.
  - **vitest** (`frontend/`): select-tenant → assume → demo home; role switcher re-themes and
    re-identifies; persona chrome (`data-persona`, Platform-Admin inversion, VIEW ONLY tag);
    explainer popover open/close/Esc + focus trap; nav role-conditional + disabled future
    items; routing guard redirects a signed-out visitor from `/app`.

## 9. Work Breakdown

Ordered **simplest-first**: a thin end-to-end slice (items 1–5) proves the demo access
model, then UI layers on. Granular so the epic plan can group into small, isolated `[UI]`
epics (`[UI]` tagged where it renders).

**Walking skeleton — the access model end-to-end**

1. **`GET /api/tenants`** (backend) — registry-served `{slug, display_name,
   brand_primary_color}`; add `brand_primary_color` to `TenantConfig`. Tests.
2. **`POST /api/demo/assume-persona`** (backend) — resolve seeded persona
   (Agent→`agent.one`, Platform Admin→global), revoke prior session + audit, mint + cookie +
   audit, return identity; `demo_login_enabled` flag; registry/role validation. Tests.
3. **API client + types** (frontend) — `fetch` wrapper (`credentials:"include"`),
   `getCurrentIdentity`/`listTenants`/`assumePersona`/`signOut`, shared types.
4. **SessionProvider** (frontend) — restore via `/me`, `assumePersona`, `signOut`,
   `useCapability`; loading/signed-out states.
5. **Guarded `/app` + thin slice** `[UI]` — `RequireSession` guard; select-tenant fetches
   `/api/tenants` and on click assumes Agent → `/app`; `/app` shows "signed in as <role> ·
   <tenant>" from `/me`. End-to-end working.

**Design system & shell**

6. **Token CSS build-out** `[UI]` — tenant brand ramps (`[data-tenant]`), persona accents
   (`[data-persona]` + Platform-Admin drain), state colors, ink tokens, elevation/z/motion/
   radius/row-height additions; add IBM Plex Mono to `index.html`.
7. **Core components** `[UI]` — Button variants (refactor `.button-tonal`), Card, StampTag.
   Tests.
8. **Popover / MarginNote primitive** `[UI]` — anchored, focus-trapped, Esc-closes. Tests.
9. **App shell masthead** `[UI]` — wordmark + tenant seal + letterhead rule + persona
   indicator + session-indicator placeholder + bell placeholder + "How it's built" link;
   wire `data-tenant`/`data-persona` theming.
10. **Role switcher** `[UI]` — persona chips (§2.4), `assumePersona` on select, accent
    animation, Platform-Admin masthead inversion. Tests.
11. **Left nav** `[UI]` — role-conditional sections, future items disabled, active marker.
12. **Read-Only "VIEW ONLY" lock tag** `[UI]` — persistent on every screen for the persona.

**Demo surfaces**

13. **Landing page** `[UI]` — real orientation content + global footer (repo/author links).
14. **Select-tenant page** `[UI]` — branded cards, specialization blurbs, why-two-tenants,
    explainer; select → assume Agent → `/app`.
15. **Demo home (`/app`)** `[UI]` — in-app orientation hosting the active stepper.
16. **Guided stepper docket** `[UI]` — 21 steps, dismissible, per-step how-it's-built notes,
    inert deep links where destinations are absent; in-memory progress.
17. **Scenario-reference panel** `[UI]` — catalog of magic inputs / demo controls / time
    controls with trigger + outcome + "live in phase/step" markers; reachable from stepper +
    help icon.
18. **Explainer affordance** `[UI]` — `ExplainerIcon` + `ExplainerPopover` (PATTERN / HOW /
    REAL VS SIMULATED / CRM PARALLEL), seeded on landing / tenant-switch / role-switcher /
    session surfaces with real foundational copy.
19. **"Simulated" badge component** `[UI]` — dashed stamp + official-notice popover (WHAT IS
    MOCKED / WHAT IS REAL / THE ADAPTER SEAM) + a representative usage.
20. **"How it's built" page shell** `[UI]` — showcase-pattern index seeded with the real
    P1.1–P1.5 patterns as deep-link cards, project motivation, annotated architecture diagram
    placeholder (ink console) with real-vs-simulated legend, author/repo links.
21. **Brand-color alignment** — registry holds the Guide colors (Sunshine `#9C4A1E`, Florida
    `#0F6A72`); seed derives brand from the registry.
