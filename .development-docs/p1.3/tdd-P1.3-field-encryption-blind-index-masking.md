# P1.3 — Field-level Encryption, Blind Index & Masking — Technical Design Document

## 1. Summary

Build the **PII-protection primitives** the rest of the platform encrypts and
renders sensitive data through: application-layer **field encryption** (AES-256-GCM
via pyca `cryptography`), an **HMAC blind index** for exact-match duplicate lookup
without decryption, and a **masking-by-default** render layer at the API boundary.
Keys follow an **envelope** shape that retires Risk #3: an env-supplied **master
key** wraps one random **per-tenant root key**; the root key is HKDF-derived into a
field-**encryption** subkey and a **blind-index** subkey (cryptographic key
separation, no key reuse). Because no real domain entities exist yet (leads/contacts
are P1.7+), the phase proves all three controls end-to-end on a **real-but-minimal
PII-bearing demonstrator entity** — `pii_demo`, one table per tenant schema —
mirroring the way P1.2 used `tenant_settings`. Decryption is an explicit
service-layer call (per-tenant keys are request-scoped); masking is applied in the
response layer; a **guarded reveal endpoint** (`Capability.REVEAL_PII`, already
defined) returns the unmasked value and `await`s two named **no-op seams** —
audit emission (P1.4) and the `pii.revealed` event (P1.5) — so those phases fill a
body with zero call-site churn. The acceptance proof is automated: PII columns are
ciphertext at rest, blind-index exact-match works **within a tenant schema under the
tenant role**, masking is the default, `age_band` is plaintext, and one tenant's
ciphertext cannot be decrypted with another tenant's key.

## 2. Business Requirements

Lifted from `program-and-phase-plan.md` → **P1.3** (lines 254–267), **Decide Once**
item #7, and `PolicyFlow_Requirements.md` → **PII Protection** (§Field Protection
Matrix, §Key Management, §Masking Matrix, §Additional Controls):

- **Application-layer field encryption** of PII columns; encrypted at rest, decrypted
  only in-process.
- **Envelope encryption:** a per-tenant **data key** wraps field encryption; an
  env-supplied **master key** wraps the data keys (KMS-ready). Per-tenant keys
  reinforce the tenant-isolation story.
- **HMAC blind index** of the normalized email/phone, supporting **exact-match
  duplicate detection without decryption**, scoped within a tenant.
- **Date of Birth** is encrypted; a derived **`age_band` is stored in plaintext**
  (feeds eligibility/enrichment display, e.g. the Medicare 65+ gate).
- **Masking by default** for Email/Phone/DOB/Address/Policy Number, with an
  **audited click-to-reveal** for Agent/Tenant-Admin; **Read-Only never reveals**;
  the **mock Medicare ID is always masked — no full reveal in any UI**.
- **No raw PII in logs or event payloads**; reveals are an audited sensitive
  operation.
- All data is synthetic; the mock Medicare ID is the deliberately-fake high-sensitivity
  centerpiece.

## 3. Goals / Non-Goals

**Goals**
- A small **crypto primitives** module: AES-256-GCM encrypt/decrypt, master-key
  wrap/unwrap, HKDF subkey derivation, HMAC blind index — pure functions, unit-tested
  without a DB.
- An **envelope key model**: random per-tenant root key wrapped by the env master key,
  stored in a `platform.tenant_data_keys` table; HKDF-derived encryption + blind-index
  subkeys; an in-process **key cache** so a tenant's keys unwrap at most once per
  process.
- A thin **PII service layer** (`encrypt_field` / `decrypt_field` / `blind_index`)
  invoked explicitly at write/read sites, resolving the per-tenant key from request
  tenant context.
- A **masking** utility + masked-by-default API responses; a **guarded reveal
  endpoint** that returns the unmasked value and `await`s the **audit** (P1.4) and
  **event** (P1.5) seams (both no-ops here).
- A **`pii_demo` demonstrator entity** (one table per tenant schema) carrying every
  distinct field treatment, with create / list / get / **blind-index lookup** /
  reveal endpoints, all tenant-scoped via the P1.2 `get_tenant_db` seam.
