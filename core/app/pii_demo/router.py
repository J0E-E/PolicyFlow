"""The `pii_demo` HTTP surface: create / get a record, masked by default.

This is the thin route layer that proves the masked write/read path end-to-end.
It adds no new crypto, masking, or scoping logic of its own; it composes the
earlier P1.3 epics' pieces:

- **Create** (`POST /api/pii-demo/`) encrypts each PII field with
  `encrypt_field`, computes the email (and phone) blind index with
  `compute_blind_index` over the normalized value, derives the plaintext
  `age_band` from the required date of birth, and stores the row. It is gated by
  `require_capability(CREATE_EDIT_RECORDS)`.
- **Get** (`GET /api/pii-demo/{record_id}`) reads one record by id and returns it
  masked. It only requires an authenticated, tenant-scoped caller.

Both ride `get_tenant_db`, so isolation is automatic — there is **no tenant
parameter** anywhere — and the inherited 401 (no session) / 400 (tenantless
Platform Admin) / per-tenant 404 come for free. Responses use the named-envelope
style the other routers use: `{"record": …}`.

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

from ..auth.dependencies import require_authenticated, require_capability
from ..auth.provider import Identity
from ..auth.rbac import Capability
from ..models.pii_demo import PiiDemoRecord
from ..pii.crypto import normalize_email, normalize_phone
from ..pii.masking import (
    age_band_for,
    mask_dob,
    mask_email,
    mask_medicare_id,
    mask_phone,
)
from ..pii.service import compute_blind_index, decrypt_field, encrypt_field
from ..tenancy.scoping import get_tenant_db
from .schemas import CreateRecordRequest

router = APIRouter(prefix="/api/pii-demo")


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
