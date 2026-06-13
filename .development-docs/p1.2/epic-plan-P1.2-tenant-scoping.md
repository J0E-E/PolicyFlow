# Tenant Scoping (schema-per-tenant) — Epic Plan

Source TDD: [./tdd-P1.2-tenant-scoping.md](./tdd-P1.2-tenant-scoping.md)

> **Review budget:** ~150 changed lines · ~8 non-generated files · one focused commit per epic. Tunable per project.

> This is a high-level agile roadmap. Each epic's design specifics are confirmed
> with stakeholders at epic time (`3-plan-epic`) before any code is written.

## Epic 1 — Tenant registry
- **Goal:** Establish the single source of truth that maps each tenant to its schema name and DB role, so the migration and the seed can never disagree about which schema/role serves which tenant.
- **Rough scope:** A small `tenancy/registry.py` holding a frozen `TenantConfig` per tenant (slug, display name, schema name, DB role) plus the platform read-role constant; fold the existing `seed.py` tenant data to read from it. Pure data, no database involved.
- **Open questions / decisions for stakeholders:** Final schema/role identifier strings (e.g. `sunshine` / `tenant_sunshine`); how much of `seed.py`'s existing `DEMO_TENANTS`/domains structure folds into the registry vs. stays alongside it.
- **Depends on:** none.
- **Implementation notes:** _none yet_

## Epic 2 — Migration `0003`: schemas, roles, grants, tenant columns
- **Goal:** Provision the isolation backbone in the database — one schema per tenant owned by a dedicated per-tenant role, a platform read-role, the GRANT/REVOKE model that makes the schema boundary the enforcement layer, and the new `schema_name`/`db_role` columns on `platform.tenants`.
- **Rough scope:** A hand-written Alembic migration driven by the registry: idempotent `CREATE ROLE`, `CREATE SCHEMA ... AUTHORIZATION`, `USAGE` + default privileges per tenant; the `platform_reader` role; make the connected login role `NOINHERIT` and a member of every tenant role + `platform_reader`; add the two `platform.tenants` columns; ordered downgrade (revoke/drop in dependency order).
- **Open questions / decisions for stakeholders:** Exact grant set and default-privilege wording; whether the two new columns are added `NULL` then tightened to `NOT NULL` after the Epic 3 backfill, or backfilled inside this migration.
- **Depends on:** Epic 1.
- **Implementation notes:** _none yet_

## Epic 3 — Seed: populate tenant schema/role columns
- **Goal:** Make the `platform.tenants` rows the runtime authority for "which schema/role serves this tenant" by filling `schema_name`/`db_role` from the registry — on insert for fresh seeds and as a backfill for existing rows.
- **Rough scope:** Extend `seed.py` to set the two columns from the registry; idempotent so a re-seed is safe. Unit coverage plus a DB-backed check on the substrate.
- **Open questions / decisions for stakeholders:** Whether backfill is keyed on slug; behavior if a tenant row exists with no matching registry entry.
- **Depends on:** Epic 2.
- **Implementation notes:** _none yet_

## Epic 4 — `tenant_settings` demonstrator (model + migration `0004` + seed row)
- **Goal:** Ship the first real tenant-scoped entity — a schema-less `TenantSettings` model with its table created in **each** tenant schema and a distinct settings row seeded per tenant — giving the isolation tests and later UI a real, requirement-backed target.
- **Rough scope:** A schema-less `TenantSettings` ORM model (resolved via `search_path`); a hand-written `0004` migration that loops the registry to create the table + per-tenant CRUD grants in every tenant schema; seed one row per tenant with distinct brand/welcome values; ordered downgrade.
- **Open questions / decisions for stakeholders:** Final column set for the settings sliver; the seeded sample values; PK choice (the configured `tenant_id` as a singleton-row PK).
- **Depends on:** Epic 2 (schemas/roles), Epic 1 (registry loop).
- **Implementation notes:** _none yet_