- An **acceptance test suite** proving encrypted-at-rest, blind-index exact-match
  within a tenant schema, masking default, age-band plaintext, and per-tenant key
  isolation — **retiring Risk #3**.

**Non-Goals** (owned by later phases — each named)
- **Real domain entities** (leads, contacts, households, …) → **P1.7+**. P1.3 ships
  primitives + the `pii_demo` demonstrator only.
- **Audit record emission** for reveals → **P1.4**; **`pii.revealed` event + outbox
  publishing** → **P1.5**. P1.3 leaves both as named no-op seams.
- **Click-to-reveal UI**, role switcher → **P1.6**; **audit viewer UI** → **M4**.
- **Key rotation / re-encryption tooling** and **real KMS integration** — the env
  master key is KMS-*ready* (unwrap swaps 1:1 for a KMS Decrypt call), not KMS-*wired*.
- **Name search / "Database-at-rest encryption only" for names** — the demonstrator
  keeps `display_name` plaintext to contrast with app-layer fields; full disk/volume
  encryption is an infra/ops concern, not application code.
- **Address / Policy Number** as their own columns — their treatment is identical to
  email-without-blind-index, already proven by the demonstrator's fields; real columns
  land with their owning entities (P1.7+, P2.3).

## 4. Current State

- **No PII and no crypto exist yet.** No encryption module, no `cryptography`
  dependency ([core/requirements.txt](../../core/requirements.txt) is FastAPI +
  SQLAlchemy + asyncpg + bcrypt only). `Capability.REVEAL_PII` is **already defined**
  and granted to Agent + Tenant-Admin (not Read-Only, not Platform-Admin) in
  [core/app/auth/rbac.py](../../core/app/auth/rbac.py).
- **The tenant-scoping backbone is in (P1.2).** [tenancy/scoping.py](../../core/app/tenancy/scoping.py)
  provides `get_tenant_db` (`SET LOCAL ROLE`/`search_path`, leak-proof) and
  `get_platform_db`; [tenancy/registry.py](../../core/app/tenancy/registry.py) is the
  single source of truth (`TenantConfig`, `TENANTS`, `PLATFORM_ROLE`). Every PII read
  rides on `get_tenant_db`, so cross-tenant denial is inherited, not re-implemented.
- **The "real-but-minimal demonstrator" pattern is established.**
  [models/tenant_settings.py](../../core/app/models/tenant_settings.py) is a
  **schema-less** model resolved via `search_path`; migration
  [0004_tenant_settings.py](../../core/alembic/versions/0004_tenant_settings.py)
  creates it **in each tenant schema** by looping the registry + explicit grants; the
  [seed](../../core/app/seed.py) writes one row per tenant via parameterized SQL with
  the schema identifier taken only from the registry. P1.3 follows this pattern exactly.
- **Config is env-sourced with throwaway dev defaults.** [config.py](../../core/app/config.py)
  reads settings once at import; `seed_user_password` is the precedent — a throwaway
  default for local/test, prod injects via SSM. The master key follows the same shape.
- **Secrets live in SSM in prod.** Requirements §CI/CD: the master encryption key is an
  SSM SecureString, injected out-of-band, never in repo/Terraform/state.
- **The audit seam pattern is set.** `record_platform_read_for_audit` in
  [scoping.py](../../core/app/tenancy/scoping.py#L129) is a named no-op `await`ed on the
  privileged path so P1.4 fills one body with no call-site churn — P1.3 mirrors it for
  reveals.
- **Test substrate is ready.** [core/tests/conftest.py](../../core/tests/) gives a
  session-scoped ephemeral Postgres (testcontainers) running `alembic upgrade head`, a
  real `db_session`, and a DB-backed `db_client`; `factories.py` seeds isolated users.
  Suite currently **135 passed**.
- **Alembic hygiene is in place.** [env.py](../../core/alembic/env.py)'s
  `include_name`/`include_object` filter restricts compare to `platform` + declared
  model schemas, so per-tenant hand-written tables don't surface as drift — P1.3's
  per-tenant `pii_demo` is covered by the existing filter; the new **platform**
  `tenant_data_keys` table is reflected normally.
- **Constraints** — `CLAUDE.md`: descriptive naming, booleans as yes/no questions,
  natural-language verbs, many small focused modules. Memory: minimal-churn
  insertion-style edits; dev *is* the local Docker stack, prod on EC2; single source of
  truth for shared data.

## 5. Proposed Design

### High-level approach
PII is encrypted with a per-tenant key the application unwraps from a stored,
master-key-wrapped root key. On a **write**, the service encrypts each PII field with
the tenant's encryption subkey (AES-256-GCM, the tenant id bound as additional
authenticated data) and computes a blind index of the normalized email/phone with the
tenant's blind-index subkey; both go to the row as `bytea`. On a **read**, the row is
fetched under the tenant role (`get_tenant_db`), the service decrypts in-process, and
the **response layer masks every PII field by default**. A **lookup** runs an
exact-match `WHERE email_blind_index = :index` entirely inside the tenant schema —
no decryption — proving duplicate detection. A **reveal** endpoint, guarded by
`Capability.REVEAL_PII`, returns one unmasked field and `await`s the audit + event
seams (no-ops today). The mock Medicare ID is **never revealable**, even for a
capable role.

