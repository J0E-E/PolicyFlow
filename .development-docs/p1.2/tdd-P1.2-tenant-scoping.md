# P1.2 — Tenant Scoping (schema-per-tenant) — Technical Design Document

## 1. Summary

Build the **tenant-isolation backbone**: one PostgreSQL schema per tenant, each
owned by a dedicated per-tenant database role, with the shared `platform` schema
keeping identity/reference data. A per-request scoping seam (a FastAPI dependency
that behaves as middleware) reads the authenticated session's `tenant_id` — never a
request parameter — and sets the connection's `search_path` + database role with
`SET LOCAL` inside a per-request transaction, so the scoping resets automatically
and can never leak across pooled connections. A Platform Admin **carve-out** runs
through a dedicated platform-scoped role for sanctioned cross-tenant operational
reads (the *audit* of those reads is a named seam → P1.4). Because no real domain
entities exist yet (leads/contacts are P1.7+), the phase ships a minimal but real
tenant-scoped entity — **`tenant_settings`** (seed-driven per-tenant config) — as
the demonstrator that proves isolation end-to-end over HTTP and at the database
layer. The acceptance proof is an automated test that a Tenant A user cannot read or
modify any Tenant B record through any endpoint, backed by a DB-layer test that the
per-tenant role is physically denied access to another tenant's schema.

## 2. Business Requirements

Lifted from `program-and-phase-plan.md` → **P1.2** (lines 221–235), the program's
**Decide Once** items #3/#4, and `PolicyFlow_Requirements.md` → **Multi-Tenancy
Requirements** (§Isolation Strategy, §Platform Administrator Carve-Out):

- **One PostgreSQL schema per tenant**; tenant-scoped entities live in the tenant's
  own schema, cross-tenant operational/reference data in a shared `platform` schema.
  Viable and clean given exactly **two fixed, seed-created tenants**.
- **Tenant context derived only from the authenticated session** — never a request
  parameter — injected by middleware that sets the connection's `search_path` **and**
  the per-tenant database role for every query.
- **Schema isolation is the enforcement boundary beneath the application:** each
  tenant schema is owned by / granted to a dedicated per-tenant DB role; middleware
  connects as that role. **No RLS.**
- **Platform Administrator carve-out:** operates outside tenant scope **for
  operational data only** (never unmasked PII); cross-tenant reads run through a
  dedicated platform-scoped path and **every cross-tenant read is audit-logged**.
- **Testable requirement:** automated tests verify a Tenant A user cannot read or
  modify any Tenant B record through any API endpoint.
- Per-schema Alembic migrations.

## 3. Goals / Non-Goals

**Goals**
- Per-tenant schemas + per-tenant DB roles + the GRANT/REVOKE model that makes the
  schema boundary the enforcement layer beneath the app.
- A shared **tenant registry** (single source of truth for slug → schema name → DB
  role) consumed by both the migration and the seed.
- A per-request **scoping dependency** (`get_tenant_db`) that sets `SET LOCAL ROLE` +
  `SET LOCAL search_path` from the session identity's `tenant_id`, leak-proof by
  construction (auto-reset at transaction end).
- A **Platform Admin carve-out** path (`get_platform_db`) using a platform-scoped
  role for sanctioned cross-tenant operational reads, with an audit-emission **seam**
  (emits nothing; wired in P1.4).
- A minimal, real tenant-scoped entity — **`tenant_settings`** — as the isolation
  demonstrator, plus a guarded endpoint reading it.
- Per-schema Alembic migrations provisioning schemas/roles/grants/tables for the two
  seed tenants; Alembic comparison configured to ignore the hand-written tenant
  schemas (no phantom drift).
- An **isolation test suite** on the existing ephemeral-Postgres substrate proving
  cross-tenant denial at both the app layer (endpoints) and the DB layer (role
  permissions), plus no pooled-connection leakage.

**Non-Goals** (owned by later phases — each named)
- **Real domain entities** (leads, contacts, households, opportunities, …) → **P1.7+**.
  P1.2 ships only the backbone + the `tenant_settings` demonstrator.
- **Audit logging** of cross-tenant reads / actions → **P1.4**. P1.2 leaves a clearly
  named emission seam and emits nothing.
- **Field-level PII encryption / blind index / masking** → **P1.3**;
  **events / outbox** → **P1.5**.
