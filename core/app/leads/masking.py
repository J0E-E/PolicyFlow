"""The single masked read shape for a lead — one builder, every read path.

This is the lead equivalent of `pii_demo`'s `_masked_record`: the one place a
stored `Lead` row is turned into the masked dictionary returned on every read.
Both the list endpoint (the queue) and the detail endpoint (Epics 11, 7) return a
lead through **this one builder**, so the masked-by-default contract — what is
shown in the clear, what is masked, and what never leaves the server at all —
lives in exactly one place and the two surfaces can never drift apart.

It adds no crypto or masking of its own. It composes the earlier P1.3 pieces:
the PII service seam (`app.pii.service.decrypt_field`) to turn a stored blob back
into plaintext just long enough to mask it, and the pure render-layer maskers
(`app.pii.masking`: `mask_email`, `mask_phone`, `mask_dob`, `mask_generic`).

Three rules govern the shape (all locked at the gate):

- **Plaintext as-is** — the non-sensitive columns (`id`, names, `age_band`,
  `zip_code`, the product-line keys, `notes`, `rejection_reason`, `lead_source`,
  `status`, the owner and duplicate-linkage bookkeeping, the timestamps) are
  returned unchanged. The
  stored plaintext `age_band` is shown directly — it is **not** recomputed from
  the (never-decrypted-here) date of birth.
- **Masked** — `email` and `phone` are decrypted in-process and then masked, so
  only the masked display string ever leaves. Date of birth is **never decrypted
  on this path**: `mask_dob` is the constant `****-**-**` and the plaintext
  `age_band` is shown in its place. Street address gets the same blob-presence
  treatment as date of birth — `mask_generic()` (`***`) when the encrypted blob is
  present, `null` when absent — judged from blob presence with **no decryption**.
- **Excluded** — the two blind indexes (`email_blind_index` / `phone_blind_index`),
  the `correlation_id`, and the raw `demo_session_id` are internal trace / matching
  columns and never reach the wire. The raw session id stays server-side; the read
  surface gets only the two **derived booleans** below.

Two derived markers (P1.8 Epic 6) let the UI distinguish shared seed rows from the
caller's own session rows **without ever exposing the raw `demo_session_id`**. Both
are derived from the caller's session id (the new `demo_session_id` keyword arg),
gated exactly like the Epic 5 write guard: both are `False` for a session-less
caller (no demo cookie), so the non-demo read surface is unchanged.

- **`is_seed`** — `True` when the caller is in a live demo session **and** the row is
  a shared seed row (`lead.demo_session_id IS NULL`): a row every visitor sees,
  read-only to a demo visitor.
- **`is_session_record`** — `True` when the caller is in a live demo session **and**
  the row belongs to **that** session (`lead.demo_session_id == demo_session_id`):
  the visitor's own row.

An absent optional field (`preferred_contact_method`, `notes`, the owner fields,
the duplicate-linkage fields, the street-address blob) renders as `null` rather
than a masked-of-nothing string — matching the masked read's `null` rendering of
absent optionals in `pii_demo`.
"""

import uuid

from ..models.lead import Lead
from ..pii.masking import mask_dob, mask_email, mask_generic, mask_phone
from ..pii.service import decrypt_field

__all__ = ["build_masked_lead"]


async def build_masked_lead(
    tenant_id: uuid.UUID,
    lead: Lead,
    demo_session_id: uuid.UUID | None = None,
) -> dict:
    """Build the masked response body for one lead — the single read shape.

    The one builder every read path (list / queue and detail) returns leads
    through, so the masked-by-default contract lives in exactly one place. The
    non-sensitive columns are returned as-is; `email` and `phone` are decrypted
    in-process with `decrypt_field` and then masked, so only the masked display
    string ever leaves.

    Date of birth is deliberately **not** decrypted here: `mask_dob` is the
    constant `****-**-**` and the plaintext `age_band` is shown in its place.
    Street address is judged the same way — `mask_generic()` (`***`) when its
    encrypted blob is present, `null` when absent — with no decryption. Every
    other absent optional (`preferred_contact_method`, `notes`, the owner fields,
    the duplicate-linkage fields) renders as `null`.

    The blind indexes, `correlation_id`, and the raw `demo_session_id` are internal
    trace / matching columns and are intentionally never included. In their place the
    read surface carries two derived booleans — `is_seed` and `is_session_record` —
    computed from the caller's `demo_session_id`, gated exactly like the Epic 5 write
    guard so both are `False` for a session-less caller (the raw session id never
    leaves the server).
    """
    masked_email = mask_email(await decrypt_field(tenant_id, lead.email_encrypted))
    masked_phone = mask_phone(await decrypt_field(tenant_id, lead.phone_encrypted))

    # Date of birth and street address are judged from blob presence with no
    # decryption: dob is the constant masked date, and the street address is the
    # generic `***` token when its blob is present and `null` when it is absent.
    masked_date_of_birth = mask_dob("")
    masked_street_address = (
        mask_generic() if lead.street_address_encrypted is not None else None
    )

    # The two derived session markers, gated exactly like the Epic 5 write guard: both
    # are `False` unless the caller is in a live demo session. A session-less caller
    # (no demo cookie ⇒ `demo_session_id is None`) sees neither marker, so the non-demo
    # read surface is unchanged. The raw `lead.demo_session_id` is never returned.
    is_seed = demo_session_id is not None and lead.demo_session_id is None
    is_session_record = (
        demo_session_id is not None and lead.demo_session_id == demo_session_id
    )

    return {
        "id": lead.id,
        "first_name": lead.first_name,
        "last_name": lead.last_name,
        "email": masked_email,
        "phone": masked_phone,
        "date_of_birth": masked_date_of_birth,
        "age_band": lead.age_band,
        "zip_code": lead.zip_code,
        "street_address": masked_street_address,
        "product_lines_of_interest": lead.product_lines_of_interest,
        "preferred_contact_method": lead.preferred_contact_method,
        "notes": lead.notes,
        "rejection_reason": lead.rejection_reason,
        "lead_source": lead.lead_source,
        "status": lead.status,
        "owner_user_id": lead.owner_user_id,
        "owner_username": lead.owner_username,
        "duplicate_of_lead_id": lead.duplicate_of_lead_id,
        "duplicate_resolution": lead.duplicate_resolution,
        "created_at": lead.created_at,
        "updated_at": lead.updated_at,
        "is_seed": is_seed,
        "is_session_record": is_session_record,
    }
