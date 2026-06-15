"""The `pii_demo` HTTP surface: create / get a record, masked by default.

This is the thin route layer that proves the masked write/read path end-to-end.
It adds no new crypto, masking, or scoping logic of its own; it composes the
earlier P1.3 epics' pieces:

- **Create** (`POST /api/pii-demo/`) encrypts each PII field with
  `encrypt_field`, computes the email (and phone) blind index with
  `compute_blind_index` over the normalized value, derives the plaintext
  `age_band` from the required date of birth, and stores the row. It is gated by
  `require_capability(CREATE_EDIT_RECORDS)`. Since P1.4 it also writes one
  tenant-store `record.created` audit record naming the written fields (never
  their values) before it returns — the only audited surface in this router.
  Since P1.5 it additionally enqueues one `record.created` event into this
  tenant's `outbox` on the same request transaction as the row insert (the
  transactional outbox), carrying the entity reference plus non-PII fields only.
- **Get** (`GET /api/pii-demo/{record_id}`) reads one record by id and returns it
  masked. It only requires an authenticated, tenant-scoped caller.
- **Lookup** (`POST /api/pii-demo/lookup`) finds records by the blind-index
  fingerprint of a normalized email or phone — exact-match duplicate detection
  with **no decryption** on this path — and returns every match masked. It only
  requires an authenticated, tenant-scoped caller.

All ride `get_tenant_db`, so isolation is automatic — there is **no tenant
parameter** anywhere — and the inherited 401 (no session) / 400 (tenantless
Platform Admin) / per-tenant 404 come for free. Responses use the named-envelope
style the other routers use: `{"record": …}` / `{"records": […]}` /
`{"matches": […]}`.

**Masked by default (the phase's whole point).** Every record leaves through
`_masked_record`, which decrypts each stored field in-process and returns only the
masked display string — the plaintext is reconstructed only long enough to mask
it and is never returned. Date of birth is the one field never decrypted on this
path: its masker is the constant `****-**-**` and the plaintext `age_band` is
shown in its place (the unmasked date of birth is reachable only via the guarded
reveal endpoint, Epic 12). Using the same builder on create proves the
encrypt → decrypt → mask round-trip works.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit.records import EventType, Outcome
from ..audit.service import record_audit_event
from ..auth.dependencies import require_authenticated, require_capability
from ..auth.provider import Identity
from ..auth.rbac import Capability
from ..events.catalog import EventType as EventBusEventType
from ..events.envelope import build_envelope
from ..events.outbox import enqueue_event
from ..models.pii_demo import PiiDemoRecord
from ..pii.crypto import normalize_email, normalize_phone
from ..pii.masking import (
    age_band_for,
    mask_dob,
    mask_email,
    mask_medicare_id,
    mask_phone,
)
from ..pii.reveal_seam import on_pii_revealed
from ..pii.service import compute_blind_index, decrypt_field, encrypt_field
from ..tenancy.scoping import get_tenant_db
from .schemas import CreateRecordRequest, LookupRequest, RevealRequest

router = APIRouter(prefix="/api/pii-demo")

# The reveal endpoint's two field allow-lists, the single source of truth for
# what `POST /{record_id}/reveal` will unmask.
#
# `REVEALABLE_FIELDS` maps each accepted request field name to the encrypted
# column attribute on `PiiDemoRecord` whose blob the handler decrypts. Only these
# three fields can ever be revealed; any other name (a typo, `display_name`,
# `age_band`) falls through to a generic 422.
#
# `NEVER_REVEALABLE_FIELDS` is the explicit deny-list: the mock Medicare id is
# refused server-side with a distinct message so no UI can ever bypass it, and the
# refusal happens before any database read or decryption.
REVEALABLE_FIELDS: dict[str, str] = {
    "email": "email_encrypted",
    "phone": "phone_encrypted",
    "date_of_birth": "date_of_birth_encrypted",
}
NEVER_REVEALABLE_FIELDS: frozenset[str] = frozenset({"mock_medicare_id"})


async def _masked_record(tenant_id: uuid.UUID, record: PiiDemoRecord) -> dict:
    """Build the masked response body for one record — the single read shape.

    The one builder every read path (create, get, and the list endpoint) returns
    records through, so the masked-by-default contract lives in exactly one place.
    `id`, `created_at`, the plaintext `display_name`, and the plaintext `age_band`
    are returned as-is; every encrypted field is decrypted in-process and then
    masked, so only the masked display string ever leaves.

    Date of birth is deliberately **not** decrypted here: `mask_dob` is the
    constant `****-**-**` and the plaintext `age_band` is shown in its place, so a
    present `date_of_birth_encrypted` renders as that constant and an absent one as
    `null`. An absent optional field (`phone`, `mock_medicare_id`) renders as
    `null` rather than a masked-of-nothing string.
    """
    masked_email = mask_email(await decrypt_field(tenant_id, record.email_encrypted))

    masked_phone = None
    if record.phone_encrypted is not None:
        masked_phone = mask_phone(
            await decrypt_field(tenant_id, record.phone_encrypted)
        )

    masked_medicare_id = None
    if record.mock_medicare_id_encrypted is not None:
        masked_medicare_id = mask_medicare_id(
            await decrypt_field(tenant_id, record.mock_medicare_id_encrypted)
        )

    masked_date_of_birth = None
    if record.date_of_birth_encrypted is not None:
        masked_date_of_birth = mask_dob("")

    return {
        "id": record.id,
        "display_name": record.display_name,
        "email": masked_email,
        "phone": masked_phone,
        "date_of_birth": masked_date_of_birth,
        "age_band": record.age_band,
        "mock_medicare_id": masked_medicare_id,
        "created_at": record.created_at,
    }


@router.post("/", status_code=201)
async def create_record(
    new_record: CreateRecordRequest,
    identity: Identity = Depends(
        require_capability(Capability.CREATE_EDIT_RECORDS)
    ),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Create one `pii_demo` record for the caller's tenant; return it masked.

    Encrypts `email` (and `phone` / `mock_medicare_id` when present) and the ISO
    date of birth with `encrypt_field`, computes the email (and phone) blind index
    over the normalized value with `compute_blind_index`, and derives the
    plaintext `age_band` from the required date of birth. The row is added,
    flushed, and refreshed so the server-default `created_at` is populated before
    it is returned through the shared `_masked_record` builder under the
    `{"record": …}` envelope with a 201.

    The guard hands the route an `Identity` only when the caller holds
    `CREATE_EDIT_RECORDS` (every other role gets a 403, the anonymous caller a
    401); `get_tenant_db` scopes the write to the caller's own schema and rejects
    a tenantless Platform Admin with a 400 — all inherited, no tenant parameter.

    Since P1.4 it also writes one tenant-store `record.created` audit record via
    `record_audit_event`, carrying the **names** of the fields the caller supplied
    (never their values), before it returns — so the create is audited with zero
    call-site churn. The audit write runs on its own `audit_writer` session routed
    to this tenant's schema, and is awaited **before** the `return`, so a failing
    audit write aborts the create: the exception propagates and `get_tenant_db`
    rolls the insert back (strict, never an unaudited record).

    Since P1.5 it also enqueues one `record.created` event into this tenant's
    `outbox` via `enqueue_event` on the **same** request session and transaction as
    the row insert (the transactional outbox — the record and its event both land
    or both roll back). The enqueue sits **before** the audit write, so a failing
    audit write rolls back both the record and the outbox row. The event's payload
    carries the entity reference plus the coarse `age_band` and the names-only
    written-field list — never a PII value.
    """
    tenant_id = identity.tenant_id

    email_encrypted = await encrypt_field(tenant_id, new_record.email)
    email_blind_index = await compute_blind_index(
        tenant_id, normalize_email(new_record.email)
    )
    date_of_birth_encrypted = await encrypt_field(
        tenant_id, new_record.date_of_birth.isoformat()
    )
    age_band = age_band_for(new_record.date_of_birth)

    phone_encrypted = None
    phone_blind_index = None
    if new_record.phone is not None:
        phone_encrypted = await encrypt_field(tenant_id, new_record.phone)
        phone_blind_index = await compute_blind_index(
            tenant_id, normalize_phone(new_record.phone)
        )

    mock_medicare_id_encrypted = None
    if new_record.mock_medicare_id is not None:
        mock_medicare_id_encrypted = await encrypt_field(
            tenant_id, new_record.mock_medicare_id
        )

    record = PiiDemoRecord(
        display_name=new_record.display_name,
        email_encrypted=email_encrypted,
        email_blind_index=email_blind_index,
        phone_encrypted=phone_encrypted,
        phone_blind_index=phone_blind_index,
        date_of_birth_encrypted=date_of_birth_encrypted,
        age_band=age_band,
        mock_medicare_id_encrypted=mock_medicare_id_encrypted,
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)

    # The names of the fields the caller actually supplied — the three required
    # ones always, plus each optional only when present. These are the logical
    # request field names (mirroring `CreateRecordRequest`), never the encrypted
    # column names and never the values, so the audit trail itself never leaks PII.
    written_field_names = [
        name
        for name in (
            "display_name",
            "email",
            "date_of_birth",
            "phone",
            "mock_medicare_id",
        )
        if getattr(new_record, name) is not None
    ]

    # Enqueue a `record.created` event into this tenant's outbox on the **same**
    # request session and transaction as the row insert above (the transactional
    # outbox: the record and its event both land or both roll back, never one
    # without the other). Placed **before** the audit write so a failing audit
    # write rolls back both the record and the outbox row (atomic, no orphan
    # outbox row), and an enqueue failure happens before the audit write commits
    # (no orphan audit row); it also keeps the outbox write adjacent to the insert
    # it mirrors. The payload carries the entity reference plus the coarse,
    # already-unmasked `age_band` and the names-only `written_field_names` —
    # **never a PII value** (the no-PII-snapshot contract). `enqueue_event` only
    # flushes; `get_tenant_db`'s `async with db.begin()` still owns the commit.
    await enqueue_event(
        db,
        build_envelope(
            event_type=EventBusEventType.RECORD_CREATED,
            tenant_id=tenant_id,
            actor_user_id=identity.user_id,
            actor_role=identity.role,
            payload={
                "entity_type": "pii_demo",
                "entity_id": str(record.id),
                "age_band": age_band,
                "fields": written_field_names,
            },
        ),
    )

    await record_audit_event(
        tenant_id=tenant_id,
        actor_user_id=identity.user_id,
        actor_role=identity.role,
        event_type=EventType.RECORD_CREATED,
        outcome=Outcome.SUCCESS,
        entity_type="pii_demo",
        entity_id=record.id,
        field_names=written_field_names,
    )

    return {"record": await _masked_record(tenant_id, record)}


