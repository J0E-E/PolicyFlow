# Field-level Encryption, Blind Index & Masking — Epic Plan

Source TDD: [./tdd-P1.3-field-encryption-blind-index-masking.md](./tdd-P1.3-field-encryption-blind-index-masking.md)

> **Review budget:** ~150 changed lines · ~8 non-generated files · one focused commit per epic. Tunable per project.

> High-level agile roadmap. Each epic's design specifics are confirmed with stakeholders at epic time (`4-plan-epic`) before any code is written.

## Epic 1 — Dependency + master-key config — **COMPLETED**
- **Goal:** Land the cryptography runtime dependency and a validated `PII_MASTER_KEY` config value so every later epic has a real master key to wrap/unwrap with — with a throwaway dev/test default and fail-fast on a bad key at boot.
- **Rough scope:** Add `cryptography` to the core requirements; add a `pii_master_key` setting to `config.py` (base64-decode, length-check to 32 bytes, throwaway dev default, loud failure on an undecodable/short key). Unit coverage for the decode/validation. No DB, no crypto logic yet.
- **Open questions / decisions for stakeholders:** Exact env var name and the dev-default value; whether a bad key raises at import or at first use; how the length/format check reports failure.
- **Depends on:** none.
- **Implementation notes:**
  - Env var `PII_MASTER_KEY`; dev/test default is base64 of the 32-ASCII-byte phrase `policyflow-dev-throwaway-key!!!!`, exposed via module constants `DEV_THROWAWAY_MASTER_KEY_PHRASE` / `DEV_THROWAWAY_MASTER_KEY_BASE64` in `config.py`. Mirrors the `seed_user_password` env/SSM precedent.
  - Validation lives in a pure helper `decode_master_key(raw_base64) -> bytes`: base64-decode with `validate=True`, exact-32-byte check, `ValueError` (clear message) on undecodable input or wrong length. Extracting it from `Settings.__init__` makes the failure paths unit-testable without manipulating import-time env.
  - `settings.pii_master_key` is the decoded 32 raw `bytes`; decode runs at import (`settings = Settings()`), so a malformed key fails boot loudly (fail-fast at import, not first use). Epic 2+ receive ready-to-use key material.
  - Dependency pinned `cryptography==49.0.0` — latest stable pyca release (released 2026-06-12), verified on PyPI; supersedes the plan's tentative `44.0.0` suggestion per the instruction to pin the current latest. Installs cleanly in the container test run.
  - New pure unit module `core/tests/test_config.py` (mirrors `test_passwords.py`): valid-32-byte round-trip, undecodable raises, too-short/too-long raise, dev default decodes to 32 bytes, live `settings.pii_master_key` is 32 `bytes`.
  - Test note: this local Windows Python lacks `asyncpg`, so `tests/conftest.py` (which builds a DB engine at import) aborts pytest collection for the whole suite — a pre-existing environment limitation, not introduced here (`test_passwords.py` fails identically). Ran the new + password unit tests in a `python:3.12-slim` container with full runtime + dev deps: **11 passed**.

## Epic 2 — Crypto primitives (pure)
- **Goal:** Provide the small, DB-free crypto toolkit the rest of the phase composes — authenticated encryption, master-key wrap/unwrap, HKDF subkey derivation, the HMAC blind index, and value normalization — each a pure, fully unit-tested function.
- **Rough scope:** A `pii/crypto.py` module: AES-256-GCM encrypt/decrypt (random nonce, tenant id as associated data), `wrap_key`/`unwrap_key`, `hkdf_subkey`, `hmac_blind_index`, `normalize_email`/`normalize_phone`. Full unit tests: encrypt→decrypt round-trip, wrong-key and wrong-AAD failures, wrap/unwrap round-trip, subkey independence, blind-index determinism, normalization correctness. No tenant logic, no database.
- **Open questions / decisions for stakeholders:** Final blob layout/version tag (`nonce‖ciphertext‖tag`); the exact HKDF `info` labels for the two subkeys; normalization edge cases (international phone formats, plus-addressing in email).
- **Depends on:** Epic 1 (the `cryptography` dependency).
- **Implementation notes:** _none yet_

## Epic 3 — Key store table + model (migration `0005`)
- **Goal:** Stand up the wrapped-key store — a `platform.tenant_data_keys` table holding one master-key-wrapped root key per tenant, readable only by the default login role so no tenant role can ever see key material.
- **Rough scope:** A hand-written `0005` migration creating the platform-schema table (`tenant_id` PK, `wrapped_root_key bytea`, `created_at`) with `SELECT` granted to the login role only — no grant to any tenant role or `platform_reader`; the platform-schema ORM model so Alembic reflects it normally. Substrate test: the table exists with the correct grants. No key generation here.
- **Open questions / decisions for stakeholders:** Final column names/types; whether `created_at` carries a DB default; exact grant wording.
- **Depends on:** none.
- **Implementation notes:** _none yet_