## Epic 5 — Tenant scoping dependency (`get_tenant_db`)
- **Goal:** Deliver the per-request scoping seam that makes isolation automatic and leak-proof — a dependency that opens a transaction, looks up the caller's schema/role from their session identity, and issues `SET LOCAL ROLE` + `SET LOCAL search_path` so every query reads only that tenant's schema and resets at transaction end.
- **Rough scope:** `tenancy/scoping.py` `get_tenant_db`; the `platform.tenants` lookup by `tenant_id`; registry-whitelist validation before identifier interpolation; a `400` for a tenantless (Platform Admin) caller. DB tests: a scoped session reads only its own schema, and the connection's role/`search_path` are back to default after the request (no leak across pooled connections).
- **Open questions / decisions for stakeholders:** Exact `400` shape/message for the tenantless case; whether the schema/role lookup is cached per request or re-read each time.
- **Depends on:** Epic 3 (columns populated for the lookup), Epic 4 (a real table to prove scoping against).
- **Implementation notes:** _none yet_

## Epic 6 — Tenant-scoped demonstrator endpoint
- **Goal:** Prove isolation end-to-end over HTTP — `GET /api/tenant/settings` returns the caller's own settings row and nothing else, with no tenant parameter that could ask for another tenant's data.
- **Rough scope:** Add the route to `tenant/router.py` behind `require_authenticated` + `get_tenant_db`; map the settings row to a response. Endpoint tests: a Sunshine user sees only Sunshine's values, a Florida user only Florida's, values never cross, and a tenantless caller gets `400`.
- **Open questions / decisions for stakeholders:** Response field names/shape for the settings payload.
- **Depends on:** Epic 5 (`get_tenant_db`), Epic 4 (settings row).
- **Implementation notes:** _none yet_

## Epic 7 — Platform-Admin carve-out (dependency + endpoint)
- **Goal:** Provide the sanctioned cross-tenant operational read path — a platform-scoped role and a `require_platform_admin` gate behind `GET /api/platform/tenant-settings` that lists every tenant's settings (operational metadata, no PII), with a clearly named audit-emission seam that emits nothing yet.
- **Rough scope:** `require_platform_admin` next to the existing RBAC guards; `get_platform_db` (`SET LOCAL ROLE platform_reader` + the marked audit seam) in `tenancy/scoping.py`; a new `platform/router.py` reading across schemas; mount it in `main.py`. Tests: a Platform Admin reads both tenants; non-platform roles are rejected; a tenant role cannot reach this path.
- **Open questions / decisions for stakeholders:** How the cross-schema list is assembled (per-schema reads vs. a union); the exact name/placement of the audit seam so P1.4 can wire it without churn.
- **Depends on:** Epic 2 (`platform_reader` role), Epic 4 (settings to read across schemas).
- **Implementation notes:** _none yet_

## Epic 8 — Isolation acceptance test suite
- **Goal:** Land the phase's acceptance proof — automated tests that a Tenant A user cannot read or modify any Tenant B record through any endpoint, backed by a DB-layer test that a per-tenant role is physically denied another tenant's schema.
- **Rough scope:** On the ephemeral-Postgres substrate: DB-layer permission-denied proof (`SET ROLE tenant_sunshine` → `SELECT`/`UPDATE`/`INSERT` on `florida.tenant_settings` denied, own schema ok); the full app-layer A-vs-B acceptance test; the no-leak/reset proof across reused pooled connections; the carve-out boundary checks. Consolidates the assertions the earlier epics introduced into the named acceptance suite.
- **Open questions / decisions for stakeholders:** Whether these live as one new isolation module or extend the per-epic tests; how much overlaps tests already written in Epics 5–7.
- **Depends on:** Epic 5, Epic 6, Epic 7.
- **Implementation notes:** _none yet_

## Epic 9 — Alembic hygiene: schema filter + round-trip
- **Goal:** Keep the migration gate clean now that hand-written tenant schemas exist — restrict Alembic's comparison to `platform` (+ declared model schemas) so `public`, `information_schema`, and the migration-owned tenant schemas don't surface as phantom drift, closing the Epic 11 caveat.
- **Rough scope:** An `include_name`/`include_object` filter in `alembic/env.py`; confirm `alembic upgrade head` → `alembic downgrade` round-trips and `alembic check` reports no drift; confirm CI stays green.
- **Open questions / decisions for stakeholders:** Exact allow-list of schemas the filter keeps; whether to assert "no drift" as a test or only in CI.
- **Depends on:** Epic 2, Epic 4.
- **Implementation notes:** _none yet_