- **UI** (tenant-config view, role switcher) → **P1.6**; **platform health UI** → **M4**.
- **Runtime/dynamic tenant onboarding** — the two tenants stay fixed and seed-created.
- **A dedicated non-superuser application DB login role** as separate infra — P1.2
  reuses the existing connection role (made `NOINHERIT` + a member of the tenant/
  platform roles); a hardened dedicated login role is a noted future infra follow-up.

## 4. Current State

- **All data is in one schema.** [core/app/models/](../../core/app/models/) defines
  `Tenant`, `User`, `AuthSession`, all `__table_args__ = {"schema": "platform"}`.
  Migration [0002_platform_identity.py](../../core/alembic/versions/0002_platform_identity.py)
  hand-creates the `platform` schema + three tables + the `user_role` enum.
- **One un-scoped DB connection.** [core/app/db.py](../../core/app/db.py) builds a
  single async engine from `DATABASE_URL` with a default pool; `get_db` yields a
  request-scoped session. **No `search_path` or role switching anywhere** (P1.1
  deliberately stopped at recording `tenant_id`).
- **Identity already carries the tenant.** [core/app/auth/sessions.py](../../core/app/auth/sessions.py)
  `get_session_identity` returns `Identity(user_id, tenant_id, role, username)`
  ([provider.py](../../core/app/auth/provider.py)); [dependencies.py](../../core/app/auth/dependencies.py)
  exposes `get_current_identity` / `require_authenticated` / `require_capability`.
  The *source* of tenant context exists; nothing acts on it yet.
- **The P1.1 demonstrator reads platform-scoped data.** [core/app/tenant/router.py](../../core/app/tenant/router.py)
  `GET /api/tenant/config` reads `platform.tenants` by id via `get_db` — it proves
  RBAC, not schema isolation (no per-tenant schema is touched).
- **Tenant registry exists as flat seed data.** [core/app/seed.py](../../core/app/seed.py)
  holds `DEMO_TENANTS` (slug, name) etc. P1.1 Decision **H** explicitly reserved
  "P1.2 extends this registry with schema-name / DB-role mapping."
- **Alembic** ([env.py](../../core/alembic/env.py)) points `target_metadata` at
  `Base.metadata` with `include_schemas=True` but **no object filter** — the Epic 11
  notes flag that a live `alembic check` will report `public`/`information_schema` as
  drift; per-tenant schemas will compound this unless filtered.
- **Test substrate is ready.** [core/tests/conftest.py](../../core/tests/) provides a
  session-scoped ephemeral Postgres (testcontainers) that runs `alembic upgrade head`,
  a real `db_session`, and a DB-backed `db_client`; `factories.py` seeds isolated
  users. Suite currently **95 passed**.
- **Constraints** — `CLAUDE.md`: descriptive naming, booleans as yes/no, natural-
  language verbs, many small focused modules. Memory: minimal-churn insertion-style
  edits; dev *is* the local Docker stack, prod on EC2; single source of truth for
  shared data.

## 5. Proposed Design

### High-level approach
Keep one engine and one connection pool. On every **tenant-scoped** request, a
dependency opens a transaction, looks up the caller's tenant schema + DB role from
the session identity, issues `SET LOCAL ROLE <tenant_role>` and `SET LOCAL
search_path TO <tenant_schema>`, then hands the route a session that now reads/writes
**only** that tenant's schema. Because the scoping is `SET LOCAL`, Postgres discards
it when the request's transaction ends, so the next checkout of that pooled
connection starts clean. The per-tenant role has `USAGE`/CRUD grants on **only** its
own schema, so even a mis-pointed query is refused by the database — isolation holds
beneath the application. The **auth/login/seed** paths keep using the un-scoped
`get_db` (they run before tenant context exists and operate on `platform`). Platform
Admins use a parallel `get_platform_db` (a platform-scoped role) for sanctioned
cross-tenant operational reads.

> **Diagram:** [tenant-scoping flow](./diagrams/tdd-P1.2-tenant-scoping-flow.excalidraw)
> — request → resolve identity → tenant lookup → `SET LOCAL ROLE`/`search_path` →
> tenant schema; the Platform-Admin carve-out branching to the platform role; and the
> DB-layer denial guarantee (a tenant role is physically refused another schema).

### Components added / changed (core service)