> **Diagram:** [PII envelope & data flow](./diagrams/tdd-P1.3-pii-envelope-flow.excalidraw)
> — master key → unwrap per-tenant root key → HKDF encryption/blind-index subkeys;
> the write path (encrypt + blind-index), the masked read path, the blind-index
> lookup, and the guarded reveal path with its two no-op seams.

### Components added / changed (core service)

```
core/app/
  pii/
    __init__.py
    crypto.py            # pure primitives: aes_gcm encrypt/decrypt, wrap/unwrap,
                         #   hkdf_subkey, hmac_blind_index — no DB, no tenant logic
    keys.py              # TenantKeys (enc_key, index_key); load/unwrap from
                         #   platform.tenant_data_keys; in-process cache by tenant_id
    service.py           # encrypt_field / decrypt_field / compute_blind_index
                         #   (resolve per-tenant key, call crypto.py)
    masking.py           # mask_email / mask_phone / mask_dob / mask_medicare_id /
                         #   mask_generic; age_band_for(date_of_birth)
    reveal_seam.py       # on_pii_revealed(identity, entity_type, entity_id, field)
                         #   — named no-op; P1.4 audit + P1.5 event land here
  models/
    tenant_data_key.py   # TenantDataKey (platform schema): wrapped root key per tenant
    pii_demo.py          # PiiDemoRecord — schema-less, resolved via search_path
  pii_demo/
    __init__.py
    router.py            # create / list / get / lookup / reveal (tenant-scoped)
    schemas.py           # request + masked-by-default response models
  config.py              # + pii_master_key (base64 32 bytes; throwaway dev default)
  seed.py                # generate+wrap a root key per tenant; seed pii_demo rows
  main.py                # mount pii_demo_router
core/alembic/versions/
  0005_tenant_data_keys.py # platform.tenant_data_keys table + grants
  0006_pii_demo.py         # pii_demo table created in EACH tenant schema + grants
```

### Key hierarchy (envelope encryption)

```
PII_MASTER_KEY  (env / SSM SecureString; base64 of 32 bytes)
   │  AES-256-GCM unwrap (KMS-ready: swap for KMS Decrypt later)
   ▼
tenant_root_key  (random 32 bytes per tenant; stored WRAPPED in
                  platform.tenant_data_keys, generated at seed time)
   ├─ HKDF-SHA256(info=b"policyflow/field-encryption/v1") → enc_key   (32 bytes)
   └─ HKDF-SHA256(info=b"policyflow/blind-index/v1")       → index_key (32 bytes)
```

- **Why a stored wrapped root key, not derivation from the master:** it is the literal
  "master key wraps the data key" envelope the requirements name, it is the shape KMS
  produces (a wrapped data-key blob), and it leaves room for rotation (re-wrap the same
  root, or issue a new root and re-encrypt) without changing the master.
- **Why HKDF subkeys:** one stored key per tenant, but **encryption and MAC never share
  key material** (key-separation hygiene). Distinct `info` labels make the two subkeys
  independent.
