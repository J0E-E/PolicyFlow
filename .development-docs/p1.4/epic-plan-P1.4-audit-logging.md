# Audit Logging — Epic Plan

Source TDD: [./tdd-P1.4-audit-logging.md](./tdd-P1.4-audit-logging.md)

> **Review budget:** ~150 changed lines · ~8 non-generated files · one focused commit per epic. Tunable per project.

> High-level agile roadmap. Each epic's design specifics are confirmed with stakeholders at epic time (`4-plan-epic`) before any code is written.

## Epic 1 — Audit constants + registry role name — **COMPLETED**
- **Goal:** Land the pure, DB-free vocabulary the whole phase shares — the event-type and outcome enums (and any field-name helper) — and register the `audit_writer` role name as a single-source-of-truth constant so the migration and the service can never disagree on it.
- **Rough scope:** A small `audit/records.py` with `EventType` + `Outcome` string enums (plus a field-name helper if one is warranted), fully unit-tested; add `AUDIT_WRITER_ROLE = "audit_writer"` to the tenancy registry alongside `PLATFORM_ROLE`. No DB.
- **Open questions / decisions for stakeholders:** The exact event-type string values (`auth.login`, `pii.revealed`, `record.created`, `platform.cross_tenant_read`, `audit.viewed`) and the outcome set (`success` / `failure`, with `denied` reserved); whether a field-name helper is needed at all.
- **Depends on:** none.
- **Implementation notes:**
  - Added new package `core/app/audit/` (`__init__.py` + `records.py`) with two `StrEnum`s mirroring the `Capability` enum style in `auth/rbac.py` (explicit string values, single-source docstring, `__all__`).
  - `EventType` values follow TDD §5 *Interfaces* verbatim (six members); `Outcome` has only `SUCCESS`/`FAILURE`. `denied` stays a **reserved comment**, not a defined member (TDD Decision 6 — no speculative members).
  - **No field-name helper** — deferred to a real consumer per this session's stakeholder decision; no dependent epic needs one.
  - `AUDIT_WRITER_ROLE = "audit_writer"` added to `tenancy/registry.py` beside `PLATFORM_ROLE`, with a comment naming Epic 2's `0007` migration and the Epic 4 service as consumers.
  - Tests: new `tests/test_audit_records.py` (independent hand-transcription of both enums; asserts each value, exact member sets, and that `denied` is not an `Outcome`); extended `tests/test_registry.py` with one test mirroring `test_platform_role_is_the_expected_constant` (constant value + `BARE_SQL_IDENTIFIER` match).
  - **Test run:** `pytest tests/test_audit_records.py tests/test_registry.py -q` → **14 passed** (run with `--noconftest`; the repo `conftest.py` fails to import under this environment's Python 3.14 / SQLAlchemy 2.0.36 ORM-union incompatibility, which also breaks pre-existing tests like `test_rbac.py` and is unrelated to this pure-data epic). Import smoke check passed. `asyncpg` was installed to get past the first conftest import error before the SQLAlchemy one surfaced.
  - **Caveat (environment) — full-suite collection block under system Python 3.14:** the repo's full suite cannot be *collected* with the system interpreter (Python 3.14.3 + SQLAlchemy 2.0.36): `make_union_type` raises `TypeError: descriptor '__getitem__' requires a 'typing.Union' object but received a 'tuple'` while mapping any ORM model with a `Mapped[... | ...]` union annotation, which fires at `conftest.py` import time and blocks every ORM-importing test (reproduces identically on pre-existing `test_rbac.py`; not caused by this epic, which adds no ORM models). **Resolution / how to run green:** use the project's pinned Python 3.12 venv at `core/.venv` (the interpreter the committed `.pre-commit-config.yaml` and `commit-epic` already invoke). Under it the suite collects and passes clean — verified this epic: `core/.venv/Scripts/python.exe -m pytest -q` → **236 passed** (full backend suite, incl. testcontainers DB tests), and this epic's two files → **14 passed** with the real conftest loaded. Noted so Epic 8's acceptance/migration work and the commit gate run against `core/.venv` (Python 3.12), not the system 3.14.

## Epic 2 — Migration `0007`: audit tables + writer role + grants — **COMPLETED**
- **Goal:** Stand up the two audit stores and make append-only **physical** — create the `audit_writer` role, the `platform.audit_records` table, and a per-tenant `audit_records` table in every tenant schema, with grants tightened so the writer can only INSERT/SELECT and tenant roles can only SELECT.
- **Rough scope:** A hand-written `0007` migration (registry loop for the per-tenant tables + the `occurred_at` index) in the `0003`/`0006` style: create `audit_writer` idempotently (`DO` block + `GRANT audit_writer TO CURRENT_USER`), grant it INSERT+SELECT on both stores, then **REVOKE** the auto-granted default CRUD down to tenant-role SELECT-only and remove `platform_reader` from tenant audit; ordered reversible downgrade. Substrate test: tables exist; grants/revokes as designed.
- **Open questions / decisions for stakeholders:** Final column types/nullability and index naming; exact grant/REVOKE wording; confirming the role-create `DO` block and membership grant mirror the `0003` precedent.
- **Depends on:** Epic 1 (the `AUDIT_WRITER_ROLE` constant).
- **Implementation notes:**
  - Added `core/alembic/versions/0007_audit_records.py` (`revision = "0007_audit_records"`, `down_revision = "0006_pii_demo"`). Copied the `create_role_if_absent` `DO`-block helper from `0003` (migrations stay self-contained); a second `create_audit_records_table(qualified_table)` helper builds the **identical** TDD §5 columns once for both stores. Created `audit_writer` + `GRANT audit_writer TO CURRENT_USER` (the `0003` NOINHERIT membership precedent).
  - **`ix_audit_records_occurred_at` is created on BOTH stores** (platform + every tenant schema), as the approved plan decided — full structural symmetry so the Epic 3 ORM models stay genuinely identical.
  - Primary key named `pk_audit_records` in every schema (a fixed name reused across schemas, mirroring `0006`'s `pk_pii_demo`; constraint names are per-schema, not cluster-global, so no clash).
  - Grants per TDD §5: `audit_writer` gets `USAGE` on `platform` and each tenant schema plus `INSERT, SELECT` on both stores (never UPDATE/DELETE). REVOKEd the `0003` default-privilege overreach on each tenant `audit_records` — `REVOKE INSERT, UPDATE, DELETE FROM <tenant.db_role>` (keep SELECT) and `REVOKE SELECT FROM platform_reader`. `platform.audit_records` left ungranted to `platform_reader`.
  - **Downgrade fix (caught by `test_migration_hygiene` round-trip):** dropping the tables removes *table*-level grants, but the *schema*-level `USAGE` grants to `audit_writer` survive and block `DROP ROLE` (`DependentObjectsStillExist`). The downgrade now explicitly `REVOKE USAGE ON SCHEMA ... FROM audit_writer` on `platform` and every tenant schema before `REVOKE ... FROM CURRENT_USER` + `DROP ROLE IF EXISTS`. Down→base→head round-trip is green.
  - Added `core/tests/test_audit_migration.py` (new filename, avoids colliding with Epic 1's pure-data `tests/test_audit_records.py`); 6 substrate tests reading expected values from `registry`: both stores exist with the column set; `audit_writer` exists with INSERT+SELECT but lacks UPDATE/DELETE on both stores; tenant role SELECT-only on its own audit; `platform_reader` lacks SELECT on any tenant audit; `ix_audit_records_occurred_at` exists in every tenant schema and in `platform`. (Live permission-*denied* execution is Epic 5; this proves grant *shape* via `has_table_privilege`, like `test_pii_demo.py`.)
  - **Cross-epic drift gap, carried as a strict `xfail` until Epic 3:** `platform.audit_records` lives in the `platform` schema, which `env.py`'s `include_name` keeps in the drift comparison. With no `PlatformAuditRecord` ORM model yet, `alembic check` reports the table+index as removed-from-metadata drift, so `test_migration_hygiene.py::test_alembic_check_reports_no_drift` cannot pass on the Epic-2-only tree. This is by design — TDD §9 assigns drift-cleanliness to Epic 3 ("ORM models for both audit stores"), and TDD §6 states `platform.audit_records` is *meant* to be reflected/drift-checked (unlike the schema-less tenant copy, excluded by the `env.py` filter). I deliberately did **not** patch `env.py` to suppress it (that would contradict Epic 3 and the TDD). Resolution (stakeholder-approved): that one test now carries `@pytest.mark.xfail(strict=True, raises=AutogenerateDiffsDetected, reason=…Epic 3…)`, so the full suite is green (xfail is not a failure) **without** any command-line deselection. `strict=True` means that once Epic 3 adds the model the test starts passing → unexpected pass → failure, forcing Epic 3 to remove the marker.
  - **Pre-existing dead-drift-guard bug, found and fixed (stakeholder-approved scope add):** while validating the `xfail` I found the drift guard had been **silently neutered in the full suite all along** — `test_db.py` calls `importlib.reload(app.db)` (with no teardown), which rebinds `app.db.Base` to a fresh, **empty** `MetaData`. The ORM models stay on the original `Base`, and `alembic/env.py` reads `from app.db import Base` at runtime on every `alembic check`, so for every test after `test_db` (it sorts before `test_migration_hygiene`) the guard inspected an empty schema set and passed **vacuously** — it could not catch *any* drift (so Epic 3's / Epic 11's "alembic check clean" acceptance was vacuous too). Proven empirically: at drift-check time in the full suite `Base.metadata.tables` was empty (`declared schemas=set()`), while the DB was correctly at `0007` with `platform.audit_records` present. **Fix:** an autouse fixture in `test_db.py` snapshots and restores the `app.config` / `app.db` module namespaces around each test, fully containing the reload so the shared `Base` (with its models) survives. After the fix the guard is live again: running `test_db.py` *before* `test_migration_hygiene.py` (the contamination order) now correctly **XFAILs** the drift test (guard detects the real Epic-2 drift) instead of vacuously passing.
  - **Test run:** full suite `core/.venv/Scripts/python.exe -m pytest -q` → **241 passed, 1 xfailed** (the audit drift case); the new substrate file `tests/test_audit_migration.py` → **6 passed**; the contamination-order check `pytest tests/test_db.py tests/test_migration_hygiene.py` → **8 passed, 1 xfailed**.

## Epic 3 — ORM models for both audit stores
- **Goal:** Give SQLAlchemy the two table mappings — a platform-schema `PlatformAuditRecord` (reflected by Alembic) and a schema-less `AuditRecord` (one per tenant, resolved via `search_path` and excluded from drift) — so the service and reader have typed models with `alembic check` reporting no drift.
- **Rough scope:** A `models/audit_record.py` with both classes (identical columns), registered in the models package; confirm the existing `env.py` schema-less filter covers `audit_records` (extend the exclusion set if needed). Drift check clean.
- **Open questions / decisions for stakeholders:** Column names/types must match the migration exactly; whether `audit_records` needs adding to the `env.py` exclusion set or the existing filter already covers it.
- **Depends on:** Epic 2 (the tables the models map).
- **Implementation notes:** _none yet_

## Epic 4 — Audit-emit service (own session, two-store routing)
- **Goal:** The single function every audited action calls — `record_audit_event(...)` — resolving the target store from `tenant_id` (present → that tenant's schema; absent → platform), opening its **own** short-lived session as `audit_writer`, and writing one append-only record storing **names, never values**.
- **Rough scope:** An `audit/service.py` with a module-global `session_factory` (the `keys.py` precedent), `tenant_id → schema` resolve + registry whitelist, `SET LOCAL ROLE audit_writer`, a schema-qualified INSERT, and strict failure propagation; add the `container_audit_session_factory` test fixture mirroring the keys one. DB test: tenant-vs-platform routing; `field_names` round-trip; newest-first ordering.
- **Open questions / decisions for stakeholders:** How the schema name is resolved and whitelist-validated (mirroring `get_tenant_db`); strict-vs-best-effort failure behavior (TDD picks strict); whether ordering is the service's concern or the reader's.
- **Depends on:** Epic 1 (constants + role name), Epic 2 (tables + role), Epic 3 (models).
- **Implementation notes:** _none yet_

## Epic 5 — Append-only + isolation acceptance (DB proof)
- **Goal:** Prove the physical guarantees hold — an `UPDATE`/`DELETE` is denied for both the tenant role and `audit_writer`, the tenant role is SELECT-only, one tenant cannot read another's audit, and `platform_reader` cannot read any tenant audit.
- **Rough scope:** A focused DB acceptance test (mirrors `test_isolation_acceptance.py`) exercising the real roles against written rows, asserting `permission denied` on every forbidden operation. No production code.
- **Open questions / decisions for stakeholders:** Whether rows are written via the Epic 4 service or inserted directly under `audit_writer`; the exact set of permission-denied assertions to cover.
- **Depends on:** Epic 2 (the grants), Epic 4 (a way to write rows to read back).
- **Implementation notes:** _none yet_

## Epic 6 — Fill the cross-tenant-read seam
- **Goal:** Make the Platform-Admin cross-tenant read actually audited — fill `record_platform_read_for_audit` so it writes one `platform.cross_tenant_read` record to the platform store, with zero call-site churn.
- **Rough scope:** Fill the existing no-op body in `tenancy/scoping.py` to call `record_audit_event(tenant_id=None, …)`; update its focused test from the no-op assertion to assert one platform record is written.
- **Open questions / decisions for stakeholders:** The `entity_type` to record (TDD suggests `tenant_settings`); confirming platform-store routing when `tenant_id` is `None`.
- **Depends on:** Epic 4 (the service).
- **Implementation notes:** _none yet_

## Epic 7 — Fill the PII-reveal seam
- **Goal:** Make every successful PII reveal audited — fill `on_pii_revealed` so it writes one tenant-store `pii.revealed` record carrying the field *name* only, never the value.
- **Rough scope:** Fill the existing no-op body in `pii/reveal_seam.py` to call `record_audit_event(tenant_id=identity.tenant_id, …, field_names=[field_name])`; **update `test_reveal_seam.py`** from the no-op assertion to assert one tenant record is written with `field_names=[field]`.
- **Open questions / decisions for stakeholders:** None expected — the signature is frozen and the reveal endpoint already passes entity type/id/field.
- **Depends on:** Epic 4 (the service).
- **Implementation notes:** _none yet_

## Epic 8 — Auth event wiring (login success/failure + logout)
- **Goal:** Audit the authentication surface — record `auth.login` on success and on failure (failure carries no identifying PII, routed to the platform store) and `auth.logout` after resolving the identity from the session.
- **Rough scope:** Emit from `auth/router.py` on the three paths; resolve the logout identity via the existing session lookup before revoking the token. Tests for each path (success in the tenant store, failure PII-free in the platform store, logout attributed).
- **Open questions / decisions for stakeholders:** Store routing for a successful login (tenant store via `identity.tenant_id`; platform store for the Platform Admin); confirming a no-session logout records nothing.
- **Depends on:** Epic 4 (the service).
- **Implementation notes:** _none yet_

## Epic 9 — Record-change wiring (`pii_demo` create)
- **Goal:** Prove the record-change audit path on the one write surface that exists today — emit `record.created` on `pii_demo` create with the written field **names** and no values.
- **Rough scope:** Emit from `pii_demo/router.py` after the insert with `entity_type="pii_demo"`, the new row id, and the list of written field names; test asserts the names are present and that no seeded plaintext appears in the row.
- **Open questions / decisions for stakeholders:** The exact field-name list to record; confirming that a propagating audit error rolls the create back (strict behavior).
- **Depends on:** Epic 4 (the service).
- **Implementation notes:** _none yet_

## Epic 10 — Guarded, self-auditing read endpoint
- **Goal:** Ship the backend read path that satisfies "viewing audit is itself audited" — `GET /api/audit`, gated by `VIEW_AUDIT_LOGS`, tenant-scoped, PII-free, recording its own `audit.viewed` before returning.
- **Rough scope:** An `audit/router.py` + a names-only response schema, reading the caller's tenant records newest-first under `get_tenant_db`, self-auditing before responding; mount in `main.py`. Endpoint tests: the RBAC matrix (Tenant Admin / Read-Only 200, Agent 403, anonymous 401, Platform Admin 403), tenant A-vs-B isolation, no unmasked PII, and a second view that sees the first.
- **Open questions / decisions for stakeholders:** Response field shape/envelope; ordering and any (deferred) pagination; confirming `audit.viewed` is written **before** the response, not after. (The `VIEW_AUDIT_LOGS` RBAC cell already exists — no matrix change.)
- **Depends on:** Epic 3 (the read model), Epic 4 (the self-auditing emit).
- **Implementation notes:** _none yet_

## Epic 11 — Named acceptance suite + migration hygiene
- **Goal:** The phase's concise proof — a sensitive op of each wired kind produces a names-not-values record, append-only holds, tenant audit is tenant-only, and viewing is itself audited — plus `alembic check` no-drift and an up/down migration round-trip.
- **Rough scope:** A `test_audit_acceptance.py` narrative test (mirrors `test_pii_acceptance.py`) over the DB-backed client; confirm migration health (`alembic check` + `0007` round-trip) and a green full suite.
- **Open questions / decisions for stakeholders:** None expected — the acceptance bullets are enumerated in the TDD's §8.
- **Depends on:** Epics 5, 6, 7, 8, 9, 10 (every wired surface plus the append-only/isolation proof it summarizes).
- **Implementation notes:** _none yet_