```
core/app/
  tenancy/
    __init__.py
    registry.py          # TenantConfig (slug, display name, schema_name, db_role,
                         #   platform role name) — single source of truth
    scoping.py           # get_tenant_db (SET LOCAL ROLE + search_path), get_platform_db
  models/
    tenant_settings.py   # TenantSettings — schema-LESS model, resolved via search_path
    tenant.py            # + schema_name, db_role columns on platform.tenants
  tenant/
    router.py            # + GET /api/tenant/settings  (tenant-scoped demonstrator)
  platform/
    __init__.py
    router.py            # GET /api/platform/tenant-settings (Platform-Admin carve-out)
  seed.py                # populate tenants.schema_name/db_role + seed a settings row/tenant
  main.py                # mount platform_router
core/alembic/versions/
  0003_tenant_schemas.py # schemas + roles + grants + tenants.schema_name/db_role columns
  0004_tenant_settings.py# tenant_settings table created in EACH tenant schema + grants
core/alembic/env.py      # include_name/include_object filter: ignore tenant schemas
```

### The tenant registry (single source of truth)
`tenancy/registry.py` holds one canonical structure per tenant so the migration and
the seed can never disagree:

```python
@dataclass(frozen=True)
class TenantConfig:
    slug: str            # "sunshine-senior-benefits"   (matches seed DEMO_TENANTS)
    display_name: str    # "Sunshine Senior Benefits"
    schema_name: str     # "sunshine"        (a safe, unquoted SQL identifier)
    db_role: str         # "tenant_sunshine"

TENANTS: tuple[TenantConfig, ...] = (sunshine, florida)
PLATFORM_ROLE = "platform_reader"   # cross-tenant operational read role
```
Slugs contain hyphens (invalid as bare SQL identifiers), so `schema_name`/`db_role`
are explicit fields, not derived. Seed's existing `DEMO_TENANTS`/domains are folded
to read from this registry (single source of truth), preserving the slugs/names.

### Data model changes

**`platform.tenants` (migration `0003`)** — add `schema_name text` and `db_role text`
(both `NOT NULL` after backfill). These make the tenant row the **runtime authority**
for "which schema/role serves this tenant," seeded from the registry. The scoping
dependency reads them by `tenant_id`; `Identity` is **left unchanged** (minimal churn).

**Per-tenant schemas, roles, grants (migration `0003`)** — for each `TenantConfig`:
- `CREATE ROLE <db_role> NOLOGIN;` (idempotent guard — roles are cluster-global).
- `CREATE SCHEMA <schema_name> AUTHORIZATION <db_role>;`
- `GRANT USAGE ON SCHEMA <schema_name> TO <db_role>;` and default privileges so the
  role gets CRUD on tables created in its schema. **No grant to any other tenant role.**
- The connected **app login role** (`current_user`) is made `NOINHERIT` and granted
  membership in every `<db_role>` + `platform_reader`, so it can `SET ROLE` into
  exactly one at a time but holds none of their privileges ambiently.
- `platform_reader`: `NOLOGIN`; granted `USAGE`/`SELECT` on `platform` and (sanctioned)
  `USAGE`/`SELECT` on each tenant schema — operational reads only.

**`tenant_settings` (migration `0004`, one table per tenant schema)** — the minimal
real tenant entity and isolation demonstrator. Schema-driven config sliver (P1.6
renders it; P1.8 expands the seed):
- `tenant_id uuid` (PK; the platform.tenants id this row configures — a singleton row
  per tenant schema), `brand_primary_color text`, `brand_logo_url text`,
  `welcome_message text`, `created_at timestamptz`.
- Created **in each tenant schema** by a hand-written loop over the registry; the tenant
  role is granted `SELECT, INSERT, UPDATE, DELETE` on its own copy.

**Schema-less ORM model.** `TenantSettings` is declared with **no** `__table_args__`
schema, so SQLAlchemy resolves it against whatever `search_path` is active — the same
model object serves both tenants. (Platform models keep explicit `schema="platform"`.)

### Interfaces

**Scoping (`tenancy/scoping.py`)**
```python
async def get_tenant_db(
    identity: Identity = Depends(require_authenticated),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[AsyncSession]:
    # 400 if identity.tenant_id is None (Platform Admin must use the platform path)
    # within a transaction: look up schema_name/db_role from platform.tenants,
    #   SET LOCAL ROLE <db_role>; SET LOCAL search_path TO <schema_name>;
    # yield db  (commit/rollback at the end auto-resets the SET LOCALs)

async def get_platform_db(
    identity: Identity = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[AsyncSession]:
    # SET LOCAL ROLE platform_reader; (cross-tenant operational reads)
    # AUDIT SEAM: cross-tenant reads are audited in P1.4 — emit nothing here, marked.
```
- `require_platform_admin` is a small dependency (role is `PLATFORM_ADMIN`) added next
  to `require_capability`; the platform carve-out is a role check, not a per-capability
  cell (Platform Admin's capabilities don't include a generic cross-tenant read).