- **Where the wrapped key lives & how it's read:** `platform.tenant_data_keys` (platform
  schema). The unwrapped subkeys are needed *during* a tenant-scoped request, but the
  tenant role has **no grant on `platform`** (P1.2), so the key is loaded via the
  **default login role** (which can read `platform`) through a dedicated short-lived
  session and then **cached in process** keyed by `tenant_id`. Wrapped blobs are useless
  without the env master key; only the *unwrapped* subkeys live in app memory (the master
  key already does). The tenant role can therefore never read any key material — the
  isolation story holds.
- **Key generation belongs to the seed, not the migration:** migrations create the
  *table*; the seed generates a random root key per tenant, wraps it with the master
  key, and inserts it (insert-if-absent → idempotent). No key material or crypto in
  migrations.

### Crypto primitives (`pii/crypto.py`) — pure, no DB

```python
def aes_gcm_encrypt(key: bytes, plaintext: str, associated_data: bytes) -> bytes:
    # returns nonce(12) || ciphertext || tag(16); random nonce per call
def aes_gcm_decrypt(key: bytes, blob: bytes, associated_data: bytes) -> str:
    # raises on auth failure (wrong key OR wrong associated_data)
def wrap_key(master_key: bytes, root_key: bytes) -> bytes        # aes_gcm_encrypt of raw bytes
def unwrap_key(master_key: bytes, wrapped: bytes) -> bytes
def hkdf_subkey(root_key: bytes, info: bytes) -> bytes           # 32-byte derived subkey
def hmac_blind_index(index_key: bytes, normalized_value: str) -> bytes  # HMAC-SHA256
def normalize_email(value: str) -> str                           # trim + lowercase
def normalize_phone(value: str) -> str                           # strip non-digits
```
- **AES-GCM associated data = the tenant id bytes.** A ciphertext authenticated for
  Tenant A fails to decrypt if presented under Tenant B's context — defense in depth on
  top of schema isolation.
- The blind index is **deterministic** (same normalized value + same tenant key → same
  bytes), which is exactly what enables equality lookup without decryption — and why it
  uses a **dedicated** key, never the encryption key.

### Data model changes

**`platform.tenant_data_keys` (migration `0005`, platform schema)** — the wrapped key
store. Columns: `tenant_id uuid` (PK; the `platform.tenants` id), `wrapped_root_key
bytea NOT NULL`, `created_at timestamptz NOT NULL DEFAULT now()`. Granted `SELECT` to
the **default login role only** (read during key load); **no grant to any tenant role**
and **no grant to `platform_reader`** (key material is never part of a cross-tenant
operational read). Reflected normally by Alembic (it is in `platform`).

**`pii_demo` (migration `0006`, one table per tenant schema)** — the demonstrator,
carrying every distinct field treatment from the matrix:

| Column | Type | Treatment shown |
|---|---|---|
| `id` | `uuid` PK | surrogate key (multiple rows → meaningful duplicate lookup) |
| `display_name` | `text` NOT NULL | **plaintext, searchable** (contrast: not app-encrypted) |
| `email_encrypted` | `bytea` NOT NULL | app-layer encrypted |
| `email_blind_index` | `bytea` NOT NULL | HMAC blind index (indexed, not unique) |
| `phone_encrypted` | `bytea` | app-layer encrypted |
| `phone_blind_index` | `bytea` | HMAC blind index (indexed) |
| `date_of_birth_encrypted` | `bytea` | app-layer encrypted |
| `age_band` | `text` NOT NULL | **derived, plaintext** |
| `mock_medicare_id_encrypted` | `bytea` | encrypted; **always masked, never revealed** |
| `created_at` | `timestamptz` NOT NULL | — |

Created **in each tenant schema** by a registry loop (same as `0004`), with explicit
per-tenant CRUD grants and a non-unique index on each blind-index column for lookup.
`PiiDemoRecord` is **schema-less** (resolved via `search_path`), like `TenantSettings`.

### Masking (`pii/masking.py`) — render layer

| Field | Masked form | Revealable? |
|---|---|---|
| email | `j***@e***.com` (first char of local + first char of domain + TLD) | yes (REVEAL_PII) |
| phone | `***-***-1234` (last 4) | yes |
| date of birth | `****-**-**` (fully masked; `age_band` shown instead) | yes |
| mock Medicare ID | `***-**-1234` (last 4) | **never** (403/422 on reveal) |
| display_name | unmasked | n/a (plaintext) |