@router.get("/")
async def list_records(
    identity: Identity = Depends(require_authenticated),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Return all of the caller's tenant records, masked, oldest first.

    Like get, there is **no tenant parameter** — `get_tenant_db` scopes the query
    to the caller's own schema, so the list can only ever contain that one
    tenant's records; another tenant's rows are physically out of reach. Rows are
    ordered by `created_at` for a stable demo order, and each is returned through
    the shared `_masked_record` builder under the `{"records": […]}` envelope.
    The dependency chain inherits 401 (no session) and 400 (tenantless caller).
    """
    records = (
        await db.execute(
            select(PiiDemoRecord).order_by(PiiDemoRecord.created_at)
        )
    ).scalars().all()

    tenant_id = identity.tenant_id
    return {
        "records": [
            await _masked_record(tenant_id, record) for record in records
        ]
    }


@router.post("/lookup")
async def lookup_records(
    lookup: LookupRequest,
    identity: Identity = Depends(require_authenticated),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Find this tenant's records by the blind index of an email or phone, masked.

    This proves exact-match duplicate detection **without decryption**: the
    supplied field is normalized (`normalize_email` / `normalize_phone`), its
    per-tenant blind-index fingerprint is computed with `compute_blind_index`, and
    the matching `*_blind_index` column is queried for equality. Every match is
    returned through the shared `_masked_record` builder under the
    `{"matches": […]}` envelope; a miss returns `{"matches": []}` with a 200 (an
    empty result is a normal answer, not a 404).

    `LookupRequest` requires exactly one of `email` / `phone` (neither / both →
    422), so exactly one branch runs here. There is **no tenant parameter** —
    `get_tenant_db` scopes the equality query to the caller's own schema, so a
    value matching in another tenant is physically out of reach and yields an
    empty result; the dependency chain inherits 401 (no session) and 400
    (tenantless caller).
    """
    tenant_id = identity.tenant_id

    if lookup.email is not None:
        blind_index = await compute_blind_index(
            tenant_id, normalize_email(lookup.email)
        )
        match_condition = PiiDemoRecord.email_blind_index == blind_index
    else:
        blind_index = await compute_blind_index(
            tenant_id, normalize_phone(lookup.phone)
        )
        match_condition = PiiDemoRecord.phone_blind_index == blind_index

    records = (
        await db.execute(
            select(PiiDemoRecord)
            .where(match_condition)
            .order_by(PiiDemoRecord.created_at)
        )
    ).scalars().all()

    return {
        "matches": [
            await _masked_record(tenant_id, record) for record in records
        ]
    }


@router.get("/{record_id}")
async def get_record(
    record_id: uuid.UUID,
    identity: Identity = Depends(require_authenticated),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Return one of the caller's tenant records by id, masked.

    There is deliberately **no tenant parameter** — `get_tenant_db` points the
    session's `search_path` at the caller's own schema, so the lookup resolves to
    that one tenant. A record id absent in this tenant (whether it does not exist
    or belongs to another tenant) yields a 404, so a caller can neither read nor
    probe for another tenant's records. The dependency chain inherits 401 (no
    session) and 400 (tenantless caller) for free.

    The matched record is returned through the shared `_masked_record` builder
    under the `{"record": …}` envelope.
    """
    record = (
        await db.execute(
            select(PiiDemoRecord).where(PiiDemoRecord.id == record_id)
        )
    ).scalar_one_or_none()

    if record is None:
        raise HTTPException(status_code=404, detail="record not found")

    return {"record": await _masked_record(identity.tenant_id, record)}


@router.post("/{record_id}/reveal")
async def reveal_field(
    record_id: uuid.UUID,
    reveal: RevealRequest,
    identity: Identity = Depends(require_capability(Capability.REVEAL_PII)),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Decrypt and return **one** unmasked field of one of the caller's records.

    This is the only place plaintext PII crosses the API boundary, so it is the
    most guarded route here. It composes only existing pieces — no new crypto,
    masking, or scoping. The flow is:

    1. **Refuse the mock Medicare id outright** (`NEVER_REVEALABLE_FIELDS`) with a
       distinct `422 "field is never revealable"`, enforced server-side so no UI
       can bypass it.
    2. **Refuse any other unknown field** with a generic `422 "field is not
       revealable"`. Both field checks run **before** the database read, because
       the refusal is about the field, not the record — a never-revealable or
       unknown field is a 422 even for an id that does not exist.
    3. **Fetch the record by id** within the caller's tenant schema; an id absent
       in this tenant (missing or another tenant's) is a `404 "record not found"`,
       reusing get's string.
    4. **Decrypt** the requested field's stored blob with `decrypt_field`. An
       absent optional field (e.g. a record with no phone) is returned as
       `value: null` with a 200 — the same uniform call site, matching the masked
       read's `null` rendering of absent optionals.
    5. **Await the reveal seam** (`on_pii_revealed`) *before* returning, so the
       later audit (P1.4) and event (P1.5) record the reveal before the value
       leaves — with zero call-site churn here.
    6. Return `{"field": …, "value": …}`.

    The guard hands the route an `Identity` only when the caller holds
    `REVEAL_PII` (Read-Only and Platform Admin lack it → 403, the anonymous caller
    → 401); `get_tenant_db` points the session's `search_path` at the caller's own
    schema, so a caller can only ever reveal their own tenant's record — all
    inherited, no tenant parameter. `decrypt_field` additionally binds `tenant_id`
    as AES-GCM associated data, so even a cross-tenant blob would fail to decrypt.
    """
    if reveal.field in NEVER_REVEALABLE_FIELDS:
        raise HTTPException(status_code=422, detail="field is never revealable")

    if reveal.field not in REVEALABLE_FIELDS:
        raise HTTPException(status_code=422, detail="field is not revealable")

    record = (
        await db.execute(
            select(PiiDemoRecord).where(PiiDemoRecord.id == record_id)
        )
    ).scalar_one_or_none()

    if record is None:
        raise HTTPException(status_code=404, detail="record not found")

    encrypted_blob = getattr(record, REVEALABLE_FIELDS[reveal.field])
    value = (
        await decrypt_field(identity.tenant_id, encrypted_blob)
        if encrypted_blob is not None
        else None
    )

    await on_pii_revealed(identity, "pii_demo", record_id, reveal.field)

    return {"field": reveal.field, "value": value}