- The schema/role names are validated against the registry before interpolation (they
  are not user input, but identifiers can't be bound as parameters, so the values are
  taken from the registry/whitelist, never from the request).

**HTTP endpoints**
- `GET /api/tenant/settings` — **tenant-scoped demonstrator.** `require_authenticated`
  + `get_tenant_db`; returns the caller's own `tenant_settings` row. A Sunshine user
  sees only Sunshine's settings; there is **no tenant parameter** to ask for another
  tenant's. Tenantless caller (Platform Admin) → `400`.
- `GET /api/platform/tenant-settings` — **carve-out.** `require_platform_admin` +
  `get_platform_db`; lists every tenant's settings across schemas via `platform_reader`
  (operational metadata, no PII). The audit of this read is the P1.4 seam.

### Primary flows
```
Tenant user ──GET /api/tenant/settings (Cookie: pf_session)──▶ core
   require_authenticated ─ Identity(tenant_id=A)
   get_tenant_db ─ BEGIN; lookup A → (schema "sunshine", role "tenant_sunshine")
                   SET LOCAL ROLE tenant_sunshine; SET LOCAL search_path TO sunshine
   SELECT * FROM tenant_settings        ─ resolves to sunshine.tenant_settings
   ◀── 200 {settings: {...A...}}        ─ COMMIT auto-resets ROLE + search_path

Platform Admin ─GET /api/platform/tenant-settings─▶ core
   require_platform_admin ─ Identity(tenant_id=None, role=platform_admin)
   get_platform_db ─ SET LOCAL ROLE platform_reader   (+ audit seam → P1.4)
   SELECT across sunshine.* + florida.*  ─ operational read, no PII
   ◀── 200 {tenants: [...]}

DB-layer guarantee: SET ROLE tenant_sunshine; SELECT FROM florida.tenant_settings
   ─▶ permission denied (no USAGE/SELECT grant) — isolation beneath the app.
```

### Alembic / hygiene
- `0003`/`0004` are **hand-written** (matching the project's style) because they create
  schemas, roles, grants, and per-tenant tables that autogenerate can't express.
- `env.py` gains an `include_name`/`include_object` filter limiting reflection/compare
  to `platform` (+ the declared model schemas), so `public`, `information_schema`, and
  the hand-written tenant schemas don't surface as phantom drift (closes the Epic 11
  caveat).

## 6. Decisions

| # | Decision | Chosen | Alternatives considered | Rationale |
|---|---|---|---|---|
| 1 | Role/`search_path` switch & leak-safety | **`SET LOCAL ROLE` + `SET LOCAL search_path` inside a per-request transaction** | Session-level `SET` + explicit `RESET` on pool checkin; one engine/pool per tenant role | Postgres auto-resets `SET LOCAL` at commit/rollback — leak-proof by construction, no cleanup hook to forget; one transaction/request is a good default. Per-tenant pools are overkill for two fixed tenants. |
| 2 | Where tenants are provisioned | **Alembic migration**, driven by the shared registry | Runtime `provision_tenant()` in seed | Schemas/roles are structure; keeping them in Alembic makes the DB shape fully versioned/reproducible. Two fixed seed tenants make dynamic provisioning unnecessary. |
| 3 | Isolation demonstrator | **A real minimal `tenant_settings` entity** (seed-driven per-tenant config) | A throwaway "isolation probe" table | "Stubs behind real seams" — `tenant_settings` is requirement-backed (P1.6 renders it, P1.8 expands it) and not thrown away; gives the isolation test a real target. |
| 4 | App DB login-role model | **Existing connection role made `NOINHERIT` + member of each tenant role + `platform_reader`, switching via `SET ROLE`**; per-tenant roles hold `USAGE` on only their own schema | A dedicated non-superuser app login role provisioned as infra now | `NOINHERIT` means the connection holds no tenant privileges until it `SET ROLE`s into exactly one — never both at once. Local Postgres is superuser (membership moot but harmless); a hardened dedicated login role is a noted infra follow-up, not blocking. |
| 5 | Injection point | **A FastAPI DB-session dependency (`get_tenant_db`)** that scopes the connection from the session identity | Pure ASGI middleware | The SQLAlchemy session lifecycle is dependency-managed; a dependency cleanly owns the connection it scopes. Functionally identical to "middleware" (runs before every tenant query, sourced only from the session) and matches P1.1's pattern. |
| 6 | Identity vs lookup for schema/role | **Resolve `schema_name`/`db_role` by a small `platform.tenants` lookup in the scoping dependency; leave `Identity`/sessions unchanged** | Add `schema_name`/`db_role` to `Identity` and the session-resolution query | Minimal churn (no change to `provider.py`/`sessions.py` and their tests); one indexed PK lookup per request, on the platform path before `SET ROLE`. |
| 7 | Tenant-model schema binding | **Schema-less `TenantSettings` model resolved via `search_path`** | A model per tenant schema; templated table names | One model serving every tenant is the whole point of `search_path` scoping; platform models keep explicit `schema="platform"`. |
| 8 | Platform carve-out gate | **A `require_platform_admin` role-check dependency** | Stretch an existing RBAC capability to cover cross-tenant reads | The carve-out is a role-level operating mode, not a per-capability cell; a dedicated guard is clearer and keeps the matrix untouched. Audit emission is the P1.4 seam. |

