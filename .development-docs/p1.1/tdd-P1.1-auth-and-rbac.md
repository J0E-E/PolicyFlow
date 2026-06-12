# P1.1 — Authentication & RBAC — Technical Design Document

## 1. Summary

Stand up the platform's authentication and authorization spine: username/password
login behind a pluggable `AuthProvider`, an authenticated **server-side session**
(httpOnly cookie → a `platform.auth_sessions` row) that is the *only* source of
identity, tenant context, and role, and a **fixed RBAC capability matrix** enforced
server-side on every protected request. This is the first phase with real database
tables, so it also introduces the SQLAlchemy (async) ORM over the existing Alembic
wiring and creates the shared `platform` schema (which P0 reserved) holding
`tenants`, `users`, and `auth_sessions`. Nine demo-persona users are seeded so the
whole role matrix is signable-in and testable today. There is **no UI** (login screen,
role switcher, and auto-login are P1.6) and **no tenant data-isolation plumbing**
(`search_path`/DB-role injection is P1.2); P1.1 stops at resolving a session to
`(user, tenant_id, role)` and enforcing capabilities. Tests run against an **ephemeral
Postgres** (testcontainers) so the suite exercises real schemas, roles, and enums —
the substrate P1.2's cross-tenant isolation proof will need.

## 2. Business Requirements

Lifted from `program-and-phase-plan.md` → **P1.1** (lines 193–207) and the
**Security Requirements** of `PolicyFlow_Requirements.md` (§Authentication,
§Authorization):

- Authentication behind a **pluggable `AuthProvider`** interface. MVP ships
  username/password with **session/JWT issuance**; the user model carries an
  **external-identity** field so OIDC can be added later without schema/API changes.
  **No OAuth/OIDC flow is built.**
- **Fixed, platform-defined RBAC roles** — Agent, Tenant Admin, Read-Only, Platform
  Admin — enforced **server-side on every API request from Phase 1 onward**. The
  capability matrix (Requirements §Authorization) is normative.
- Seeded users can sign in; each role's capability matrix is enforced server-side and
  verifiable by test; unauthorized and unauthenticated calls are rejected.
