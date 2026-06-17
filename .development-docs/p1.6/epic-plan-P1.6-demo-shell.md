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

## Epic 1 — Tenant list endpoint + registry brand color — **COMPLETED**
- **Goal:** Stand up the public, unauthenticated `GET /api/tenants` that returns the canonical tenant list (`slug`, `display_name`, `brand_primary_color`) straight from the registry — no DB read, no PII — so the pre-login tenant-selection screen has one authoritative source.
- **Rough scope:** A new demo router under `core/app/demo/` mounted in `main.py`; add `brand_primary_color` to the registry's `TenantConfig` (the authoritative Guide-aligned primary lives here). Tests assert the public shape and that no PII/DB read is involved.
- **Open questions / decisions for stakeholders:** Confirm the registry is where the authoritative `--primary` lives (vs `tenant_settings`); the Guide-aligned *values* land here but the seed's derivation from them is Epic 22's job — settle the boundary at epic time.
- **Depends on:** none.
- **Implementation notes:**
  - Added `brand_primary_color: str` to the frozen `TenantConfig` and set the Guide §2.3 authoritative primaries: Sunshine `#9C4A1E`, Florida `#0F6A72`. The registry is now the single source of truth for each tenant's `--primary`.
  - New `core/app/demo/` package (`__init__.py` + `router.py`): `APIRouter(prefix="/api")` with a public `GET /tenants` that loops `TENANTS` and returns `{"tenants": [{"slug","display_name","brand_primary_color"}, ...]}` in registry order (Sunshine, then Florida). No auth dependency and no `get_db` dependency — reads only the in-memory registry. Used the `/api` prefix (not `/api/demo`) so Epic 2 can add `POST /demo/assume-persona` to the same router without rework.
  - Mounted in `main.py` via `app.include_router(demo_router)`; updated the module docstring's router list.
  - **Epic-1 / Epic-22 boundary (recorded):** the registry now holds the authoritative Guide primaries, but the seed still hardcodes the placeholder colors (`#F5A623` / `#2E86C1`) into the `tenant_settings` rows. So `/api/tenants` (Guide colors) and the seeded DB rows (placeholders) intentionally diverge until Epic 22 rewrites the seed to derive its color from the registry. This is harmless per TDD §7 + Decisions 4/5/8: the masthead brand is frontend-owned and reads `/api/tenants`, not the DB rows. **`seed.py` / `tenant_settings` colors were deliberately not touched** — that is Epic 22.
  - Tests: new `core/tests/test_demo_tenants.py` (pure no-DB/no-Docker, mounts the real demo router on a throwaway FastAPI + `TestClient` with no overrides) covers 200 + exact body/order/Guide colors, public access with no `pf_session` cookie, exactly the three whitelisted keys per tenant (no PII), and correctness with no DB wiring (proves no DB read). `core/tests/test_registry.py` gains: every tenant's `brand_primary_color` matches `^#[0-9A-Fa-f]{6}$`, and the two values are exactly `#9C4A1E` / `#0F6A72`.
  - Targeted run (per `0-conventions.md`): `./.venv/Scripts/python.exe -m pytest tests/test_demo_tenants.py tests/test_registry.py` → 15 passed.

