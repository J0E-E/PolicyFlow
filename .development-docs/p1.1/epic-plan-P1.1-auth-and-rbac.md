# Authentication & RBAC — Epic Plan

Source TDD: [./tdd-P1.1-auth-and-rbac.md](./tdd-P1.1-auth-and-rbac.md)

> **Review budget:** ~150 changed lines · ~8 non-generated files · one focused commit per epic. Tunable per project.

> This is a high-level agile roadmap. Each epic's design specifics are confirmed
> with stakeholders at epic time (`3-plan-epic`) before any code is written.

## Epic 1 — ORM + async engine skeleton — **COMPLETED**
- **Goal:** Stand up SQLAlchemy 2.0 (async) over the existing Alembic wiring so the rest of the phase has a database session to work with — proven by the engine connecting, with no tables yet.
- **Rough scope:** Add `sqlalchemy[asyncio]` to the core runtime deps; a new engine/session module (async engine from `DATABASE_URL`, a session-maker, a request-scoped `get_db` dependency, and the declarative base every model will extend).
- **Open questions / decisions for stakeholders:** Module name/home for the engine; whether to verify connectivity via a throwaway check or lean on the existing health probe.
- **Depends on:** none.
- **Implementation notes:**
  - Engine home: `core/app/db.py` (per TDD §5).
  - `DATABASE_URL` rewritten to `postgresql+asyncpg://` via `get_asynchronous_database_url()` — the async twin of `env.py`'s sync `postgresql+psycopg://` rewrite, same fail-fast `RuntimeError` on a missing/unsupported scheme.
  - `engine = create_async_engine(...)` is built at import but lazy (no connection until first use); `session_factory = async_sessionmaker(engine, expire_on_commit=False)`; `Base(DeclarativeBase)` (models in Epic 2); `get_db()` yields a request-scoped `AsyncSession` and closes it.
  - Deliberately untouched this epic: `main.py` (no consumer of `get_db` until Epics 7–8), `config.py` (`session_*` settings are Epic 5), `alembic/env.py` (`target_metadata`/`include_schemas` is Epic 2).
  - `sqlalchemy[asyncio]==2.0.36` pinned (the `[asyncio]` extra pulls `greenlet`); `asyncpg==0.30.0` already present, so no driver change.
  - Connectivity proven by a no-Docker wiring test (`core/tests/test_db.py`, 7 cases) plus the existing health probe; live engine-vs-Postgres deferred to the Epic 11 substrate (stakeholder decision).
  - Caveat for future tests: `engine` is built from `settings` at import, so a test changing `DATABASE_URL` must reload `app.config` before `app.db` (the wiring test does this via a reload helper).
  - Test note: `app.db` builds its engine from `settings` at import, so the wiring test sets `DATABASE_URL`, reloads `app.config`, then imports/reloads `app.db` in that order so the engine is built against a valid URL.
  - Environment note (not an epic deliverable): the core suite must run under the project's `core/.venv` (Python 3.12); the global Python 3.14 cannot install the pinned `asyncpg==0.30.0` / `psycopg[binary]==3.2.3` wheels. Full suite green there (12 passed).