**Age bands** (derived at write from DOB): `<18`, `18-34`, `35-49`, `50-64`, `65+`
(the `65+` boundary is the Medicare-eligibility signal P2 uses).

### Interfaces

**PII service (`pii/service.py`)**
```python
async def encrypt_field(tenant_id: UUID, plaintext: str) -> bytes
async def decrypt_field(tenant_id: UUID, blob: bytes) -> str
async def compute_blind_index(tenant_id: UUID, normalized_value: str) -> bytes
# each resolves TenantKeys(tenant_id) from the cache (load+unwrap on first use)
```

**Reveal seam (`pii/reveal_seam.py`)**
```python
async def on_pii_revealed(
    identity: Identity, entity_type: str, entity_id: UUID, field_name: str
) -> None:
    """P1.4 audit + P1.5 `pii.revealed` event land here — no-op today."""
    return None
```

**HTTP endpoints (all `require_authenticated` + `get_tenant_db`; tenant-scoped)**
- `POST /api/pii-demo` — create a record (`require_capability(CREATE_EDIT_RECORDS)`);
  encrypts fields + computes blind indexes + derives `age_band` on write. Returns the
  masked record. Exercises the full write path and makes duplicate lookup demonstrable.
- `GET /api/pii-demo` — list the tenant's records, **masked**.
- `GET /api/pii-demo/{id}` — one record, **masked** (404 if absent in this tenant).
- `POST /api/pii-demo/lookup` — body `{email}` or `{phone}`; computes the blind index
  and returns matching records (masked) via `WHERE *_blind_index = :index` — **no
  decryption**. The exact-match duplicate-detection proof.
- `POST /api/pii-demo/{id}/reveal` — body `{field}`; `require_capability(REVEAL_PII)`;
  returns `{field, value}` unmasked for a revealable field; `await`s `on_pii_revealed`.
  `mock_medicare_id` → `422 {"detail":"field is never revealable"}`. Read-Only and
  Platform-Admin lack the capability → `403`.

### Primary flows
```
Write   POST /api/pii-demo {email, phone, dob, medicare_id, display_name}
  require_capability(CREATE_EDIT_RECORDS) + get_tenant_db (role+search_path = tenant)
  keys = TenantKeys(tenant_id)            # load+unwrap once, then cached
  email_encrypted   = AESGCM(enc_key).encrypt(tenant_id_aad, email)
  email_blind_index = HMAC(index_key, normalize_email(email))
  age_band          = age_band_for(dob)   # plaintext
  INSERT pii_demo(...)  → resolves to <tenant_schema>.pii_demo
  ◀── 201 {email:"j***@e***.com", age_band:"65+", medicare_id:"***-**-1234", ...}

Lookup  POST /api/pii-demo/lookup {email:"JANE@example.com "}
  index = HMAC(index_key, normalize_email(...))   # "jane@example.com"
  SELECT * FROM pii_demo WHERE email_blind_index = :index   # NO decryption
  ◀── 200 {matches:[{id, email:"j***@e***.com", ...}]}      # duplicate detected

Reveal  POST /api/pii-demo/{id}/reveal {field:"email"}
  require_capability(REVEAL_PII) → else 403
  row = SELECT ... WHERE id=:id     # tenant-scoped; 404 if not in this tenant
  value = decrypt_field(tenant_id, row.email_encrypted)
  await on_pii_revealed(identity, "pii_demo", id, "email")   # no-op (P1.4 + P1.5)
  ◀── 200 {field:"email", value:"jane@example.com"}
  # field == "mock_medicare_id" → 422 (never revealable)

Isolation (inherited + new): a Florida user's read runs under tenant_florida +
  search_path=florida → sees only florida.pii_demo; a Sunshine ciphertext decrypted
  with Florida's key fails AES-GCM authentication (per-tenant key + tenant_id AAD).
```

### Alembic / hygiene
- `0005`/`0006` are **hand-written** (platform table + grants; per-tenant tables via a
  registry loop) matching `0003`/`0004`'s style.