## Epic 2 — Passwordless assume-persona endpoint — **COMPLETED**
- **Goal:** Build `POST /api/demo/assume-persona {tenant_slug, role}` — the one seam serving both first entry ("assume Agent") and every role switch. It resolves a **seeded** persona deterministically, re-mints the session as that real user, and returns the same identity body as login, so "RBAC enforced per assumed role" is literally true.
- **Rough scope:** The route in the demo router; reuse existing `auth/sessions.py` (`create_session`/`revoke_session`), the `_identity_response` shape, and the RBAC role enum; registry-validate `tenant_slug`; tie-break two Agents by lowest username; route Platform Admin to the global tenantless user. Revoke + audit any prior session, mint + cookie + audit the new one. Add the `demo_login_enabled` config flag (default on). Tests: correct persona per role, 404 unknown tenant, 422 bad role, re-mint replaces prior session, capabilities match the role, audit events recorded.
- **Open questions / decisions for stakeholders:** Confirm the audit routing on a role switch (logout audited under the old tenant, login under the new) and the two-Agent tie-break rule read as intended — both are specified in the TDD; settle any naming at epic time. This is an auth-path endpoint kept whole as one coherent flow (correctness-critical) — confirm that's acceptable vs splitting mint/revoke.
- **Depends on:** none (builds on existing P1.1–P1.5 auth, sessions, registry, seed).
- **Implementation notes:**
  - Added `demo_login_enabled` flag to `config.py` (env `DEMO_LOGIN_ENABLED`, default on, truthy-set idiom mirroring `session_cookie_secure`); OFF → `403 {"detail": "demo login is disabled"}`.
  - Extracted the shared identity body into new `core/app/auth/identity.py` as public `build_identity_response(identity)`; `auth/router.py` now imports it (private `_identity_response` deleted, `CAPABILITIES` import dropped). One definition, both routers; login/`me`/assume-persona share it. The extraction is regression-guarded by `test_endpoints_db.py` (body shape) and `test_auth_audit.py` (audit routing).
  - New `POST /api/demo/assume-persona` lives on the existing `demo/router.py` (`/api` prefix), kept whole: refuse-if-disabled → resolve seeded persona → revoke+audit prior session → mint+cookie+audit new. `GET /tenants` stays DB-free.
  - Persona resolver `_get_seeded_persona`: tenant-scoped role registry-validates the slug (unknown → 404) then picks `(tenant_id, role)` ordered by username (`agent.one` tie-break); Platform Admin ignores the slug and resolves the global tenantless admin (unknown slug does NOT 404). Typed `role: Role` gives 422 on a bad role for free. Defensive missing-persona → 404.
  - Role-switch re-mint resolves the old identity **before** revoking, audits `auth.logout` under the old tenant, then `auth.login` under the new persona's tenant (platform store for Platform Admin) — mirrors `auth/router.py` routing exactly.
  - Tests: new `tests/test_demo_assume_persona.py` (per-role persona, capabilities, cookie/`me`, 404 unknown tenant, 422 bad role, re-mint revokes prior + dual-tenant audit, flag-off 403) and `tests/test_config.py` flag cases. The replay-after-revoke check clears the cookie jar and re-sets the old token (httpx 0.28 dropped per-request `cookies=`).
  - Deviation/finding: the targeted command surfaces one failure, `test_auth_audit.py::test_logout_audits_attributed_to_the_actor`, which is a **pre-existing cross-file order bug** — it asserts a global `== 1` logout count for the shared Tenant Admin while `test_endpoints_db.py::test_me_after_logout_is_401` accumulates a logout row for that same actor in the never-reset container DB. Reproduces with this epic's edits stashed; not caused by Epic 2 and out of scope. Each file passes in isolation; all 18 new assume-persona tests + 12 config tests pass.

## Epic 3 — Frontend API client + shared types — **COMPLETED**
- **Goal:** A thin, typed `fetch` wrapper (`credentials: "include"` so the `pf_session` cookie rides every call) exposing `getCurrentIdentity`, `listTenants`, `assumePersona`, `signOut`, with shared types (`Identity`, `Role`, `Capability`, `Tenant`) — the single client every later frontend epic calls.
- **Rough scope:** A new `frontend/src/api/` module: the wrapper, the four typed calls, the shared type definitions, and typed error handling. Vitest unit tests mock fetch (jsdom has no backend).
- **Open questions / decisions for stakeholders:** Confirm the typed-error shape (how a non-2xx / network failure surfaces to callers) so contexts and surfaces handle it consistently — minor; otherwise none expected.
- **Depends on:** Epic 1, Epic 2 (the endpoints it wraps).
- **Implementation notes:**
  - Four new files under `frontend/src/api/`, no other source touched. `types.ts` holds the four shared types; `client.ts` holds `ApiError` + the `request<T>` wrapper + the four calls; `index.ts` is the barrel later epics import from (`../api`); `client.test.ts` is the vitest unit suite.
  - **Wire-shape types, snake_case (verified against backend source):** `Identity`/`IdentityUser`/`Tenant` match the JSON exactly (snake_case keys: `tenant_id`, `display_name`, `brand_primary_color`; raw UUID strings; `tenant_id: string | null` for the tenantless Platform Admin). `Role` and `Capability` are string-literal unions transcribed by hand from `core/app/models/user.py` (4 roles) and `core/app/auth/rbac.py` (10 capabilities). No camelCase mapping layer — confirmed against `core/app/auth/identity.py::build_identity_response` and `core/app/demo/router.py::list_tenants`.
  - **Call arguments stay camelCase; the wrapper maps to the wire.** `assumePersona(tenantSlug, role)` sends `{ tenant_slug, role }` so call sites never hand-write snake_case keys.
  - **`request<T>` wrapper:** `fetch(path, { method, credentials: "include" })`; for a body it sets `Content-Type: application/json` and `JSON.stringify`s it (GET sends no body/header); on a 2xx it returns `response.json() as T`.
  - **Typed errors (settled at the planning gate):** a non-2xx throws `ApiError(status, message)` and a network drop throws `ApiError(0, "network request failed")`. `ApiError extends Error` with `readonly status` and `name = "ApiError"` (verified `instanceof Error`/`instanceof ApiError`). Message extraction (`readErrorMessage`) uses the backend's `detail` only when it is a **string**; a `422`'s array `detail`, a missing `detail`, or a non-JSON body falls back to `response.statusText` (then a generic `"request failed"`).
  - **`listTenants` unwraps the `{ tenants: [...] }` envelope** into a plain `Tenant[]`; **`signOut` ignores the response body** and resolves to `void`. Relative `/api/...` paths (same-origin; the cookie rides via `credentials:"include"`) — a Vite dev proxy is out of scope here (later-epic infra).
  - **No HTML `id`s:** no JSX/DOM in this epic, so the project's "id on every element" rule does not apply (per the approved plan; recorded so review doesn't flag the absence).
  - **Type-drift caveat:** the `Role`/`Capability` unions mirror the backend StrEnums by hand, so a new backend value is unknown to the frontend type until added here too. Acceptable for the demo; noted in `types.ts`.
  - **Tests + typecheck (per `0-conventions.md`, frontend-only — backend untouched, no pytest):** `npx vitest run src/api/client.test.ts` → 11 passed (1 file). `npm run build` (`tsc -b` strict + vite) → passes clean. Tests mock `globalThis.fetch` via `vi.stubGlobal` and cover: each call's path/method/`credentials:"include"`, the POST JSON body + header, envelope unwrap, `void` signOut, and the error paths (401/403/404 detail, 422 array-detail fallback, non-JSON-body fallback, network drop → status 0, `instanceof`).
  - Diff: 4 files, +427 (≈224 of which is the test file); one concern (the typed client) — within budget, no split.