- **Tenant context is derived only from the authenticated session** — never a request
  parameter (Decide-Once #4). Platform Admin operates **outside tenant scope**.
- Seeded demo users (per the Demo Access Model): per tenant **two Agents, one Tenant
  Admin, one Read-Only**; plus **one global Platform Admin** — nine users total.
- **Ownership rule:** assignment governs task routing/dashboards, **not visibility**;
  all agents in a tenant can view all tenant records. (No owner-scoped visibility.)

## 3. Goals / Non-Goals

**Goals**
- A pluggable `AuthProvider` Protocol + a local password-verifying implementation;
  bcrypt password hashing.
- Server-side session issuance: login creates a session row and sets an httpOnly
  cookie; logout revokes it; sessions expire.
- A FastAPI dependency that resolves the current session to a `CurrentIdentity`
  (`user_id`, `tenant_id`, `role`) — the single source of identity/tenant/role.
- A declarative RBAC capability matrix mirroring Requirements §Authorization, plus a
  reusable `require_capability(...)` enforcement seam, proven on a real guarded
  endpoint and exhaustively unit-tested against the matrix.
- First real schema: `platform` schema with `tenants`, `users`, `auth_sessions`;
  SQLAlchemy async ORM + Alembic migration `0002`; idempotent seed of 2 tenants + 9
  users.
- `pytest` suite (login, session lifecycle, full role matrix, endpoint enforcement)
  behind the existing pre-commit gate, running against an ephemeral Postgres.

**Non-Goals** (owned by later phases — each named)
- **Schema-per-tenant `search_path` / per-tenant DB-role injection** and cross-tenant
  isolation tests → **P1.2**. P1.1 records `tenant_id` on the session and stops there;
  all P1.1 queries run as the app's default role against the `platform` schema.
- **Login UI, role-switcher, auto-login demo access** → **P1.6**. P1.1 is exercised
  via API + tests only.
- **Auditing** of auth events / role-assignment changes / PII reveals → **P1.4**.
  P1.1 leaves a clearly-named emission seam and emits nothing.
- **Field-level PII encryption / blind index / masking** → **P1.3**;
  **events / outbox** → **P1.5**; **full seed data** → **P1.8**.
- **Real OAuth/OIDC** — out of project scope (seam documented only).
- **Login brute-force rate limiting / lockout** — not required by P1.1 (intake abuse
  controls are P1.7); noted as a future hardening seam.
- **Session-level `assumed_role`** for persona switching → **P1.6** (P1.1's effective
  role derives directly from the authenticated user).

## 4. Current State

- **Core app** — [core/app/main.py](../../core/app/main.py) is a bare FastAPI app
  mounting only the health router; [core/app/health.py](../../core/app/health.py)
  exposes `GET /api/health`. Settings read from the environment in
  [core/app/config.py](../../core/app/config.py) (`DATABASE_URL`, `RABBITMQ_URL`,
  `APP_VERSION`). **No ORM, no auth, no domain tables.** Python 3.12.
- **Database access** — health probes use **raw `asyncpg`**
  ([core/app/health.py](../../core/app/health.py)); there is **no SQLAlchemy** yet.
  Runtime deps in [core/requirements.txt](../../core/requirements.txt) (FastAPI,
  asyncpg, aio-pika, alembic, psycopg).
- **Migrations** — Alembic wired with a single empty baseline
  ([core/alembic/versions/0001_empty_baseline.py](../../core/alembic/versions/0001_empty_baseline.py));
  [core/alembic/env.py](../../core/alembic/env.py) rewrites the asyncpg URL to
  `postgresql+psycopg://` for sync migrations and has `target_metadata = None`. The
  `platform` schema is **reserved but not created**.
- **Boot sequence** — [core/entrypoint.sh](../../core/entrypoint.sh) runs
  `alembic upgrade head` → `python -m app.seed` → uvicorn. The seed
  ([core/app/seed.py](../../core/app/seed.py)) is a logging placeholder (the seam this
  phase begins filling).
- **Tests** — [core/tests/conftest.py](../../core/tests/conftest.py) provides an
  `httpx.ASGITransport` client against `app.main:app`;
  [core/tests/test_health.py](../../core/tests/test_health.py) tests are **mock-based,
  no DB**. Dev deps in [core/requirements-dev.txt](../../core/requirements-dev.txt)
  (`pytest`, `httpx`, `pytest-asyncio`). The pre-commit gate
  ([.pre-commit-config.yaml](../../.pre-commit-config.yaml)) runs both suites and
  blocks red; CI mirrors it ([ops/buildspec.yml](../../ops/buildspec.yml) `pre_build`,
  [.github/workflows/tests.yml](../../.github/workflows/tests.yml)).
- **Frontend** — SPA shell only; **untouched by this phase.**
- **Constraints** — `CLAUDE.md`: descriptive naming (no `cfg`/`req`/`res`/`e`/`usr`),
  booleans read as yes/no questions, natural-language verbs (`get`/`create`/`run`),
  many small focused modules. Memory: minimal-churn insertion-style doc edits; dev is
  the local Docker stack, prod on EC2.

## 5. Proposed Design

### High-level approach
A small, layered auth package inside the existing core service. The browser holds an
**opaque session token** in an httpOnly cookie; the server hashes it to find an
`auth_sessions` row, which points at a `users` row carrying `tenant_id` and `role`.
A FastAPI dependency turns that into a `CurrentIdentity`; `require_capability(...)`
checks the role's capabilities against a declarative matrix. Login authenticates
through an `AuthProvider` (local password impl now). All of this lives in the shared
`platform` schema and is tenant-agnostic by design — because login happens *before*
tenant context exists, the identity store must be reachable without a tenant.

**Diagram:** [login → session → RBAC sequence](./diagrams/tdd-P1.1-auth-and-rbac-flow.excalidraw)
(SPA → `/api/auth/login` → session issue + cookie → guarded request →
`require_capability` → identity).

### Components added (core service)

```
core/app/
  db.py                 # async engine + async_sessionmaker + DeclarativeBase
  models/
    __init__.py
    tenant.py           # Tenant
    user.py             # User + Role enum
    auth_session.py     # AuthSession
  auth/
    __init__.py
    passwords.py        # hash_password / verify_password (passlib[bcrypt])
    provider.py         # AuthProvider Protocol, Identity, LocalPasswordAuthProvider
    sessions.py         # create / resolve / revoke session + cookie helpers
    rbac.py             # Role, Capability, CAPABILITIES matrix, has_capability
    dependencies.py     # get_current_identity, require_authenticated, require_capability
    router.py           # POST /api/auth/login, POST /api/auth/logout, GET /api/auth/me
  tenant/
    __init__.py
    router.py           # GET /api/tenant/config  (guarded RBAC demonstrator)
  seed.py               # extended: idempotently seed 2 tenants + 9 users
  main.py               # mount auth_router + tenant_router
```

### Data model changes — Alembic migration `0002` (all in the `platform` schema)

`0002` creates the schema then three tables (hand-written DDL, matching the
hand-written baseline style; `target_metadata` is also pointed at the ORM `Base` so
future autogenerate/`alembic check` can catch drift).

- **`platform.tenants`** — `id` UUID PK, `slug` text unique (e.g.
  `sunshine-senior-benefits`), `name` text, `created_at` timestamptz. Seeded with the
  two demo tenants. *(P1.2 extends this registry with schema-name / DB-role mapping.)*
- **`platform.users`** — `id` UUID PK; `tenant_id` UUID FK → `tenants.id`
  **NULLable** (NULL only for Platform Admin); `username` text **unique** (global, as
  login is pre-tenant); `email` text; `password_hash` text; `role`
  `platform.user_role` enum (`agent` | `tenant_admin` | `read_only` |
  `platform_admin`); `external_identity` text **nullable** (the OIDC seam);
  `is_active` boolean default true; `created_at` timestamptz. **CHECK constraint:**
  `role = 'platform_admin'` ⇔ `tenant_id IS NULL` (Platform Admin is tenantless; every
  other role must have a tenant).
- **`platform.auth_sessions`** — `id` UUID PK; `token_hash` text **unique** (SHA-256 of
  the opaque cookie token — the raw token is never stored); `user_id` UUID FK →
  `users.id` (`ON DELETE CASCADE`); `created_at` timestamptz; `expires_at` timestamptz;
  `revoked_at` timestamptz **nullable**. A session is valid iff `revoked_at IS NULL`
  and `expires_at > now()`.

`id` is UUID (surrogate, production-minded) with a human-readable `slug` on tenants.

### Interfaces

**`AuthProvider` (provider.py)** — the pluggable seam:
```python
@dataclass(frozen=True)
class Identity:
    user_id: UUID
    tenant_id: UUID | None
    role: Role
    username: str

class AuthProvider(Protocol):
    async def authenticate(self, username: str, password: str) -> Identity | None: ...

class LocalPasswordAuthProvider:           # the MVP implementation
    async def authenticate(self, username, password) -> Identity | None:
        # look up active user by username; verify_password(...); return Identity or None
```
A later `OIDCAuthProvider` implements the same Protocol and maps `external_identity`;
no API/schema change. Authentication failures return `None` → a generic 401 (never
distinguishing unknown-user from bad-password).

**Sessions (sessions.py)**
- `create_session(db, user, *, lifetime) -> raw_token` — insert a row with
  `token_hash = sha256(raw_token)`; return the raw token (set as the cookie).
- `get_session_identity(db, raw_token) -> CurrentIdentity | None` — hash, look up a
  valid (unrevoked, unexpired) row, join the user, return identity or `None`.
- `revoke_session(db, raw_token)` — set `revoked_at = now()`.
- Cookie: name `pf_session`, **httpOnly**, **SameSite=Lax**, `Path=/`, `Secure` in
  prod (driven by a setting), `Max-Age` = session lifetime.

**RBAC (rbac.py)**
- `class Role(StrEnum)`: `AGENT`, `TENANT_ADMIN`, `READ_ONLY`, `PLATFORM_ADMIN`.
- `class Capability(StrEnum)` — one per Requirements §Authorization row:
  `VIEW_TENANT_RECORDS`, `CREATE_EDIT_RECORDS`, `CLAIM_LEADS_MANAGE_TASKS`,
  `REASSIGN_LEADS_TASKS`, `REVEAL_PII`, `REPLAY_DISCARD_DLQ`, `VIEW_TENANT_CONFIG`,
  `VIEW_AUDIT_LOGS`, `VIEW_DASHBOARDS`, `PLATFORM_HEALTH_DEMO_CONTROLS`.
- `CAPABILITIES: dict[Role, frozenset[Capability]]` — the literal transcription of the
  matrix below; `has_capability(role, capability) -> bool`. This dict is the
  **single source of truth** and is asserted cell-by-cell in tests.

| Capability | Agent | Tenant Admin | Read-Only | Platform Admin |
|---|---|---|---|---|
| `VIEW_TENANT_RECORDS` | ✓ | ✓ | ✓ | — |
| `CREATE_EDIT_RECORDS` | ✓ | ✓ | — | — |
| `CLAIM_LEADS_MANAGE_TASKS` | ✓ | ✓ | — | — |
| `REASSIGN_LEADS_TASKS` | — | ✓ | — | — |
| `REVEAL_PII` | ✓ | ✓ | — | — |
| `REPLAY_DISCARD_DLQ` | — | ✓ | — | ✓ |
| `VIEW_TENANT_CONFIG` | — | ✓ | — | — |
| `VIEW_AUDIT_LOGS` | — | ✓ | ✓ | — |
| `VIEW_DASHBOARDS` | ✓ | ✓ | ✓ | — |
| `PLATFORM_HEALTH_DEMO_CONTROLS` | — | — | — | ✓ |

*(Read-Only's record view is "PII masked, no reveal"; the masking render layer is
P1.3 — at P1.1 the capability bit is the enforcement surface.)*

**Dependencies (dependencies.py)**
- `get_current_identity(request, db) -> CurrentIdentity | None` — read cookie →
  `get_session_identity`.
- `require_authenticated -> CurrentIdentity` — 401 if no valid session.
- `require_capability(capability) -> Callable[..., CurrentIdentity]` — a dependency
  factory: resolves identity (401 if none), checks `has_capability` (403 if missing),
  returns the identity.

**HTTP endpoints**
- `POST /api/auth/login` — body `{username, password}` → on success: create session,
  `Set-Cookie`, `200 {user: {id, username, role, tenant_id}, capabilities: [...]}`; on
  failure: `401 {detail: "invalid credentials"}` (generic).
- `POST /api/auth/logout` — revoke session, clear cookie, `200`.
- `GET /api/auth/me` — `require_authenticated` → `200` identity + capability list;
  `401` if unauthenticated/expired/revoked. (The SPA consumes this in P1.6.)
- `GET /api/tenant/config` — **guarded RBAC demonstrator**:
  `require_capability(VIEW_TENANT_CONFIG)` → returns the session tenant's seeded
  read-only config (name, slug — the minimal config-view seam P1.8 expands). Only
  **Tenant Admin** passes; Agent / Read-Only / Platform Admin → 403; unauthenticated →
  401. This proves the matrix end-to-end over HTTP against a real table.

### Seed (seed.py, idempotent — runs after migrations on every boot)
Insert-if-absent (keyed by `slug` / `username`):
- **Tenants:** `sunshine-senior-benefits` (Sunshine Senior Benefits),
  `florida-family-planning` (Florida Family Planning).
- **Users (9):** per tenant `agent.one@…`, `agent.two@…`, `admin@…`, `readonly@…`
  (`@sunshine.example` / `@florida.example`); plus `platform.admin@policyflow.example`
  (tenant_id NULL). All share a seed password read from `SEED_USER_PASSWORD` (dev
  default for local/test; **prod injects via SSM**), bcrypt-hashed at seed time.

### Engine / config additions
- `core/app/db.py` — async engine from `DATABASE_URL` (asyncpg), `async_sessionmaker`,
  a request-scoped `get_db` dependency, `DeclarativeBase`.
- `config.py` — add `session_cookie_secure: bool` (true in prod), `session_lifetime`,
  `seed_user_password`.
- `requirements.txt` — add `sqlalchemy[asyncio]`, `passlib[bcrypt]`.
- `alembic/env.py` — set `target_metadata = Base.metadata` and enable
  `include_schemas=True` (autogenerate/`alembic check` support; `0002` stays
  hand-written).

### Primary flow — login then a guarded request
```
SPA ──POST /api/auth/login {username,password}──▶ core
        AuthProvider.authenticate ─ verify bcrypt hash ─ users row (platform schema)
        create_session ─ insert auth_sessions(token_hash=sha256(token))
   ◀── 200 + Set-Cookie: pf_session=<token>; HttpOnly; SameSite=Lax
SPA ──GET /api/tenant/config  (Cookie: pf_session)──▶ core
        get_current_identity ─ get_session_identity(token) ─ CurrentIdentity(user,tenant,role)
        require_capability(VIEW_TENANT_CONFIG) ─ has_capability(role, cap)?
            ├─ no  ─▶ 403
            └─ yes ─▶ 200 tenant config
   (no cookie / expired / revoked ─▶ 401)
```

## 6. Decisions

| # | Decision | Chosen | Alternatives considered | Rationale |
|---|---|---|---|---|
| A | Session mechanism | **Opaque server-side session** (httpOnly cookie → `platform.auth_sessions`, token stored as SHA-256) | Stateless JWT in cookie | Trivial revocation/logout; P1.6's role-switch becomes a row update; no signing-key secret to manage; Postgres already present, no Redis in the stack. |
| B | Identity store location | **`platform.users` now**, with a nullable `tenant_id` column | Throwaway `public` table moved in P1.2 | Login is inherently pre-tenant-context, so the auth lookup must be tenant-agnostic; `platform` schema is its permanent home and avoids a P1.2 migration. |
| C | RBAC enforcement style | **Declarative capability matrix + FastAPI `require_capability(...)` dependency** | Central route→capability middleware table | Idiomatic FastAPI, per-route explicit, directly unit-testable; the matrix dict is the single source of truth. |
| D | Seed scope | **Full 9 demo personas** with a fixed seed password | Minimal subset now, full set in P1.8 | The entire role matrix is signable-in and testable today; matches the Demo Access Model exactly. |
| E | Password hashing | **bcrypt via `passlib[bcrypt]`** | argon2id | Universally understood, well-supported; sufficient for a demo. (Version-pin caveat in Risks.) |
| F | ORM | **SQLAlchemy 2.0 async** (asyncpg) over existing Alembic | Raw asyncpg / SQLModel | First real schema; async matches FastAPI; Alembic already wired; the program's reuse list names SQLAlchemy + Alembic. |
| G | Test database | **Ephemeral Postgres via testcontainers** (session-scoped, reused; skips locally if Docker absent, always runs in CI) | Mock/SQLite; DB tests CI-only; shared local/CI Postgres URL | Real schemas/roles/enums = parity with prod and the substrate P1.2's isolation tests need; keeps the auth integration tests inside the commit gate. |
| H | `tenants` registry | **Create minimal `platform.tenants` now** (id, slug, name) | Hard-code tenant ids; defer table to P1.2 | `users.tenant_id` needs a real referent; the registry is platform-level reference data; P1.2 extends it with schema/role mapping. |
| I | RBAC demonstrator endpoint | **`GET /api/tenant/config`** (Tenant-Admin-only, reads the seeded tenant) | A synthetic placeholder route; tests-only | A real, requirement-backed endpoint (read-only tenant config view) exercises single-role enforcement over HTTP without inventing domain entities. |

## 7. Risks and Open Questions

- **`passlib` + `bcrypt` version compatibility.** Recent `bcrypt` releases broke
  `passlib`'s backend detection (a noisy warning / error). *Mitigation:* pin
  compatible versions in `requirements.txt` and assert a hash/verify round-trip in the
  test suite so a bad combo fails loudly; fall back to the `bcrypt` library directly
  behind `passwords.py` if pinning proves fragile (the helper boundary makes this a
  one-file change).
- **Testcontainers in the pre-commit gate (Decision G).** Booting Postgres adds a few
  seconds and requires Docker on the committer's machine. *Mitigation:* session-scoped
  container with reuse; **skip DB tests gracefully when Docker is unavailable locally**
  (mock/unit tests still run) while **CI always runs them** (testcontainers or a GHA
  `services: postgres`). Revisit if commit time becomes a friction point.
- **CI runtimes.** CodeBuild `pre_build` and GitHub Actions must have Docker (for
  testcontainers) or a Postgres service available. *Mitigation:* GHA uses a postgres
  service or Docker-in-job; CodeBuild already runs Docker for image builds — confirm in
  the CI epic.
- **Migration / model drift.** Hand-written `0002` must match the ORM models.
  *Mitigation:* point `target_metadata` at `Base.metadata` and run `alembic check` in
  CI to catch divergence.
- **Cookie flags across environments.** `Secure` must be off for local HTTP and on in
  prod HTTPS. *Mitigation:* `session_cookie_secure` setting, defaulting safely per
  environment.
- **Tenant-context boundary with P1.2 (scope discipline).** P1.1 must not start
  setting `search_path`/DB roles. *Mitigation:* the session yields `tenant_id` only;
  P1.2 owns the middleware that consumes it. Reviewer should reject any `search_path`
  code here.
- **Open (deferred, not blocking):** auth-event audit shape lands in P1.4;
  `assumed_role` persona-switch column lands in P1.6 — both are named seams, not built
  now.

## 8. Rollout / Verification

**Manual verification (local stack)**
1. `docker-compose up` → boot runs `alembic upgrade head` (applies `0002`) then `seed`
   (creates 2 tenants + 9 users). Logs show the seed counts.
2. `POST /api/auth/login` with a seeded Tenant-Admin username + seed password → `200`,
   `Set-Cookie: pf_session=…; HttpOnly`.
3. `GET /api/auth/me` with the cookie → `200` identity + capabilities; without the
   cookie → `401`.
4. `GET /api/tenant/config` as Tenant Admin → `200`; repeat as a seeded Agent / Read-
   Only → `403`; as Platform Admin → `403`; with no cookie → `401`.
5. `POST /api/auth/logout` → subsequent `GET /api/auth/me` → `401` (session revoked).
6. Login with a wrong password / unknown user → `401 "invalid credentials"` (no
   distinction between the two).

**Automated verification (pytest, ephemeral Postgres)**
- Matrix unit test: assert every (role, capability) cell equals the Requirements table.
- Password hash/verify round-trip; wrong password rejected.
- Session create → resolve → revoke; expired session does not resolve.
- Endpoint tests: login success/failure; `/me` authed/unauthed/revoked;
  `/api/tenant/config` per role (200 Tenant Admin, 403 others, 401 anonymous);
  logout revokes.

**Rollout / compatibility**
- Additive schema (`0002`) on top of the empty baseline; deploys may reset+reseed
  (acceptable pre-go-live per Requirements §CI/CD). No data migration needed.
- New runtime deps (`sqlalchemy`, `passlib[bcrypt]`) enter the production image; dev/
  test deps (`testcontainers`) stay in `requirements-dev.txt`.
- `SEED_USER_PASSWORD` provisioned via SSM in prod (Terraform parameter, value out-of-
  band) alongside existing secrets; safe dev default locally.
- No feature flags; reversible by reverting the migration + code.
- Must stay green behind the pre-commit gate and CI before P1.2 begins.

## 9. Work Breakdown

Ordered simplest-first — a thin DB/ORM skeleton, then password + provider, then
sessions, then RBAC, then the endpoints, then enforcement on a real route, then seed,
then the test substrate. Each item is narrow and independently reviewable.

1. **ORM + engine skeleton.** Add `sqlalchemy[asyncio]` to `requirements.txt`; create
   `core/app/db.py` (async engine, `async_sessionmaker`, `get_db` dependency,
   `DeclarativeBase`). No tables yet — prove the engine connects.
2. **Models + migration `0002`.** Define `Tenant`, `User` (+ `Role` enum),
   `AuthSession` models; hand-write Alembic `0002` creating the `platform` schema and
   the three tables (enum + CHECK constraint + unique indexes); point
   `target_metadata` at `Base.metadata`, enable `include_schemas`.
3. **Password hashing.** `auth/passwords.py` — `hash_password` / `verify_password`
   (`passlib[bcrypt]`, pinned); round-trip unit test.
4. **AuthProvider.** `auth/provider.py` — `Identity`, `AuthProvider` Protocol,
   `LocalPasswordAuthProvider` (lookup active user → verify → `Identity | None`).
5. **Sessions.** `auth/sessions.py` — `create_session` / `get_session_identity` /
   `revoke_session` + cookie helpers; `session_*` settings in `config.py`.
6. **RBAC matrix.** `auth/rbac.py` — `Role`, `Capability`, `CAPABILITIES`,
   `has_capability`; cell-by-cell matrix unit test against the Requirements table.
7. **Auth dependencies + router.** `auth/dependencies.py`
   (`get_current_identity` / `require_authenticated` / `require_capability`) and
   `auth/router.py` (`POST /login`, `POST /logout`, `GET /me`); mount in `main.py`.
8. **Guarded demonstrator.** `tenant/router.py` — `GET /api/tenant/config` behind
   `require_capability(VIEW_TENANT_CONFIG)`, reading the session tenant's seeded row.
9. **Seed.** Extend `core/app/seed.py` to idempotently insert the 2 tenants + 9 users
   (bcrypt-hashed `SEED_USER_PASSWORD`); verify the boot logs.
10. **Test substrate (ephemeral Postgres).** Add `testcontainers` to
    `requirements-dev.txt`; a session-scoped Postgres fixture in `conftest.py` that
    runs migrations (skips locally if Docker absent); a DB-backed httpx client fixture.
11. **Integration tests + CI.** Endpoint tests (login, `/me`, `/api/tenant/config` per
    role, logout); ensure GitHub Actions / CodeBuild provide Postgres/Docker for the
    DB suite; full gate green.
```