- The existing `env.py` filter already excludes per-tenant schemas, so `pii_demo` does
  not surface as drift; `platform.tenant_data_keys` **is** in the model metadata
  (`TenantDataKey`, `schema="platform"`) so autogenerate/`alembic check` see it
  normally and report no drift.

## 6. Decisions

| # | Decision | Chosen | Alternatives considered | Rationale |
|---|---|---|---|---|
| 1 | Crypto library & cipher | **pyca `cryptography`, AES-256-GCM** (nonce‖ciphertext‖tag, tenant id as AAD) | Fernet (AES-128-CBC+HMAC); PyNaCl (XSalsa20-Poly1305) | Authenticated encryption, AES-256, full control of the envelope blob, and matches how KMS encrypts so the managed-KMS swap is 1:1. AAD binds ciphertext to its tenant. |
| 2 | Per-tenant key model | **Stored wrapped root key + HKDF subkeys** (enc + blind-index) | Derive all keys from master (no storage); two separately-stored keys | The literal "master wraps the data key" envelope, KMS-shaped, rotation-ready; HKDF gives key separation (encryption vs MAC never share material) with a single stored key per tenant. |
| 3 | Encrypt/decrypt mechanism | **Explicit helper in a thin PII service layer** | SQLAlchemy `TypeDecorator`; TypeDecorator + `ContextVar` | Per-tenant keys are request-scoped; a column type's bind/result processors can't get tenant context without hidden global state. Explicit keeps key handling visible/auditable and fits "small focused modules." |
| 4 | Masking placement | **Mask in the API response layer; reveal endpoint bypasses under capability** | Mask in the read/repository layer | Decryption is a data concern, masking a render concern; separating them keeps the read path clean and the masked-by-default rule enforced at the boundary. |
| 5 | Where the wrapped key is stored & read | **`platform.tenant_data_keys`, read via the default login role, unwrapped subkeys cached in process** | Store in each tenant schema (tenant role reads its own key); no cache (unwrap per request) | The tenant role has no `platform` grant, so it can never see key material — isolation holds; the master key is the only thing that unlocks a blob; an in-process cache avoids unwrapping on every request. Keys are static between deploys. |
| 6 | Key generation site | **Seed generates + wraps the root key (idempotent)**; migration creates only the table | Generate in the migration | Migrations shouldn't perform crypto or hold key material; the seed already owns demo data and runs after migrate, mirroring `tenant_settings`. |
| 7 | Isolation demonstrator | **A real minimal `pii_demo` entity** (per tenant schema) covering every field treatment | A throwaway crypto probe; building the real `contact` now | "Stubs behind real seams" — `pii_demo` is a convincing showcase and a stable test target without claiming P1.7's `contact`. Schema-less model + per-schema table reuse the proven `tenant_settings` pattern. |
| 8 | Reveal scope in P1.3 | **Ship a guarded reveal endpoint now; audit + event are named no-op seams** | Ship only masking + the decrypt helper, defer the endpoint to P1.6 | Confirmed at the gate. Building the seam now means P1.4/P1.5/P1.6 fill bodies with zero call-site churn — the same pattern that worked for `record_platform_read_for_audit`. |
| 9 | Master key config | **`PII_MASTER_KEY` (base64, 32 bytes); throwaway dev/test default; prod via SSM; fail-fast on a bad/short key at import** | A required env var with no default (breaks local/test boot) | Mirrors `seed_user_password`: local/test stays runnable, prod injects a real SecureString, and an undecodable/short key fails boot fast rather than corrupting data. |
| 10 | Mock Medicare ID reveal | **Never revealable — `422` even for `REVEAL_PII`** | Treat like other fields | Requirements: "always masked, no full reveal in any UI." Enforced server-side so no UI can bypass it. |

## 7. Risks and Open Questions

- **Risk #3 (the phase's reason to exist): blind index + schema-per-tenant coexisting.**
  The blind index must compute and match **inside a tenant schema under the tenant
  role**, with per-tenant keys. *Mitigation/proof:* a DB-substrate test runs the lookup
  under `get_tenant_db` (tenant role + `search_path`) and asserts exact-match returns the
  row without decryption; a second test asserts Tenant A's ciphertext fails to decrypt
  under Tenant B's key. *Kill criterion (from the register):* if exact-match can't run
  within a tenant schema, revisit per-tenant key derivation before intake (P1.7).