## Epic 2 — Domain models + migration `0002` — **COMPLETED**
- **Goal:** Create the first real schema — the shared `platform` schema with `tenants`, `users`, and `auth_sessions` — as ORM models plus a matching hand-written Alembic migration, so the database carries identity, tenant, and session data.
- **Rough scope:** The three model definitions (including the `Role` enum, the nullable `tenant_id`, the Platform-Admin CHECK constraint, unique indexes, and the SHA-256 `token_hash` column); a hand-written `0002` migration creating the schema + tables + enum; point Alembic's `target_metadata` at the models and enable schema-aware autogenerate so future drift is catchable.
- **Open questions / decisions for stakeholders:** Exact column types/defaults (UUID generation, `timestamptz` defaults); whether to keep models and migration in one epic or split if the migration balloons.
- **Depends on:** Epic 1.
- **Implementation notes:**
  - New `core/app/models/` package: `tenant.py` (`Tenant`), `user.py` (`Role` StrEnum + `User`), `auth_session.py` (`AuthSession`), `__init__.py` imports all three (registering the tables on `Base.metadata`) and re-exports `AuthSession`, `Role`, `Tenant`, `User`.
  - All tables `schema="platform"`; `Uuid` PK `default=uuid.uuid4` (Python-side, no DB default); `created_at` `TIMESTAMP(timezone=True)` `server_default=text("now()")`.
  - `User.role` maps to the Postgres enum `platform.user_role` with lowercase labels via `values_callable`; named CHECK `platform_admin_tenantless`; `is_active` `server_default=true()`; `tenant_id` nullable FK → `platform.tenants.id`; `username` unique.
  - `AuthSession`: unique `token_hash`; `user_id` FK → `platform.users.id` `ON DELETE CASCADE`, not null; `expires_at` not null; `revoked_at` nullable.
  - `db.py`: added a `MetaData(naming_convention=...)` (ix/uq/ck/fk/pk) on `Base.metadata` — the only change to the Epic-1 file — so model + migration constraint names agree by construction. Verified the model side emits exactly `pk_*`, `uq_*`, `fk_users_tenant_id_tenants`, `fk_auth_sessions_user_id_users`, `ck_users_platform_admin_tenantless`, matching `0002` verbatim.
  - Hand-wrote `0002_platform_identity.py` (`down_revision = "0001_empty_baseline"`): `CREATE SCHEMA IF NOT EXISTS platform`, create the `user_role` enum (`create_type=False` on the shared `Enum`, created once explicitly), the three tables with the convention names; downgrade drops tables in reverse, then the enum, then the schema.
  - `env.py`: `import app.models` + `from app.db import Base`, `target_metadata = Base.metadata`, `include_schemas=True` in both offline and online `context.configure(...)` calls.
  - `conftest.py`: `os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://...")` at the very top (before `from app.main import app`) so the eager engine build never raises on an unset URL; `setdefault` lets a real CI/dev URL win.
  - `test_models.py`: pure-Python metadata assertions, no live DB. Note — `alembic/versions/` is not an importable package and the file name starts with a digit, so the `0002` revision-chain test loads the migration by file path via `importlib.util` rather than `import_module`.
  - Suite green under `core/.venv` (Python 3.12): **20 passed** (existing 12 + new 8). Live `alembic upgrade head` / `alembic check` against real Postgres remains deferred to Epic 11 (not attempted).
  - Caveat for Epic 11 (from review): `include_schemas=True` has no `include_object`/`include_name` filter, so a live `alembic check`/autogenerate will reflect `public` + `information_schema` (which `target_metadata` doesn't declare) and report them as drift. Epic 11 must add a `platform`-only object filter when it wires the real-DB check.

## Epic 3 — Password hashing helper — **COMPLETED**
- **Goal:** A tiny, well-isolated module that hashes and verifies passwords with bcrypt, proven by a hash → verify round-trip test that also guards against the known passlib/bcrypt version-compatibility trap.
- **Rough scope:** A `hash_password` / `verify_password` pair behind one helper module; pin the compatible bcrypt/passlib versions in the runtime deps.
- **Open questions / decisions for stakeholders:** `passlib[bcrypt]` vs the `bcrypt` library directly (the TDD prefers passlib but names a direct fallback if pinning proves fragile).
- **Depends on:** none.
- **Implementation notes:**
  - **Decision: bcrypt directly, no passlib.** Took the TDD's pre-authorized fallback to sidestep the unmaintained-passlib version trap. Added `bcrypt==5.0.0` to `core/requirements.txt` (verified installable in the 3.12 venv).
  - New `core/app/auth/` package: `__init__.py` (package docstring marker) + `passwords.py` with `hash_password` / `verify_password`. `hash_password` uses `bcrypt.hashpw` over the UTF-8 password with a fresh `bcrypt.gensalt()`, returns a decoded `str`. `verify_password` calls `bcrypt.checkpw` and catches `ValueError` → returns `False` (corrupt stored hash reads as "no match", never a 500).
  - **72-byte limit — confirmed actual behavior:** pinned bcrypt 5.0.0 does NOT truncate; `hashpw` *raises* `ValueError` on >72-byte input. Documented in the module docstring. Note this means `verify_password`'s `except ValueError` also catches an over-long password (returns `False`); acceptable since seed/demo passwords are short.
  - Tests: `core/tests/test_passwords.py`, pure unit (no DB/Docker) — round-trip, wrong-password rejected, salt randomness, `$2b$` hash-shape trap-guard, malformed-hash → `False`. Full suite green: 25 passed (existing 20 + 5 new) under `core/.venv` (Python 3.12).

## Epic 4 — Pluggable AuthProvider (local password) — **COMPLETED**
- **Goal:** Introduce the pluggable authentication seam — an `AuthProvider` interface plus the MVP local implementation that looks up an active user by username, verifies the password, and returns an identity (or nothing, so failures stay generic).
- **Rough scope:** A small immutable `Identity` value, the `AuthProvider` Protocol, and `LocalPasswordAuthProvider` wired to the user model and the password helper. No OAuth/OIDC — the external-identity field on the model is the documented future seam only.
- **Open questions / decisions for stakeholders:** Whether the provider takes a DB session as an argument or resolves its own; how "active user" is filtered.
- **Depends on:** Epics 2, 3.
- **Implementation notes:**
  - New `core/app/auth/provider.py` holds all three pieces: `Identity` (`@dataclass(frozen=True)`: `user_id`, `tenant_id: uuid.UUID | None`, `role: Role`, `username`), the `AuthProvider` `typing.Protocol` (single `async authenticate(db, username, password) -> Identity | None`), and `LocalPasswordAuthProvider`.
  - `authenticate`: `select(User).where(User.username == username, User.is_active.is_(True))` → `scalar_one_or_none()`; no row → `None`; `verify_password` false → `None`; else returns `Identity`. Exact, case-sensitive username; `is_active = true` only; every miss returns `None` so failures stay generic (settled with stakeholder).
  - Reused `verify_password` (`auth/passwords.py`), `Role`/`User` (`models/user.py`), `AsyncSession` (type hint only). No `auth/__init__.py` change — submodule import path is consistent with how `passwords.py` is used.
  - Deliberately not built (named deferrals): no timing-attack mitigation / dummy-hash on unknown user (per TDD §7 brute-force-hardening deferral), no rate limiting, no case-insensitive matching.
  - Tests: `core/tests/test_provider.py`, pure unit (no DB/Docker) via a `FakeAsyncSession` whose `execute` returns a stub result yielding a chosen in-memory `User` or `None` — `Identity` frozen, happy path (real bcrypt hash via `hash_password`), wrong password → `None`, unknown/inactive (row is `None`) → `None`. Followed the suite's `asyncio_mode = auto` convention: async tests carry no `@pytest.mark.asyncio` decorator, matching `test_db.py`.
  - Full core suite green under `core/.venv` (Python 3.12): **29 passed** (existing 25 + 4 new).

## Epic 5 — Server-side sessions (create / resolve / revoke) — **COMPLETED**
- **Goal:** The session spine — issue an opaque token on login (stored only as its SHA-256 hash in `auth_sessions`), resolve a token back to the current identity, and revoke on logout — plus the cookie helpers that carry it.
- **Rough scope:** `create_session` / `get_session_identity` / `revoke_session` against the `auth_sessions` table; the `pf_session` httpOnly cookie (SameSite=Lax, Path, Secure-in-prod, Max-Age); new session-related settings (cookie-secure flag, lifetime).
- **Open questions / decisions for stakeholders:** Default session lifetime; exact cookie attribute defaults per environment (local HTTP vs prod HTTPS).
- **Depends on:** Epic 2.
- **Implementation notes:**
  - Settled decisions implemented: 8h default lifetime via `SESSION_LIFETIME_SECONDS` (28800s); cookie `Secure` default off, prod overrides via `SESSION_COOKIE_SECURE` (true on `"true"/"1"/"yes"`, case-insensitive).
  - The three session functions **commit themselves** (self-contained discrete operations), so Epic 8/12 callers don't manage the transaction.
  - `expires_at` is written from the app's UTC clock while resolution compares against the DB clock (`func.now()`) — acceptable because app and DB share one host/wall clock.
  - `_hash_token` keeps the SHA-256 prefix and lives as a private helper; the raw token is never stored.
  - `create_session(..., *, lifetime_seconds=None)` defaults to the configured lifetime; an explicit (incl. negative/past) value lets Epic 12 forge an already-expired session.
  - `SESSION_COOKIE_NAME = "pf_session"` is the single place the cookie name lives.
  - Backend-only: no route, no migration, no new dependency. Files: edited `core/app/config.py`; added `core/app/auth/sessions.py` and `core/tests/test_sessions.py`. Suite: 41 passed (29 prior green + 12 new), no live Postgres.

## Epic 6 — RBAC capability matrix — **COMPLETED**
- **Goal:** The single source of truth for authorization — the role enum, the capability enum (one per Requirements row), and the role → capabilities matrix — proven cell-by-cell against the normative table so the matrix can never silently drift.
- **Rough scope:** A declarative `rbac` module (`Role`, `Capability`, the `CAPABILITIES` dict, a `has_capability` check) plus an exhaustive unit test asserting every (role, capability) cell. No DB, no HTTP.
- **Open questions / decisions for stakeholders:** None expected — the matrix is transcribed verbatim from the Requirements §Authorization table in the TDD.
- **Depends on:** none.
- **Implementation notes:**
  - New `core/app/auth/rbac.py`: `Capability(StrEnum)` (10 members, values are the lowercase snake-case of each name), `CAPABILITIES: dict[Role, frozenset[Capability]]` transcribing the normative §Authorization table verbatim, and `has_capability(role, capability) -> bool` returning `capability in CAPABILITIES[role]`. Pure logic — no DB, no HTTP, no async, no migration, no new dependency.
  - **Reused `Role` (single source of truth):** `from ..models.user import Role`, not a second definition; re-exported via `__all__ = ["Role", "Capability", "CAPABILITIES", "has_capability"]` so callers can take both names from one place (honors the model docstring's directive).
  - Tests: `core/tests/test_rbac.py`, pure sync unit (no asyncio decorator, matching `test_models.py`). An **independent** `EXPECTED_CELLS` table (hand-transcribed, separate from the production dict) asserts all 40 (role, capability) cells via `has_capability`; plus completeness checks (all 4 roles keyed; every `Capability` covered by the expectation) and a `frozenset`-shape check on each matrix value.
  - Full core suite green under `core/.venv` (Python 3.12): **45 passed** (prior 41 + 4 new). No code changes outside the two new files.
  - Caveat (from review, non-blocking): the test proves the enum→table direction (every `Capability` is covered by the expectation) and asserts each cell, but does not assert the table→enum direction (that `CAPABILITIES` values contain only valid `Capability` members). The cell-by-cell + completeness checks already fail on any real drift; a `set().union(*CAPABILITIES.values()) <= set(Capability)` guard would close the remaining direction if a future epic wants belt-and-suspenders.

## Epic 7 — Auth dependencies (identity resolution + capability guard) — **COMPLETED**
- **Goal:** The reusable enforcement seam every protected endpoint will lean on — resolve the cookie to a current identity, reject the unauthenticated, and a `require_capability(...)` factory that returns the identity or a 403.
- **Rough scope:** A `dependencies` module composing the session resolver (Epic 5) and the matrix (Epic 6): `get_current_identity`, `require_authenticated`, and the `require_capability` dependency factory (401 when no session, 403 when the capability is missing).
- **Open questions / decisions for stakeholders:** Exact error bodies/shapes for 401 vs 403.
- **Depends on:** Epics 5, 6.
- **Implementation notes:**
  - New `core/app/auth/dependencies.py` holds all three dependencies and adds no new auth logic — it composes the existing pieces: `get_session_identity`/`SESSION_COOKIE_NAME` (Epic 5), `has_capability`/`Capability` (Epic 6), `Identity` (Epic 4), `get_db` (Epic 1). No re-declaration.
  - Phase 1: `get_current_identity(request, db=Depends(get_db))` reads `request.cookies.get(SESSION_COOKIE_NAME)` → `None` if absent, else `await get_session_identity(db, raw_token)`. `require_authenticated(identity=Depends(get_current_identity))` raises `HTTPException(401, "not authenticated")` when `None`, else returns the `Identity`.
  - Phase 2: `require_capability(capability)` is a factory returning a dependency that takes `identity=Depends(require_authenticated)` (so the 401 path is inherited for free), then raises `HTTPException(403, "insufficient permissions")` when `has_capability(identity.role, capability)` is `False`, else returns the `Identity`.
  - **Settled error bodies (stakeholder):** flat FastAPI shape — `401 {"detail": "not authenticated"}`, `403 {"detail": "insufficient permissions"}`; no `WWW-Authenticate` header.
  - **Naming note:** kept the plan's `get_current_identity` / `get_session_identity` names verbatim (reuse-from-one-place rule). The CLAUDE.md "resolve → get" guidance is already honored — these are `get_*`, not `resolve_*`; the prose word "resolve" stays only in docstrings to describe behavior.
  - Backend-only epic: no route mounting (Epic 8 mounts), no migration, no new runtime dependency, no frontend (HTML-id rule N/A).
  - Tests: `core/tests/test_dependencies.py`, pure unit (no DB/Docker) — a throwaway FastAPI app + `TestClient` with `app.dependency_overrides[get_db]` stubbed and `dependencies.get_session_identity` monkeypatched. Covers: no cookie → 401, token resolves → 200 identity, token does not resolve → 401, `get_current_identity` → `None` (not 401) without a cookie, and the guard's Tenant-Admin 200 / Agent 403 / no-session 401. Followed `asyncio_mode = auto` (no `@pytest.mark.asyncio`). Set cookies on the client instance (not per-request) to stay warning-clean.
  - Full core suite green under `core/.venv` (Python 3.12): **52 passed** (prior 45 + 7 new), no live Postgres.

## Epic 8 — Auth router (login / logout / me) — **COMPLETED**
- **Goal:** The HTTP surface for authentication — log in (authenticate, issue a session, set the cookie), log out (revoke + clear), and a `me` endpoint returning the current identity and capabilities — mounted on the app.
- **Rough scope:** A `auth` router with `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`, using the provider (Epic 4), sessions (Epic 5), and dependencies (Epic 7); mount it in the app. Login failures return a single generic 401 (never distinguishing unknown-user from bad-password).
- **Open questions / decisions for stakeholders:** The exact success-response body for login/`me` (which user fields + capability list shape).
- **Depends on:** Epics 4, 5, 7.
- **Implementation notes:**
  - New `core/app/auth/router.py`: `APIRouter(prefix="/api/auth")` composing the existing provider/sessions/dependencies/RBAC pieces — no new auth logic. `get_auth_provider()` dependency returns `LocalPasswordAuthProvider()` so tests override the seam via `dependency_overrides`. Shared `_identity_response(identity)` builds the body for both login and `me`: `{"user": {id, username, role, tenant_id}, "capabilities": [...]}` with capabilities = `sorted(c.value for c in CAPABILITIES[role])` (flat sorted strings). Raw `UUID`/`StrEnum` left for FastAPI's encoder.
  - Confirmed decisions honored: `me` mirrors login's body exactly; capabilities is a flat sorted array; login failure → single generic `401 {"detail": "invalid credentials"}`; `logout` → `200 {"detail": "logged out"}` (unguarded, idempotent revoke, always clears cookie).
  - Integration adjustment (Epic 5): `sessions.create_session` now takes `user_id: uuid.UUID` instead of `user: User` — sessions are keyed by user id and login already holds it on the `Identity`, avoiding a wasteful re-query. Updated docstring, body, the `uuid` import, and the 3 call sites in `test_sessions.py` (assertions unchanged).
  - Mounted in `main.py` via `app.include_router(auth_router)`.
  - Tests: new `core/tests/test_router.py` (6 pure-unit cases, no DB) — login success/failure, logout with/without cookie, `me` authed/unauthed. Full core suite: 58 passed (52 prior + 6 new), all green under `core/.venv`.

## Epic 9 — Guarded RBAC demonstrator (`GET /api/tenant/config`) — **COMPLETED**
- **Goal:** Prove the capability matrix end-to-end over HTTP against a real table — a Tenant-Admin-only endpoint that reads the session tenant's seeded config, with every other role rejected (403) and the anonymous caller rejected (401).
- **Rough scope:** A small `tenant` router exposing `GET /api/tenant/config` behind `require_capability(VIEW_TENANT_CONFIG)`, reading the current session's tenant row; mount it in the app.
- **Open questions / decisions for stakeholders:** Which minimal tenant fields the config view returns (name, slug — the seam P1.8 expands).
- **Depends on:** Epics 7, 8.
- **Implementation notes:**
  - Added `core/app/tenant/` package (`__init__.py` + `router.py`) and mounted `tenant_router` in `core/app/main.py` alongside health + auth.
  - `GET /api/tenant/config` guarded by `require_capability(Capability.VIEW_TENANT_CONFIG)`; reads the caller's own tenant via `select(Tenant).where(Tenant.id == identity.tenant_id)`. Body is the settled `{"tenant": {"id", "name", "slug"}}` envelope; raw `UUID` left for FastAPI's encoder.
  - Missing tenant handled defensively as `404 {"detail": "tenant not found"}` per the plan (effectively unreachable given the FK + tenantless-platform-admin CHECK).
  - `router.py` imports auth pieces as siblings (`..auth.dependencies`/`..auth.rbac`/`..auth.provider`) since `tenant` is a peer package of `auth`; no auth logic redeclared.
  - Tests (`core/tests/test_tenant_router.py`): pure-unit, override `get_current_identity` (so the real `require_capability` matrix runs) + `get_db` with a `FakeAsyncSession` mirroring `test_provider.py`. Covers Tenant Admin → 200 exact body; Agent / Read-Only / Platform Admin → 403; anonymous → 401.
  - Suite green: `core/.venv/Scripts/python -m pytest core/tests -q` → 63 passed (58 prior + 5 new), no live Postgres.

## Epic 10 — Seed the demo personas (2 tenants + 9 users) — **COMPLETED**
- **Goal:** Make the whole role matrix signable-in today — idempotently seed the two demo tenants and the nine demo users (two Agents, one Tenant Admin, one Read-Only per tenant, plus one global Platform Admin) on every boot.
- **Rough scope:** Extend the existing seed placeholder to insert-if-absent (keyed by slug / username), bcrypt-hashing a seed password read from config (dev default locally, SSM in prod); confirm the boot logs show the counts.
- **Open questions / decisions for stakeholders:** Final usernames/emails per persona; where the seed password default lives for local/test vs the prod SSM-injected value.
- **Depends on:** Epics 2, 3.
- **Implementation notes:**
  - **Username = email** — each persona's `username` and `email` hold the same email-style string; you log in with your email.
  - **Seed password** comes from new `Settings.seed_user_password` (`SEED_USER_PASSWORD`, dev/test default `"demo-password-change-me"`, prod injects via SSM). Added in `config.py` next to the `session_*` settings.
  - **Persona spec is pure module-level data** in `seed.py` (`DEMO_TENANTS`, `TENANT_EMAIL_DOMAINS`, `TENANT_USER_TEMPLATES`, `PLATFORM_ADMIN_EMAIL`) exposed via `demo_tenants()` / `demo_users_for(slug)` / `demo_user_specs()`, so the 2-tenant/9-user matrix is unit-testable without a session.
  - **Tenants:** `sunshine-senior-benefits` / "Sunshine Senior Benefits" (`@sunshine.example`), `florida-family-planning` / "Florida Family Planning" (`@florida.example`). Per tenant: `agent.one@`, `agent.two@` (AGENT), `admin@` (TENANT_ADMIN), `readonly@` (READ_ONLY); plus `platform.admin@policyflow.example` (PLATFORM_ADMIN, `tenant_id=None`).
  - **`async def seed(db)` is insert-if-absent:** reads existing slugs/usernames into sets, inserts missing tenants with an explicit `id=uuid.uuid4()` (queries back already-present tenant ids to link their users), inserts missing users with one shared `password_hash`, commits once, and logs inserted/already-present counts at INFO. Thin sync `run()` drives it via `session_factory()` + `asyncio.run`, preserving the `python -m app.seed` entrypoint.
  - **Tests** (`core/tests/test_seed.py`, 8 cases, pure unit, no Docker) reuse the `FakeAsyncSession`/`FakeResult` idiom — extended to replay multiple `execute` results in order and record `add`/`commit`. Cover spec correctness, empty→11 inserts with verifiable password, full→0 inserts, and partial→only-missing. Suite: **63 → 71 passed**.
  - Docs: `seed.py` docstring rewritten (placeholder framing dropped) and `core/README.md` "Migrations on boot" step 2 updated. No migration, no new dependency, no HTTP route (matches plan's out-of-scope).

## Epic 11 — Test substrate (ephemeral Postgres) — **COMPLETED**
- **Goal:** A real-database test foundation — a session-scoped ephemeral Postgres (testcontainers) that runs the migrations and a DB-backed HTTP client fixture — so the auth suite exercises real schemas, roles, and enums; skips gracefully when Docker is absent locally.
- **Rough scope:** Add `testcontainers` to the dev deps; a shared Postgres fixture + a DB-backed client fixture in the test conftest; a smoke test proving the fixture connects and migrations apply.
- **Open questions / decisions for stakeholders:** Container reuse strategy; the exact local skip signal when Docker is unavailable.
- **Depends on:** Epics 1, 2.
- **Implementation notes:**
  - **Deviation — Docker absent → FAIL ALWAYS (confirmed gate choice).** The container fixtures have no skip logic or exception handling, so a missing Docker daemon errors every DB test rather than skipping. This deliberately overrides this epic's written "skips gracefully when Docker is absent locally" goal, per the approved plan's gate decision.
  - **Image / scope:** `postgres:16-alpine` (matches `docker-compose.yml`), session-scoped `postgres_container` (boots once per `pytest` run, torn down at end).
  - **Wiring:** `database_engine` points `DATABASE_URL` at the container, runs `alembic upgrade head` via `alembic.command.upgrade` (env.py rewrites the scheme to sync psycopg), then yields an asyncpg async engine. `db_session` (function-scoped) yields a real `AsyncSession`; `db_client` overrides `app.dependency_overrides[get_db]` to a container-backed session and cleans it up after — the seams Epics 12/13 build on.
  - **`NullPool` on the test async engine** (deviation from `app.db`, which pools): with pytest-asyncio's function-scoped event loop, a pooled asyncpg connection from a finished loop fails on teardown on Windows ("proactor NoneType has no attribute send"). Opening a fresh connection per session sidesteps it without changing observable behavior.
  - **Migration bug fixed (out-of-scope but blocking) — backlog-worthy.** The substrate immediately caught that `0002_platform_identity.py` used the **generic** `sa.Enum(..., create_type=False)`; `create_type` is a PostgreSQL-specific `ENUM` keyword and is silently ignored on the generic type, so the `users` table create auto-emitted a second `CREATE TYPE` and `upgrade head` failed against real Postgres with "type user_role already exists" — the migration had never been applied live before this epic. Fixed minimally by switching that one enum to `sqlalchemy.dialects.postgresql.ENUM` so `create_type=False` is honored. This is the exact class of defect this epic exists to surface; flagging for reviewer awareness since Epic 11 was nominally "no migration changes".
  - `testcontainers[postgres]==4.14.2` pinned in `core/requirements-dev.txt` (stays out of the runtime image).
  - **Smoke tests** (`core/tests/test_substrate.py`): migrations created the three `platform` tables + the `user_role` enum; a tenant write/read round-trip through `db_session`; `db_client` reaches a DB-touching guarded path (`GET /api/tenant/config` no cookie → 401).
  - Suite: `core/.venv/Scripts/python -m pytest core/tests -q` → **74 passed** (71 prior + 3 new), real container boots, migrations apply.
  - Review verdict **Approve with nits** (no changes required). Non-blocking suggestions captured as deferred, none implemented this epic: migration fix ideally its own commit (acceptable bundled, already noted above); no per-test DB rollback isolation — flagged for Epic 12; duplicated `async_sessionmaker` between `app.db` and the test engine (DRY cleanup); `database_engine` never calls `engine.dispose()` on teardown; `container.port` is an undocumented testcontainers attribute.

## Epic 12 — Session & provider lifecycle tests — **COMPLETED**
- **Goal:** Prove the auth internals against a real database — session create → resolve → revoke, an expired session not resolving, and provider authentication succeeding/failing on the right inputs.
- **Rough scope:** DB-backed tests over the sessions module (Epic 5) and the provider (Epic 4) using the substrate; no HTTP layer yet.
- **Open questions / decisions for stakeholders:** Which expiry/revocation edge cases to cover beyond the happy path.
- **Depends on:** Epics 4, 5, 11.
- **Implementation notes:**
  - Test-only epic as planned: no production code, migration, dependency, or HTTP layer touched. Three new files under `core/tests/`, all green.
  - **New `factories.py` → `insert_active_user`**: seeds a committed `User` (real `hash_password` bcrypt hash) plus its `Tenant`, isolated by `uuid`-suffixed username/email/slug (no rollback fixture, per settled decision). `flush()` (not commit) the tenant first to get its id, then commit the user. Skips the tenant for `PLATFORM_ADMIN` to honor the `platform_admin_tenantless` CHECK. Default `password="correct horse battery staple"` returned to the caller via the known plaintext.
  - **`test_sessions_db.py`** (5 tests): happy-path create→resolve identity match; expired (`lifetime_seconds=-1`) → `None`; revoked → `None`; unknown token → `None`; double-revoke + unknown-token revoke are no-ops.
  - **`test_provider_db.py`** (5 tests): success identity match; wrong password / unknown username / inactive user / upper-cased (case-sensitive) username all → `None`.
  - Per the plan + `pytest.ini` `asyncio_mode = auto`, the new async tests carry **no** `@pytest.mark.asyncio` decorator (note: the older `test_substrate.py` still uses the decorator; not touched, out of scope).
  - Suite: `core/.venv/Scripts/python -m pytest core/tests -q` → **84 passed** (74 prior + 10 new), real container boots, migrations apply. No guesses, no failures, nothing blocked.

## Epic 13 — Endpoint enforcement tests (per-role, end-to-end) — **COMPLETED**
- **Goal:** Lock down the HTTP contract — login success/failure, `me` authed/unauthed/revoked, `/api/tenant/config` returning 200 for Tenant Admin and 403/401 for everyone else, and logout revoking the session.
- **Rough scope:** Endpoint tests driving the real routers (Epics 8, 9) against seeded users (Epic 10) over the DB-backed client (Epic 11).
- **Open questions / decisions for stakeholders:** None expected — the cases are enumerated in the TDD's verification section.
- **Depends on:** Epics 8, 9, 10, 11.
- **Implementation notes:**
  - Test-only epic: one new file `core/tests/test_endpoints_db.py`, 11 cases, zero production-code change. Full core suite: 84 → 95 passed.
  - Used the real `seed()` + real personas via a local function-scoped `seeded` fixture (idempotent); `conftest.py` untouched. Picked personas by role from `demo_user_specs()` via `email_for_role`; logged in with `settings.seed_user_password`. No `insert_active_user` factory.
  - Added a small `tenant_slug_for_role` helper (alongside `email_for_role`) so the Tenant-Admin 200 case asserts the returned slug against the persona's seeded tenant, rather than hardcoding a slug — robust to seed edits.
  - Asserted exact 401/403 detail bodies (`"invalid credentials"`, `"not authenticated"`, `"insufficient permissions"`) and verified the `pf_session` cookie is set on login; matched the `_db.py` siblings' style with no `@pytest.mark.asyncio` decorator.

## Epic 14 — CI: Postgres/Docker for the DB suite — **COMPLETED**
- **Goal:** Keep the new DB-backed suite inside the commit gate everywhere — ensure GitHub Actions and CodeBuild provide Postgres/Docker so the auth integration tests always run in CI (not just skip locally), and the gate stays green before P1.2 begins.
- **Rough scope:** Wire a Postgres service or Docker-in-job into the existing GitHub Actions workflow and confirm CodeBuild's `pre_build` can run testcontainers; no app code.
- **Open questions / decisions for stakeholders:** GHA approach — a `services: postgres` container vs Docker-in-job for testcontainers; confirm CodeBuild's Docker availability covers the test phase.
- **Depends on:** Epics 11, 13.
- **Implementation notes:**
  - CI config only — no app/test code, no Terraform change. Chose **Docker-in-job, not `services: postgres`** (stakeholder-confirmed): the substrate always boots its own ephemeral Postgres via testcontainers and ignores any external `DATABASE_URL`, so a sidecar would be unused.
  - Phase 1 (`.github/workflows/tests.yml`, `backend` job): added a `docker info` step before the pytest run so a runner without reachable Docker fails fast (honoring Epic 11's "fail, never skip"); pytest command unchanged. Added comments documenting the Docker-in-job decision and why no `services: postgres`.
  - Phase 2 (`ops/buildspec.yml`, `pre_build`): added a bounded wait-for-Docker guard `timeout 60 sh -c 'until docker info >/dev/null 2>&1; do sleep 1; done'` before pytest, removing provisioning-race fragility. `testcontainers` already installed via `core/requirements-dev.txt`; existing `pip install` covers it. Added comments.
  - Confirmed `privileged_mode = true` already set at `infra/codebuild.tf:138` — no Terraform edit needed.
  - Did NOT add `TESTCONTAINERS_RYUK_DISABLED` or any env that would diverge CI from local.