## 7. Risks and Open Questions

- **Superuser local connection.** Locally `DATABASE_URL` is the Postgres superuser; a
  superuser doing `SET ROLE <tenant>` *does* drop to that role's privileges (superuser
  bypass stops while the role is set), so the isolation tests are meaningful. *Risk:*
  if a future change connects as a superuser and forgets `SET ROLE`, scoping is
  bypassed. *Mitigation:* the scoping dependency always `SET ROLE`s; a DB-layer test
  asserts cross-schema access is denied under the tenant role; the noted follow-up is a
  dedicated non-superuser login role in prod.
- **`SET LOCAL` requires a transaction, and existing helpers self-commit.** Session
  helpers (`create_session`, etc.) commit their own transactions on the **platform**
  path (`get_db`), untouched here. Tenant routes use `get_tenant_db`, which owns one
  transaction per request. *Mitigation:* keep the two paths separate; don't route auth
  through `get_tenant_db`.
- **Identifiers can't be bound as parameters.** `SET ROLE`/`search_path` take an
  identifier, not a bind value. *Mitigation:* schema/role names come **only** from the
  registry/`platform.tenants` (a fixed whitelist), never from the request; validate the
  looked-up value is a known registry entry before interpolating.
- **Alembic drift / `alembic check` against hand-written schemas.** Schema-less tenant
  models + hand-written per-tenant tables won't match naive autogenerate.
  *Mitigation:* the `include_name`/`include_object` filter restricts comparison to
  `platform`; tenant schemas are migration-owned and excluded from compare.
- **Role/schema teardown in tests & re-seed.** Roles are cluster-global; dropping a
  schema with `CASCADE` and then the role requires no remaining owned objects.
  *Mitigation:* `0003`/`0004` downgrades drop tables → schema → revoke memberships →
  drop roles in order; the substrate runs a fresh container so global roles start clean.
- **Pre-go-live reset.** Deploys may reset+reseed (Requirements §CI/CD). Additive
  migrations on the empty-ish DB; no data migration. The two `schema_name`/`db_role`
  columns backfill from the registry for the two known tenants.
- **Open (deferred, not blocking):** the cross-tenant-read **audit** record shape lands
  in P1.4 (seam only here); a dedicated hardened app login role is an infra follow-up;
  platform reference tables reachable via `search_path` fall-through arrive when the
  first shared reference table lands (P1.2 sets `search_path` to the tenant schema only).

## 8. Rollout / Verification

**Manual verification (local stack)**
1. `docker-compose up` → boot runs `alembic upgrade head` (applies `0003`+`0004`:
   schemas `sunshine`/`florida`, roles `tenant_sunshine`/`tenant_florida`/
   `platform_reader`, `tenant_settings` per schema) then `seed` (sets
   `tenants.schema_name/db_role`, inserts a settings row per tenant). Logs show counts.
2. Log in as a Sunshine Agent → `GET /api/tenant/settings` → `200` with **Sunshine's**
   color/message; log in as a Florida Agent → the **Florida** values. Neither can
   request the other's (no tenant parameter exists).