- **Unwrapped keys live in process memory.** The cache holds plaintext subkeys.
  *Accepted:* the master key is already in process env; wrapped blobs are inert without
  it; the tenant role can't read the store. A future hardening note (with the dedicated
  login role from P1.2) is to scope the cache lifetime.
- **Master key change invalidates stored wrapped keys.** If `PII_MASTER_KEY` changes,
  existing wrapped root keys can't unwrap → decryption fails. *Accepted:* deploys
  reset+reseed (Requirements §CI/CD); locally the key + volume persist together. Rotation
  tooling is an explicit non-goal.
- **AAD choice couples ciphertext to tenant id.** Re-keying or moving a row between
  tenants would break decryption. *Accepted:* tenants are fixed and rows never move; the
  coupling is a feature (cross-tenant ciphertext reuse fails authentication).
- **No raw PII in logs.** The service must never log plaintext or keys; reveal responses
  are the only place plaintext crosses the boundary, and only under capability + the
  audit seam. *Mitigation:* no logging of field values in `pii/`; a test asserts the
  reveal path is the sole plaintext egress.
- **`bytea` round-tripping under asyncpg.** Encrypted columns are binary. *Mitigation:*
  SQLAlchemy `LargeBinary`/`sa.LargeBinary`; a round-trip substrate test.
- **Open (deferred, not blocking):** audit record shape for reveals → **P1.4**;
  `pii.revealed` envelope + outbox → **P1.5**; click-to-reveal UI → **P1.6**; key
  rotation + real KMS → future; Address/Policy-Number columns → with their entities.

## 8. Rollout / Verification

**Manual verification (local stack)**
1. Set `PII_MASTER_KEY` (or use the dev default). `docker-compose up` → boot runs
   `alembic upgrade head` (creates `platform.tenant_data_keys` and per-schema
   `pii_demo`) then `seed` (wraps+stores a root key per tenant; inserts demo PII rows,
   Sunshine including a mock Medicare ID). Logs show counts.
2. Log in as a Sunshine Agent → `GET /api/pii-demo` → `200` with **masked** values
   (`j***@e***.com`, `***-**-1234`, `age_band` in plaintext).
3. `POST /api/pii-demo/lookup {email}` with a seeded email in mixed case/whitespace →
   the matching record returns (blind-index hit) without revealing more than masked
   fields.
4. `POST /api/pii-demo/{id}/reveal {field:"email"}` as the Agent → `200` unmasked; as a
   Read-Only user → `403`; with `field:"mock_medicare_id"` → `422`.
5. `psql`: `SELECT email_encrypted FROM sunshine.pii_demo` → opaque bytes (no plaintext
   email visible at rest).

**Automated verification (pytest, ephemeral Postgres)**
- **Primitives (no DB):** encrypt→decrypt round-trip; wrong-key and wrong-AAD decrypt
  raise; wrap/unwrap round-trip; HKDF subkeys differ from each other and from the root;
  blind index is deterministic and normalization-correct (email case/space, phone
  punctuation); masking format per field; age-band boundary table (incl. the 65+ edge).
- **Encrypted at rest (DB):** after a create, the raw `*_encrypted` column bytes do not
  contain the plaintext; `age_band` is stored as readable plaintext.