## Epic 4 — Per-tenant key resolution + in-process cache
- **Goal:** Turn a stored wrapped root key into usable per-tenant subkeys — load it via the default login role, unwrap with the master key, HKDF-derive the encryption and blind-index subkeys, and cache the result so a tenant's keys unwrap at most once per process.
- **Rough scope:** A `pii/keys.py` holding a `TenantKeys` shape and the load→unwrap→derive→cache flow keyed by tenant id, reading the wrapped blob through a short-lived login-role session. DB test: load yields stable subkeys; a second call is a cache hit that avoids re-reading.
- **Open questions / decisions for stakeholders:** Cache lifetime/eviction (process-lifetime vs. bounded); how the short-lived login-role session is obtained relative to the request's tenant session; behavior when no key row exists for a tenant.
- **Depends on:** Epic 1 (master key), Epic 2 (unwrap + HKDF), Epic 3 (the key store).
- **Implementation notes:** _none yet_

## Epic 5 — PII service layer
- **Goal:** Provide the thin, explicit write/read seam the demonstrator calls — `encrypt_field` / `decrypt_field` / `compute_blind_index`, each resolving the per-tenant key from tenant context and delegating to the crypto primitives.
- **Rough scope:** A `pii/service.py` over `keys.py` + `crypto.py`, resolving `TenantKeys` from the request's tenant id. DB test: encrypt under Tenant A then decrypt back; decrypting under Tenant B's context fails (per-tenant key + tenant-id AAD).
- **Open questions / decisions for stakeholders:** How tenant id reaches the service (explicit argument vs. request context); whether blind-index computation lives here or stays a thin pass-through to `crypto.py`.
- **Depends on:** Epic 2 (crypto), Epic 4 (key resolution).
- **Implementation notes:** _none yet_

## Epic 6 — Seed: per-tenant root keys
- **Goal:** Give each tenant a real wrapped root key at seed time — generate a random root key per tenant, wrap it with the master key, and insert it (insert-if-absent so a re-seed is safe), so the service has keys to work with at runtime.
- **Rough scope:** Extend `seed.py` to generate + wrap + insert one root key per tenant via the registry loop, idempotently. DB test: exactly one wrapped key per tenant after seed; a second seed run leaves them unchanged.
- **Open questions / decisions for stakeholders:** Whether the seed refuses to overwrite an existing key (insert-if-absent) vs. re-wraps; logging of how many keys were created.
- **Depends on:** Epic 1 (master key), Epic 2 (wrap), Epic 3 (the key store).
- **Implementation notes:** _none yet_

## Epic 7 — Masking + age band (pure)
- **Goal:** Provide the render-layer masking utilities and the derived `age_band` helper — pure functions, fully unit-tested, that the response layer applies by default.
- **Rough scope:** A `pii/masking.py`: `mask_email` / `mask_phone` / `mask_dob` / `mask_medicare_id` / `mask_generic`, plus `age_band_for(date_of_birth)`. Unit tests for each masked format and the age-band boundary table (including the 65+ edge). No DB, no tenant logic.
- **Open questions / decisions for stakeholders:** Final masked-form strings per field; the exact age-band cut points and the boundary convention (inclusive/exclusive at 18/35/50/65).
- **Depends on:** none.
- **Implementation notes:** _none yet_

## Epic 8 — `pii_demo` demonstrator table + model (migration `0006`)
- **Goal:** Ship the demonstrator entity carrying every distinct field treatment — a `pii_demo` table created in each tenant schema (plaintext name, encrypted fields, blind-index columns, plaintext age band, the never-revealable Medicare id) plus its schema-less model.
- **Rough scope:** A hand-written `0006` migration looping the registry to create the table + per-tenant CRUD grants + a non-unique index on each blind-index column in every tenant schema; a schema-less `PiiDemoRecord` model resolved via `search_path`, like `TenantSettings`; ordered downgrade. Substrate test: the table exists in both schemas with the expected columns/grants.
- **Open questions / decisions for stakeholders:** Final column set and nullability; which fields get a blind index; PK choice; index naming.
- **Depends on:** none.
- **Implementation notes:** _none yet_

