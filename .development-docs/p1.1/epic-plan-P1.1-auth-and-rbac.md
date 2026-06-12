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

## Epic 4 — Pluggable AuthProvider (local password)
- **Goal:** Introduce the pluggable authentication seam — an `AuthProvider` interface plus the MVP local implementation that looks up an active user by username, verifies the password, and returns an identity (or nothing, so failures stay generic).
- **Rough scope:** A small immutable `Identity` value, the `AuthProvider` Protocol, and `LocalPasswordAuthProvider` wired to the user model and the password helper. No OAuth/OIDC — the external-identity field on the model is the documented future seam only.
- **Open questions / decisions for stakeholders:** Whether the provider takes a DB session as an argument or resolves its own; how "active user" is filtered.
- **Depends on:** Epics 2, 3.
- **Implementation notes:** _none yet_

## Epic 5 — Server-side sessions (create / resolve / revoke)
- **Goal:** The session spine — issue an opaque token on login (stored only as its SHA-256 hash in `auth_sessions`), resolve a token back to the current identity, and revoke on logout — plus the cookie helpers that carry it.
- **Rough scope:** `create_session` / `get_session_identity` / `revoke_session` against the `auth_sessions` table; the `pf_session` httpOnly cookie (SameSite=Lax, Path, Secure-in-prod, Max-Age); new session-related settings (cookie-secure flag, lifetime).
- **Open questions / decisions for stakeholders:** Default session lifetime; exact cookie attribute defaults per environment (local HTTP vs prod HTTPS).
- **Depends on:** Epic 2.
- **Implementation notes:** _none yet_

## Epic 6 — RBAC capability matrix
- **Goal:** The single source of truth for authorization — the role enum, the capability enum (one per Requirements row), and the role → capabilities matrix — proven cell-by-cell against the normative table so the matrix can never silently drift.
- **Rough scope:** A declarative `rbac` module (`Role`, `Capability`, the `CAPABILITIES` dict, a `has_capability` check) plus an exhaustive unit test asserting every (role, capability) cell. No DB, no HTTP.
- **Open questions / decisions for stakeholders:** None expected — the matrix is transcribed verbatim from the Requirements §Authorization table in the TDD.
- **Depends on:** none.
- **Implementation notes:** _none yet_

## Epic 7 — Auth dependencies (identity resolution + capability guard)
- **Goal:** The reusable enforcement seam every protected endpoint will lean on — resolve the cookie to a current identity, reject the unauthenticated, and a `require_capability(...)` factory that returns the identity or a 403.
- **Rough scope:** A `dependencies` module composing the session resolver (Epic 5) and the matrix (Epic 6): `get_current_identity`, `require_authenticated`, and the `require_capability` dependency factory (401 when no session, 403 when the capability is missing).
- **Open questions / decisions for stakeholders:** Exact error bodies/shapes for 401 vs 403.
- **Depends on:** Epics 5, 6.
- **Implementation notes:** _none yet_

## Epic 8 — Auth router (login / logout / me)
- **Goal:** The HTTP surface for authentication — log in (authenticate, issue a session, set the cookie), log out (revoke + clear), and a `me` endpoint returning the current identity and capabilities — mounted on the app.
- **Rough scope:** A `auth` router with `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`, using the provider (Epic 4), sessions (Epic 5), and dependencies (Epic 7); mount it in the app. Login failures return a single generic 401 (never distinguishing unknown-user from bad-password).
- **Open questions / decisions for stakeholders:** The exact success-response body for login/`me` (which user fields + capability list shape).
- **Depends on:** Epics 4, 5, 7.
- **Implementation notes:** _none yet_

## Epic 9 — Guarded RBAC demonstrator (`GET /api/tenant/config`)
- **Goal:** Prove the capability matrix end-to-end over HTTP against a real table — a Tenant-Admin-only endpoint that reads the session tenant's seeded config, with every other role rejected (403) and the anonymous caller rejected (401).
- **Rough scope:** A small `tenant` router exposing `GET /api/tenant/config` behind `require_capability(VIEW_TENANT_CONFIG)`, reading the current session's tenant row; mount it in the app.
- **Open questions / decisions for stakeholders:** Which minimal tenant fields the config view returns (name, slug — the seam P1.8 expands).
- **Depends on:** Epics 7, 8.
- **Implementation notes:** _none yet_

## Epic 10 — Seed the demo personas (2 tenants + 9 users)
- **Goal:** Make the whole role matrix signable-in today — idempotently seed the two demo tenants and the nine demo users (two Agents, one Tenant Admin, one Read-Only per tenant, plus one global Platform Admin) on every boot.
- **Rough scope:** Extend the existing seed placeholder to insert-if-absent (keyed by slug / username), bcrypt-hashing a seed password read from config (dev default locally, SSM in prod); confirm the boot logs show the counts.
- **Open questions / decisions for stakeholders:** Final usernames/emails per persona; where the seed password default lives for local/test vs the prod SSM-injected value.
- **Depends on:** Epics 2, 3.
- **Implementation notes:** _none yet_

## Epic 11 — Test substrate (ephemeral Postgres)
- **Goal:** A real-database test foundation — a session-scoped ephemeral Postgres (testcontainers) that runs the migrations and a DB-backed HTTP client fixture — so the auth suite exercises real schemas, roles, and enums; skips gracefully when Docker is absent locally.
- **Rough scope:** Add `testcontainers` to the dev deps; a shared Postgres fixture + a DB-backed client fixture in the test conftest; a smoke test proving the fixture connects and migrations apply.
- **Open questions / decisions for stakeholders:** Container reuse strategy; the exact local skip signal when Docker is unavailable.
- **Depends on:** Epics 1, 2.
- **Implementation notes:** _none yet_

## Epic 12 — Session & provider lifecycle tests
- **Goal:** Prove the auth internals against a real database — session create → resolve → revoke, an expired session not resolving, and provider authentication succeeding/failing on the right inputs.
- **Rough scope:** DB-backed tests over the sessions module (Epic 5) and the provider (Epic 4) using the substrate; no HTTP layer yet.
- **Open questions / decisions for stakeholders:** Which expiry/revocation edge cases to cover beyond the happy path.
- **Depends on:** Epics 4, 5, 11.
- **Implementation notes:** _none yet_

## Epic 13 — Endpoint enforcement tests (per-role, end-to-end)
- **Goal:** Lock down the HTTP contract — login success/failure, `me` authed/unauthed/revoked, `/api/tenant/config` returning 200 for Tenant Admin and 403/401 for everyone else, and logout revoking the session.
- **Rough scope:** Endpoint tests driving the real routers (Epics 8, 9) against seeded users (Epic 10) over the DB-backed client (Epic 11).
- **Open questions / decisions for stakeholders:** None expected — the cases are enumerated in the TDD's verification section.
- **Depends on:** Epics 8, 9, 10, 11.
- **Implementation notes:** _none yet_

## Epic 14 — CI: Postgres/Docker for the DB suite
- **Goal:** Keep the new DB-backed suite inside the commit gate everywhere — ensure GitHub Actions and CodeBuild provide Postgres/Docker so the auth integration tests always run in CI (not just skip locally), and the gate stays green before P1.2 begins.
- **Rough scope:** Wire a Postgres service or Docker-in-job into the existing GitHub Actions workflow and confirm CodeBuild's `pre_build` can run testcontainers; no app code.
- **Open questions / decisions for stakeholders:** GHA approach — a `services: postgres` container vs Docker-in-job for testcontainers; confirm CodeBuild's Docker availability covers the test phase.
- **Depends on:** Epics 11, 13.
- **Implementation notes:** _none yet_