## Epic 4 — Session context + capability helper — **COMPLETED**
- **Goal:** A `SessionProvider` React context that restores identity via `/me` on mount (loading → signed-in → signed-out), exposes `identity`, `capabilities`, `assumePersona`, `signOut`, and a `useCapability(cap)` helper that reads the server-returned matrix — the shared session state every authed surface consumes.
- **Rough scope:** A new context module under `frontend/src/` wrapping the Epic 3 client; the load/refresh lifecycle and the capability helper. Tests cover the three states and that `assumePersona`/`signOut` refresh identity. (No rendered surface — infrastructure.)
- **Open questions / decisions for stakeholders:** Confirm the signed-out vs error distinction (a clean "not signed in" vs a failed `/me`) — affects how the guard in Epic 5 redirects; settle at epic time.
- **Depends on:** Epic 3.
- **Implementation notes:**
  - Five new files under `frontend/src/session/` (mirroring the `api/` module's split), plus one edit to `frontend/src/main.tsx`. No other source touched; backend untouched (frontend-only infrastructure — no pytest).
  - **`SessionContext.ts`** holds the `SessionStatus` union (`"loading" | "signed-in" | "signed-out"`), the `SessionContextValue` interface (`status`, `identity: Identity | null`, `capabilities: Capability[]`, `assumePersona`, `signOut`), the `createContext<SessionContextValue | null>(null)` object, and the `useSession()` hook (throws a clear error if read outside a provider). No JSX here → clean Vite fast-refresh boundary (the only component lives in `SessionProvider.tsx`).
  - **`SessionProvider.tsx`** is the module's only component. `status` starts `"loading"`, `identity` starts `null`. A mount effect calls `getCurrentIdentity()`; success → `setIdentity` + `signed-in`; **any** rejection → `identity = null` + `signed-out`. An `isActive` cleanup flag ignores a late resolution after unmount (and StrictMode's dev double-invoke). `capabilities` in the provided value is `identity ? identity.capabilities : []`. Renders `{children}` through the context provider with no DOM node of its own.
  - **Three states, fail-closed (the settled open question):** a failed `/me` that is not a clean 401 — a 500, or in local dev simply no backend to reach (the Vite dev proxy is a later epic) — is treated **the same as a 401: `signed-out`**. The mount-effect `catch` swallows every error identically; there is no fourth "error" state. Keeps Epic 5's guard a clean binary (not signed in → redirect to `/`). Matches TDD §5.2.
  - **Actions (each a `useCallback`)** import the client calls aliased to avoid shadowing the context method names (`assumePersona as assumePersonaRequest`, `signOut as signOutRequest`). `assumePersona(tenantSlug, role)` awaits the request and sets the **returned** identity + `signed-in` — it refreshes identity from the call's own response body (same `Identity` shape as `/me`), so there is **no second `/me` round trip**; a failure propagates to the caller with state unchanged. `signOut()` awaits the request, then clears identity + `signed-out`.
  - **`useCapability.ts`** is the one-line permission check: `useSession().capabilities.includes(capability)`. Returns `false` while loading / signed out (empty list) — fail-closed, tracking the server-returned RBAC matrix.
  - **`index.ts`** barrel re-exports `SessionProvider`, `useSession`, `useCapability`, and the `SessionStatus` / `SessionContextValue` types (the import surface later epics use as `../session`).
  - **`main.tsx` edit (the one change to existing code):** wrapped `<App />` in `<SessionProvider>` **inside** `<BrowserRouter>` (so the provider sits at the root above the router), making the provider live and firing the startup `/me` once. Nothing visible changes — no surface reads session yet. In `npm run dev` the `/me` call has no backend and fail-closes to `signed-out`, harmless.
  - **Reuse, no new dependencies:** `getCurrentIdentity`, `assumePersona`, `signOut` and the `Identity` / `Role` / `Capability` types all come from the Epic 3 `../api` barrel. React Context is built-in (per TDD Decision 6).
  - **No HTML `id`s:** the provider adds no DOM element (renders `{children}` through a context provider) and the module has no rendered surface, so the project's "id on every element" rule does not apply — same reasoning recorded for Epic 3. The test harness's throwaway elements are test-only.
  - **Type-drift** is inherited from Epic 3's hand-mirrored `Role` / `Capability` unions; nothing new added here.
  - **Tests + build (per `0-conventions.md`, frontend-only — backend untouched, no pytest):** `npx vitest run src/session/` → 10 passed (1 file); covers the three states (initial `loading`; `signed-in` exposing identity + capabilities; 401 → `signed-out`; non-401/network → `signed-out`), both actions (`assumePersona` signed-out → signed-in with the new identity, and that it refreshes from its own response — `getCurrentIdentity` stays called exactly once; `signOut` signed-in → signed-out clearing identity), `useCapability` true/false + false-while-signed-out, and `useSession()` outside a provider throwing. `npx vitest run src/App.test.tsx` → 1 passed (the `main.tsx` wiring didn't break the app tree). `npm run build` (`tsc -b` strict + vite) → clean. `../api` is mocked with `vi.mock`; tests use a small readout harness that prints status/role/capabilities into the DOM.
  - Diff: 6 files — 5 new (`SessionContext.ts`, `SessionProvider.tsx`, `useCapability.ts`, `index.ts`, `SessionProvider.test.tsx`) + the `main.tsx` edit; ~178 lines of production code (the 341-line test file does not count toward the budget). One concern (shared session state) — within budget, no split.

## Epic 5 — Guarded /app + thin end-to-end slice [UI] — **COMPLETED**
- **Goal:** Prove the whole access model end-to-end in the browser: a public/`/app` routing split behind a `RequireSession` guard (skeleton while `/me` resolves, redirect to `/` when signed-out), a thin select-tenant that lists `/api/tenants` and on click assumes Agent, and an `/app` that shows "signed in as <role> · <tenant>" from `/me`.
- **Rough scope:** The routing split in `App.tsx`, the `RequireSession` guard, a minimal (un-branded) select-tenant and demo-home using existing base styles. Tests: select → assume → demo home; guard redirects a signed-out visitor from `/app`.
- **Open questions / decisions for stakeholders:** none expected — this is the walking skeleton; branding and real content arrive in later epics.
- **Depends on:** Epic 3, Epic 4.
- **Implementation notes:**
  - **Phase 1 — backend identity enhancement (in-scope by gate decision).** `build_identity_response` is now **async** and takes `db`: when `identity.tenant_id` is set it does a `db.get(Tenant, tenant_id)` (cheap primary-key fetch, non-hot path) and adds `tenant_slug` + `tenant_name` to the `user` block; both are `null` for the tenantless Platform Admin. `auth/router.py` (`login`, `get_me` — the latter gained a `db = Depends(get_db)`) and `demo/router.py` (`assume_persona`) now `await` it. `Tenant.name` is the registry `display_name` (set by the seed), so the demo-home name matches `/api/tenants` and the select-tenant cards. The body stays PII-free. This is the only backend touch and it is the prerequisite for the demo-home "<role> · <tenant>" line — kept whole with the UI per the gate (a backend-only micro-epic would be more awkward than the coupling).
  - **Phase 2 — guarded `/app` zone.** `IdentityUser` gained `tenant_slug` / `tenant_name` (`string | null`, wire-shape, always present); the two existing `Identity` fixtures (`client.test.ts`, `SessionProvider.test.tsx`) were updated so typecheck stays green. New `RequireSession.tsx` is an idiomatic react-router v6 layout-route guard: `loading` → a `role="status"` `aria-live="polite"` "Restoring your session…" skeleton in a `PageLayout`; `signed-out` → `<Navigate to="/" replace />` (no history pollution); `signed-in` → `<Outlet />`. New `DemoHomePage.tsx` reads `useSession().identity`, maps role → human label via a small `ROLE_LABELS` constant, and renders "Signed in as <role> · <tenant_name>" (Platform Admin's null `tenant_name` → "Platform — no tenant scope"); a defensive null-identity guard renders a neutral note. `App.tsx` nests the guarded zone (`/app` → `RequireSession` → index `DemoHomePage`) so P1.7 can add `/app/*` children; the `*` → `/` redirect stays last.
  - **Phase 3 + 4 — live select-tenant, built in one file.** `SelectTenantPage.tsx` was rewritten from the static placeholder to the live flow: fetch `listTenants()` on mount, render each tenant as a focusable `<button className="tenant-card tenant-card-button">`, and on click `await assumePersona(slug, "agent")` then `navigate("/app")`. The robust states (Phase 4) live in the same file because they are the same surface's state machine — a `LoadState` union (`loading | loaded | error`) drives the loading status, the empty note, and the fetch-error + **Retry** path; an `assumingSlug` + `assumeError` pair disables the buttons and shows "Signing you in…" while a persona is in flight, re-enabling + messaging on an assume failure. Un-branded — `brand_primary_color` is deliberately not used yet (Epic 15).
  - **Card markup change:** the clickable card's name/note are `<span>`s (block via CSS), not `<h2>`/`<p>`, since they now live inside a `<button>` (a button must not wrap a heading). Styling reuses the existing `.tenant-card` surface with a `.tenant-card-button` reset (full-width, left-aligned, inherits font, `--surface-1` hover, disabled dimming); the global `:focus-visible` ring and reduced-motion rule from `base.css` apply unchanged. New CSS is tokens-only (no raw hex), reusing the existing display/headline registers — no new tokens/fonts/palette/components (those are Epics 6–8).
  - **`id` on every element (CLAUDE.md):** every rendered element carries a unique id — guard skeleton (`app-loading-*` from `PageLayout`, `app-session-skeleton`, `-message`), demo home (`demo-home-content/-title/-status/-role/-tenant`, plus `-empty` for the defensive branch), select-tenant (`select-tenant-card-<slug>` buttons + `-name`/`-note`, and `-loading`/`-empty`/`-error`/`-error-message`/`-retry-button`/`-pending`/`-assume-error`).
  - **Deviation — test runner:** the plan's `SelectTenantPage.test.tsx` sketch implied `@testing-library/user-event`, which is **not** a project dependency (no other test uses it). To avoid adding a dependency for this epic, the tests use `fireEvent` from `@testing-library/react` (the pattern the existing suite already uses). No behavior change.
  - **Tests + build (targeted, per `0-conventions.md`):** backend `./.venv/Scripts/python.exe -m pytest tests/test_endpoints_db.py tests/test_demo_assume_persona.py` → **23 passed**. Frontend `npx vitest run src/components/RequireSession.test.tsx src/pages/SelectTenantPage.test.tsx src/api/client.test.ts src/session/SessionProvider.test.tsx src/App.test.tsx` → **29 passed (5 files)**; `npm run build` (`tsc -b` strict + vite) → **clean** (47 modules). Full suites run at manual commit time via the pre-commit hook.
  - **Size:** one coherent concern (the walking skeleton end-to-end). Production code is modest; the bulk of the diff is two new test files and tokens-only CSS (both excluded from the budget by the plan's note). Within budget — no split.

## Epic 6 — Design tokens + IBM Plex Mono [UI] — **COMPLETED**
- **Goal:** Build out the Guide token layer the rest of the phase needs: tenant brand **ramps** as `[data-tenant]` blocks, **persona accent** tokens as `[data-persona]` blocks plus the Platform-Admin brand-drain, the state colors + containers, the ink-console tokens, and the missing elevation / z-index / radius / motion / row-height values. Load IBM Plex Mono.
- **Rough scope:** `styles/tokens.css` additions keyed by slug/persona (authoritative `--primary` comes from the backend; supporting ramp tokens are frontend design data per the Guide); the font in `index.html`. Mostly additive CSS values.
- **Open questions / decisions for stakeholders:** **Which ink-console token subset to land now vs defer** (a TDD §7 open question) — settle the minimum needed by the "How it's built" diagram (Epic 21) without front-loading the full console system.
- **Depends on:** none (foundational; sequenced after the skeleton).
- **Implementation notes:**
  - **Scope — two files only:** `frontend/src/styles/tokens.css` (all token additions) and `frontend/index.html` (one extended font `<link>` href). No React/DOM, no logic — pure declarative design data copied verbatim from the Guide (§2.1–2.4, §3, §4). Backend untouched → no pytest.
  - **Ink-console subset decision (the open question — resolved at the gate):** land the **full** ink color subset now, not a partial cut. The Guide's §2.1 ink block and §2.2 on-ink brights are a small, cohesive 9-token set (`--surface-ink`, `--surface-ink-raised`, `--on-ink`, `--on-ink-variant`, `--outline-ink` + the four `--state-*-on-ink` brights); splitting it would invite a second guess about which brights pair with which ink later. These are **color tokens only** — the ink-console *components* still arrive with their owners (timeline/trace/payload/outbox/DLQ, Epic 21 et al.). This satisfies the Epic 21 "How it's built" diagram's needs without front-loading the console component system.
  - **Real-wire-string selectors (the plan's CRITICAL note — verified):** `[data-persona]` selectors use the runtime role strings (`agent`, `tenant_admin`, `read_only`, `platform_admin` — snake_case, underscores), confirmed against `frontend/src/api/types.ts::Role`. `[data-tenant]` selectors use the runtime slugs (`sunshine-senior-benefits`, `florida-family-planning` — hyphens), confirmed against `GET /api/tenants` / the registry. The Guide's illustrative `[data-persona="platform-admin"]` hyphen was deliberately corrected to the underscore wire string, otherwise Epic 10's theming would silently no-op. Token **names** stay kebab-case (matching the Guide's own `--persona-platform-admin-on-ink`).
  - **No collisions:** only ADDED tokens — `--space-8`, `--radius-lg`/`--radius-full`, `--motion-fast`/`--motion-slow`, the elevation/scrim, interaction-layer, row-height, and z-index scalars, the state + ink + persona color palettes, and the tenant/persona theming blocks. The pre-existing surfaces/outline/text/fonts/`space-1..7`/`radius-sm,md`/`motion-standard`/`focus-ring` were left as-is. `--font-mono` was the one *edited* existing token (prepended `"IBM Plex Mono"`), matching Guide §3 now that the web font loads.
  - **Lowercase-hex convention:** all new hex written lowercase (`#9c4a1e`, not the Guide's uppercase `#9C4A1E`) to match the file's existing `#f2efe9` style; values are otherwise verbatim from the Guide. `rgba()` channel alphas written with a leading zero (`0.05`) to match the file's `cubic-bezier(0.2, ...)` style; magnitudes verbatim.
  - **Font wiring:** extended the single existing combined Google-Fonts `<link id="font-stylesheet-besley-public-sans">` href with `&family=IBM+Plex+Mono:wght@400` (weight 400 only, alphabetical family order) — same element, same id, no new `<link>`.
  - **No new test file (recorded decision):** there is no token-test precedent in the suite and these are pure declarative CSS custom properties with no behavior to assert; a snapshot/value test would just restate the Guide. Regression confidence comes from the green build + existing vitest suite (no JS source changed).
  - **`id`-on-every-element rule — N/A:** this epic renders no DOM (CSS custom properties + one font-link href edit), so the project's HTML-id rule does not apply — same reasoning recorded for Epics 3/4.
  - **Verification (targeted, frontend-only per `0-conventions.md`):** from `frontend/`, `npm run build` (`tsc -b && vite build`) → clean (47 modules). `npx vitest run` → **30 passed (6 files)**, unchanged from before (confirms no regression; no JS source touched). No deviation from the approved plan.

## Epic 7 — Button variants [UI] — **COMPLETED**
- **Goal:** A `Button` component covering the Guide's Filled / Tonal / Outlined / Text variants with proper focus ring and a unique `id` per element, replacing the existing ad-hoc `.button-tonal`.
- **Rough scope:** The component under `frontend/src/components/`, plus refactoring current `.button-tonal` usages onto it. Tests cover the variants and disabled/focus states.
- **Open questions / decisions for stakeholders:** Confirm the variant-name mapping to the Guide and that every existing button usage migrates now (vs incrementally) — settle at epic time.
- **Depends on:** Epic 6.
- **Implementation notes:**
  - **Five new files + four edits, frontend-only (no backend, no pytest).** New: `components/buttonVariants.ts`, `components/Button.tsx`, `components/ButtonLink.tsx`, `styles/button.css`, `components/Button.test.tsx`. Edited: `main.tsx` (css import), `pages/SelectTenantPage.tsx` (Retry), `pages/LandingPage.tsx` (CTA), `styles/pages.css` (deleted `.button-tonal` + tidied the header comment).
  - **Variant-name mapping + migrate-all decision (the open question — settled at the gate):** the four variants are the Guide's, lowercase — `"filled" | "tonal" | "outlined" | "text"` — in `buttonVariants.ts` as a `ButtonVariant` type plus `buttonClassName(variant)` → `"button button-<variant>"`. The helper is kept JSX-free in its own module (clean Vite fast-refresh boundary, mirroring the `api/`/`session/` splits) and shared by both `Button` and `ButtonLink` so the two render identically. **Both** `.button-tonal` usages migrated now and the class fully deleted; the `.text-link` "Back to landing" nav link was deliberately left as-is (out of scope per the gate).
  - **Token fallbacks (the central design tension):** colors use `var(--token, <neutral>)` so the variants are Guide-correct once Epic 10 sets `[data-tenant]`/`[data-persona]`, yet render neutrally unthemed. Filled = `var(--primary, var(--on-surface))` on `var(--on-primary, var(--surface-2))` (ink-on-paper unthemed). **Tonal fallback reproduces the retired `.button-tonal` exactly** — `var(--primary-container, var(--surface-3))` fill, `var(--on-primary-container, var(--on-surface))` ink, `1px solid var(--outline)` — so the two migrated buttons are a pixel-identical, no-visual-change refactor. Outlined/Text are transparent on `--on-surface` (Outlined adds the hairline; Text drops it and uses `--space-3` padding). Tokens only, no raw hex.
  - **Hover/press = one MD3 state-layer overlay** (`.button::before`, `background: currentColor`, `pointer-events: none`) over a local stacking context (`isolation: isolate`; the label span gets its own `z-index` to ride above it). Strengthens to `--state-layer-hover` / `--state-layer-pressed`, suppressed via `:not(:disabled)`. Works uniformly for all four variants — transparent ones get a wash, filled gets a film — replacing the old per-class `background-color` hover. Transition uses `--motion-fast` (the retired class used `--motion-standard`; `fast` is the Guide's hover/press token, §4) — a deliberate, non-visual timing correction.
  - **Pending state landed now (Guide §5 complete):** `isPending` on `Button` only (a nav `ButtonLink` does not pend). Sets native disabled (`disabled || isPending`) + `aria-busy`, and renders an `aria-hidden` `<span id="${id}-spinner">` before the label — a CSS ring (`border-right-color: transparent`) spun by `@keyframes button-spinner-rotation`. Reduced-motion is already handled by the global rule in `base.css` (it freezes the spin and the transitions), so no per-component override.
  - **Focus ring:** none added — the global `:focus-visible` rule in `base.css` already covers the real `<button>` and `<a>` these render.
  - **`id` on every element (CLAUDE.md):** `Button`/`ButtonLink` take a **required** `id` (they are reusable; the caller owns it), with derived ids `${id}-label` and `${id}-spinner`. Existing call-site ids preserved verbatim: `landing-select-tenant-button`, `select-tenant-retry-button`.
  - **`onClick` return value:** the Retry button's `onClick={loadTenants}` still returns `loadTenants`'s cleanup function, exactly as the native `<button>` did before; React ignores onClick return values, so behavior is unchanged.
  - **CSS import:** `import "./styles/button.css";` added to `main.tsx` between `base.css` and `pages.css` (CSS is imported globally there).
  - **Tests (per `0-conventions.md`, frontend-only):** new `components/Button.test.tsx` follows the suite's `@testing-library/react` + `fireEvent` pattern (no `user-event` — not a project dependency); `ButtonLink` wrapped in a `MemoryRouter`. Covers each variant → its class, default `type="button"`, the `id` + `${id}-label`, `onClick` fires, disabled blocks the click, `isPending` → disabled + `aria-busy="true"` + `${id}-spinner` present + click blocked, no spinner when not pending, and `ButtonLink` rendering an `<a href>` at `to` with the variant class. `npx vitest run src/components/Button.test.tsx` → **11 passed**. `npx vitest related --run` the changed sources → **19 passed (4 files)** (`RequireSession.test.tsx`, `SelectTenantPage.test.tsx`, `Button.test.tsx`, `App.test.tsx` all green). `npm run build` (`tsc -b` strict + vite) → **clean (51 modules)**. (React Router v7 future-flag warnings are pre-existing across the suite, not errors.)
  - **Size:** one concern (the Button primitive). Production code is modest; the bulk of the diff is the test file + tokens-only CSS (both excluded from the budget per the plan's note). Within budget — no split.
  - **Out-of-scope working-tree note:** the tree already carried two unrelated, pre-existing uncommitted changes when this epic started — `core/alembic.ini` (a `prepend_sys_path = .` line) and `.vscode/tasks.json` — neither touched by Epic 7 (frontend-only). Left as-is for the human; they are not part of this epic's commit.

## Epic 8 — Card + StampTag [UI] — **COMPLETED**
- **Goal:** Two small presentational primitives — `Card` (the Guide container) and `StampTag` (status + overline stamp) — that later surfaces (tenant cards, nav markers, "How it's built" cards, the Simulated badge) build on.
- **Rough scope:** Both components under `frontend/src/components/`, each with a unique `id` and ARIA where relevant. Tests cover the StampTag status/overline variants.
- **Open questions / decisions for stakeholders:** none — resolved at plan time (see Implementation notes).
- **Depends on:** Epic 6.
- **Implementation notes:**
  - **StampTag status set = full five** (`success`/`pending`/`warning`/`error`/`neutral`), gate decision, though only `warning` + `neutral` render in P1.6 — feature phases (P1.7+) reuse it without reopening the component. Discriminated-union API: `status` required on the (default) `status` variant, disallowed on the `overline` variant. Exports `StampStatus` for later callers.
  - **On-ink deferred** (affects Epics 20/21): stamps ship paper-ground only; the `--state-*-on-ink` bright variant arrives with the first ink-console stamp usage. No P1.6 surface renders stamps on ink.
  - StampTag `icon` is an optional `aria-hidden` slot; the always-present uppercase text label satisfies "not by color alone" — no icon system built (TDD Decision 6, no new deps).
  - Card built to the full Guide contract (title + body + optional footer) + `headingLevel` (2|3|4, default 2) so later epics nest cards under deeper page headings without breaking heading order. Untitled card carries no `aria-labelledby` (unnamed section, deliberately not a landmark).
  - **No migration** of the existing `.tenant-card` (`styles/pages.css`); Epic 15 rebuilds the select-tenant cards branded on `Card`. Recorded so review doesn't flag the absence.

## Epic 9 — Popover / MarginNote primitive [UI] — **COMPLETED**
- **Goal:** The anchored, focus-trapped, Esc-closes popover primitive that is the shared substrate for both the explainer and the Simulated-badge popovers later — built once, correctly, with full keyboard a11y.
- **Rough scope:** A `Popover`/`MarginNote` component under `frontend/src/components/`: anchoring, focus trap, Esc + outside-click close, ARIA wiring. Hand-rolled (no new deps, per TDD Decision 6). Tests: open/close/Esc + focus trap.
- **Open questions / decisions for stakeholders:** none — resolved at plan time (see Implementation notes).
- **Depends on:** Epic 6.
- **Implementation notes:**
  - **API (affects Epics 19/20):** self-contained `Popover` owns the trigger button + open state. Required props `id`, `trigger: ReactNode`, `triggerLabel: string` (accessible name for the icon-only trigger), `surfaceLabel: string` (the panel's `aria-label`), `children`; optional `triggerClassName` (consumer styling — e.g. Epic 20's dashed stamp). Derived ids `${id}-trigger`, `${id}-surface`. Epic 19 `ExplainerPopover` / Epic 20 `SimulatedBadge` wrap it and pass only their own icon/label + contents; the Guide's illustrative `id="explainer-<surface>-icon"` maps to `${id}-trigger`.
  - **Contract (affects Epics 19/20):** non-modal `role="dialog"` + `aria-label`, **no scrim** (never blocks the workflow). On open, focus moves into the surface (`tabIndex={-1}`); Tab is trapped (wraps last→first / first→last, pins to the container when there are no interior controls). Closes on **Esc** (focus restored to trigger), **outside `mousedown`** (focus left where clicked), and **trigger toggle** (focus already on the trigger). The focus trap is hand-rolled in a colocated `useFocusTrap.ts` hook (no new dependency, TDD Decision 6) — extracted to keep `Popover.tsx` readable; tested through the component.
  - **Positioning caveat (affects Epics 19/20):** in-tree (no portal, stays glued on scroll), absolute, single default placement (below-start: `top: calc(100% + --space-2)`, `left: 0`); `min-width: 240px` / `max-width: 360px`. **No collision/flip logic** — Epics 19/20 must place the trigger with room below/right or revisit (deferred, not in scope here).

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