## Epic 9 — Reveal seam (no-op)
- **Goal:** Land the named seam P1.4 (audit) and P1.5 (`pii.revealed` event) will fill with zero call-site churn — an awaitable `on_pii_revealed` that does nothing today.
- **Rough scope:** A `pii/reveal_seam.py` with `on_pii_revealed(identity, entity_type, entity_id, field_name)` returning `None`. Unit test: it is awaitable and returns `None`. Mirrors the established `record_platform_read_for_audit` no-op pattern.
- **Open questions / decisions for stakeholders:** Exact signature/argument names so P1.4/P1.5 wire in without changing call sites.
- **Depends on:** none.
- **Implementation notes:** _none yet_

## Epic 10 — Demonstrator write/read endpoints (masked by default)
- **Goal:** Prove the masked write/read path end-to-end — create, list, and get `pii_demo` records over HTTP, all tenant-scoped, encrypting + blind-indexing + deriving `age_band` on write and returning masked-by-default responses on read.
- **Rough scope:** A `pii_demo/router.py` (create / list / get) behind `require_authenticated` + `get_tenant_db`, with request/masked-response schemas; mount in `main.py`; seed a couple of demo rows per tenant (Sunshine including a mock Medicare id). Endpoint tests: masked defaults; `age_band` plaintext; Tenant A-vs-B isolation; 404 for an absent id in this tenant.
- **Open questions / decisions for stakeholders:** Response field names/shape; which capability gates create (`CREATE_EDIT_RECORDS`); the seeded demo rows.
- **Depends on:** Epic 5 (service), Epic 6 (seeded keys), Epic 7 (masking), Epic 8 (table + model).
- **Implementation notes:** _none yet_

## Epic 11 — Blind-index lookup endpoint
- **Goal:** Prove exact-match duplicate detection without decryption — a lookup endpoint that computes the blind index of a normalized email/phone and returns matching records (masked) via an equality query, entirely inside the tenant schema. This is Risk #3 at the API layer.
- **Rough scope:** `POST /api/pii-demo/lookup` taking `{email}` or `{phone}`, computing the blind index and selecting `WHERE *_blind_index = :index` with no decryption, returning masked matches. Endpoint test: a mixed-case/whitespace value hits; a non-matching value returns none.
- **Open questions / decisions for stakeholders:** Request/response shape (single field vs. either); whether a miss returns an empty list vs. 404.
- **Depends on:** Epic 10 (endpoints + service in place).
- **Implementation notes:** _none yet_

## Epic 12 — Guarded reveal endpoint
- **Goal:** Ship the audited click-to-reveal backend — a capability-gated endpoint that decrypts and returns one unmasked field, `await`s the reveal seam, refuses the mock Medicare id outright, and rejects callers without the capability.
- **Rough scope:** `POST /api/pii-demo/{id}/reveal` taking `{field}`, gated by `require_capability(REVEAL_PII)`; decrypt the requested field, `await on_pii_revealed`, return `{field, value}`; `mock_medicare_id` → `422` (never revealable); missing capability (Read-Only, Platform-Admin) → `403`; tenant-scoped 404. Endpoint tests for each path.
- **Open questions / decisions for stakeholders:** Exact `422`/`403` detail messages; the set of revealable field names; whether the seam is awaited before or after the value is returned.
- **Depends on:** Epic 9 (reveal seam), Epic 10 (endpoints + service).
- **Implementation notes:** _none yet_

## Epic 13 — Acceptance test suite + migration health
- **Goal:** Land the phase's acceptance proof, retiring Risk #3 — automated tests that PII is ciphertext at rest, blind-index exact-match works within a tenant schema under the tenant role, masking is the default, `age_band` is plaintext, one tenant's ciphertext can't be decrypted with another's key, and the migrations round-trip cleanly with no drift.
- **Rough scope:** A consolidated acceptance suite on the ephemeral-Postgres substrate: encrypted-at-rest (raw `*_encrypted` bytes don't contain plaintext); blind-index exact-match under `get_tenant_db` (Risk #3); per-tenant key isolation (Sunshine blob fails under Florida's key); masking-default + reveal RBAC summary; the sole-plaintext-egress check; `alembic upgrade head` → `downgrade` round-trip and `alembic check` no-drift (`tenant_data_keys` reflected, per-tenant `pii_demo` excluded by the existing filter). Confirm CI/gate green.
- **Open questions / decisions for stakeholders:** Whether this is one new acceptance module or extends per-epic tests; how much overlaps assertions already written in Epics 10–12 (add-only vs. consolidate).
- **Depends on:** Epic 11, Epic 12.
- **Implementation notes:** _none yet_