3. Log in as Platform Admin → `GET /api/tenant/settings` → `400` (tenantless);
   `GET /api/platform/tenant-settings` → `200` listing **both** tenants' settings.
4. `psql` as `tenant_sunshine` (`SET ROLE tenant_sunshine`) → `SELECT FROM
   florida.tenant_settings` → **permission denied**; `SELECT FROM sunshine.tenant_settings`
   → ok.

**Automated verification (pytest, ephemeral Postgres)**
- **DB-layer isolation:** under `SET ROLE tenant_sunshine`, `SELECT`/`UPDATE`/`INSERT`
  on `florida.tenant_settings` → permission denied; own schema → ok.
- **App-layer isolation:** Sunshine user's `GET /api/tenant/settings` returns only
  Sunshine's row; Florida user's returns only Florida's; values never cross.
- **No leak across pooled connections:** two sequential requests as different tenants
  on the reused connection each return correctly scoped data; after a request the
  connection's `search_path`/role are back to default.
- **Carve-out:** Platform Admin reads all tenants via `get_platform_db`; a tenant role
  cannot reach the platform cross-tenant read; tenantless caller on the tenant endpoint
  → 400.
- **Migration health:** `alembic upgrade head` then `alembic downgrade` round-trips;
  `alembic check` reports no drift (filter excludes tenant schemas).

**Rollout / compatibility**
- Additive migrations `0003`/`0004` on top of `0002`; pre-go-live reset+reseed is
  acceptable. No feature flags; reversible by reverting the migrations + code.
- No new runtime dependency (uses existing SQLAlchemy/asyncpg); no Terraform change
  (roles are created in-migration by the existing connection).
- Must stay green behind the pre-commit gate and CI before P1.3 begins.

## 9. Work Breakdown

Ordered simplest-first — a thin registry, then the schemas/roles backbone, then the
first tenant table, then the scoping mechanism, then the two endpoints, then the
isolation proof and migration hygiene. Each item is narrow and independently
reviewable.

1. **Tenant registry.** `tenancy/registry.py` — `TenantConfig` (slug, display name,
   `schema_name`, `db_role`) + `TENANTS` + `PLATFORM_ROLE`; fold `seed.py`'s
   `DEMO_TENANTS`/domains to read from it (single source of truth, slugs unchanged).
   Pure data; unit-tested without a DB.
2. **Migration `0003` — schemas, roles, grants, tenant columns.** Per-tenant
   `CREATE ROLE`/`CREATE SCHEMA AUTHORIZATION`/`GRANT USAGE` (+ default privileges);
   `platform_reader` role; make the connected login role `NOINHERIT` + member of all
   roles; add `schema_name`/`db_role` to `platform.tenants`. Idempotent role guards;
   ordered downgrade. Substrate test: schemas/roles exist, grants correct.
3. **Seed: populate tenant schema/role columns.** Extend `seed.py` to set
   `schema_name`/`db_role` from the registry on insert + backfill existing rows.
   Idempotent; unit + DB test.
4. **`tenant_settings` model + migration `0004`.** Schema-less `TenantSettings` model;
   hand-written DDL creating the table in **each** tenant schema + per-tenant CRUD
   grants; seed one settings row per tenant with distinct values. Substrate test: the
   table exists in both schemas with the seeded values.
5. **Scoping dependency.** `tenancy/scoping.py` — `get_tenant_db` (`SET LOCAL ROLE` +
   `SET LOCAL search_path` from the tenant lookup, 400 on tenantless) and
   `require_platform_admin` + `get_platform_db` (platform role + **audit seam**).
   DB tests: a scoped session reads only its schema; reset after the request.
6. **Tenant-scoped demonstrator endpoint.** `GET /api/tenant/settings` via
   `get_tenant_db`, returning the caller's settings row; mount stays in `tenant/router.py`.
   Endpoint tests: Sunshine vs Florida users see only their own; tenantless → 400.
7. **Platform carve-out endpoint.** `platform/router.py` →
   `GET /api/platform/tenant-settings` via `get_platform_db`; mount in `main.py`.
   Endpoint tests: Platform Admin reads both; non-platform roles rejected.
8. **Isolation test suite + Alembic hygiene.** The DB-layer permission-denied proof,
   the no-leak/reset proof, the full A-vs-B acceptance test; add the `env.py`
   `include_name`/`include_object` filter and an `alembic check`/downgrade round-trip
   so the gate stays clean. Confirm CI green.