- **Blind-index exact-match within a tenant schema (Risk #3):** under `get_tenant_db`
  (tenant role + `search_path`), `lookup` by normalized email returns the row **without
  decryption**; a non-matching value returns none.
- **Per-tenant key isolation:** a Sunshine-encrypted blob fails to decrypt with the
  Florida key (AES-GCM auth failure); each tenant's `pii_demo` rows are visible only to
  that tenant (inherits `get_tenant_db`, asserted A-vs-B).
- **Masking & reveal:** list/get return masked by default; reveal returns unmasked for a
  capable role and revealable field; `403` without `REVEAL_PII`; `422` for
  `mock_medicare_id`; `on_pii_revealed` is invoked on the reveal path.
- **Migration health:** `alembic upgrade head` then `downgrade` round-trips;
  `alembic check` reports no drift (`tenant_data_keys` reflected in `platform`; per-tenant
  `pii_demo` excluded by the existing filter).

**Rollout / compatibility**
- New runtime dependency: `cryptography` added to `core/requirements.txt`.
- New env var `PII_MASTER_KEY`: Terraform provisions an SSM SecureString parameter
  (value injected out-of-band) and the container reads it into the environment; local/test
  use the throwaway default. (Terraform parameter wiring is the one infra touch; the value
  never enters repo/state.)
- Additive migrations `0005`/`0006` on top of `0004`; pre-go-live reset+reseed acceptable;
  reversible by reverting migrations + code.
- Must stay green behind the pre-commit gate and CI before P1.4 begins.

## 9. Work Breakdown

Ordered simplest-first — pure primitives, then the key envelope, then the service, then
the demonstrator table, then masking + endpoints, then the acceptance proof. Each item is
narrow and independently reviewable.

1. **Dependency + config.** Add `cryptography` to `core/requirements.txt`; add
   `pii_master_key` to `config.py` (base64-decode, length-check, throwaway dev default,
   fail-fast on a bad key). Unit-test the config decode/validation.
2. **Crypto primitives (`pii/crypto.py`).** `aes_gcm_encrypt`/`decrypt` (AAD),
   `wrap_key`/`unwrap_key`, `hkdf_subkey`, `hmac_blind_index`, `normalize_email`/
   `normalize_phone`. Pure functions; full unit tests (round-trips, wrong-key/AAD,
   determinism, normalization). No DB.
3. **Key store table + model (`0005`, `TenantDataKey`).** Migration creating
   `platform.tenant_data_keys` + `SELECT` grant to the login role only; the
   platform-schema ORM model. Substrate test: table exists with correct grants.
4. **Key resolution + cache (`pii/keys.py`).** `TenantKeys` (enc + index subkeys);
   load the wrapped root key via the default login role, unwrap with the master key,
   HKDF-derive subkeys, cache by `tenant_id`. DB test: load→unwrap→derive yields stable
   subkeys; cache hit avoids re-read.
5. **PII service (`pii/service.py`).** `encrypt_field`/`decrypt_field`/
   `compute_blind_index` over `keys.py` + `crypto.py`. DB test: encrypt with Tenant A,
   decrypt back; decrypt with Tenant B's context fails.
6. **Seed: per-tenant root keys.** Extend `seed.py` to generate a random root key per
   tenant, wrap with the master key, insert-if-absent into `tenant_data_keys`. Idempotent;
   DB test asserts one wrapped key per tenant after seed.
7. **Masking + age band (`pii/masking.py`).** `mask_email`/`mask_phone`/`mask_dob`/
   `mask_medicare_id`, `age_band_for`. Pure; unit-tested (formats + age-band boundaries).
8. **`pii_demo` table + model (`0006`, `PiiDemoRecord`).** Schema-less model; hand-written
   DDL creating the table in each tenant schema + per-tenant CRUD grants + blind-index
   indexes; substrate test the table exists in both schemas.
9. **Reveal seam (`pii/reveal_seam.py`).** Named no-op `on_pii_revealed`; unit test it is
   awaitable and returns `None` (the place P1.4/P1.5 fill).
10. **Demonstrator endpoints (`pii_demo/router.py` + `schemas.py`).** create / list / get,
    masked-by-default responses, via `get_tenant_db`; mount in `main.py`; seed a couple of
    demo rows per tenant. Endpoint tests: masked defaults; tenant A-vs-B isolation.
11. **Blind-index lookup endpoint.** `POST /api/pii-demo/lookup`; exact-match by blind
    index, no decryption. Endpoint test: mixed-case/whitespace email hits; miss returns
    none — **the Risk #3 proof at the API layer**.
12. **Guarded reveal endpoint + acceptance suite + hygiene.** `POST /api/pii-demo/{id}/
    reveal` (capability gate, `on_pii_revealed`, Medicare-ID `422`); the full acceptance
    suite (encrypted-at-rest, blind-index within tenant schema, per-tenant key isolation,
    masking, reveal RBAC); `alembic check`/downgrade round-trip. Confirm CI green.
```
