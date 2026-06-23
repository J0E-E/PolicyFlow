"""Per-session seed instantiation: a visitor's private, claimable New queue.

A tenant-scoped persona's first `assume-persona` for a tenant instantiates that
**visit**'s own New queue from the canonical `SESSION_LEAD_TEMPLATES` (3 fillers +
the Jordan Rivera dup-bait) as **session-tagged** rows (`demo_session_id` set), so
concurrent visitors each work an isolated, genuinely-claimable queue without ever
touching the shared `NULL` seed baseline (P1.8 Epic 7).

`ensure_session_leads` is the one entry point. Its idempotency is the **ledger**
(`platform.demo_session_tenant_seed`), not a per-lead blind-index skip: the boot
seed's `email_blind_index` "already present" skip must **not** be used here,
because different visits legitimately share the dup-bait email, so a blind-index
skip would wrongly suppress the second visitor's copy. Instead, a ledger row for
`(demo_session_id, tenant_slug)` means "already instantiated" → no-op; its absence
means "seed now, then write the marker." A second visit (a fresh `demo_session_id`)
has no ledger row and so seeds its own copy even though the bait email repeats.

It emits **no** `lead.created` events — these are seed templates, not visitor
submissions, exactly like the boot seed. Encryption, blind indexing, and the
derived `age_band` go through the same `encrypt_field` / `compute_blind_index` /
`age_band_for` path the boot seed and the create endpoint use, so a session-tagged
dup-bait flags through `find_duplicate_lead` the same way the shared bait did.

The inserts (and the ledger write) run inside one tenant-scoped transaction opened
by `get_public_tenant_db`: the tenant role can write its own `leads` rows and —
since the `0012` migration — read/write the ledger, all in the shared `platform`
schema. The owning tenant's `tenant_id` (needed by the encrypt path) is read from
`platform.tenants` on the login-role session **before** scoping, because the
per-tenant role set by `get_public_tenant_db` cannot see the `platform` schema's
`tenants` table — the same ordering the public-intake route uses.
"""

import logging
import uuid
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.tenant import Tenant
from ..pii.crypto import normalize_email, normalize_phone
from ..pii.masking import age_band_for
from ..pii.service import compute_blind_index, encrypt_field
from ..seed import SESSION_LEAD_TEMPLATES
from ..leads.state import LeadSource, LeadStatus
from ..tenancy.registry import TenantConfig
from ..tenancy.scoping import get_public_tenant_db

logger = logging.getLogger(__name__)


async def _ledger_row_exists(
    db: AsyncSession, demo_session_id: uuid.UUID, tenant_slug: str
) -> bool:
    """Return whether a ledger row already marks this `(visit, tenant)` as seeded.

    The single idempotency guard: a present row means `ensure_session_leads` has
    already instantiated this visit's queue in this tenant, so the caller skips the
    inserts. Read under the scoped tenant role, which the `0012` grant lets read the
    `platform.demo_session_tenant_seed` ledger.
    """
    found = (
        await db.execute(
            text(
                "SELECT 1 FROM platform.demo_session_tenant_seed "
                "WHERE demo_session_id = :demo_session_id "
                "AND tenant_slug = :tenant_slug LIMIT 1"
            ),
            {"demo_session_id": demo_session_id, "tenant_slug": tenant_slug},
        )
    ).first()
    return found is not None


async def _insert_session_lead(
    db: AsyncSession,
    schema_name: str,
    tenant_id: uuid.UUID,
    template: dict,
    demo_session_id: uuid.UUID,
) -> None:
    """Insert one template as a session-tagged New-queue lead in the tenant schema.

    Mirrors the boot seed's lead insert exactly — every PII field encrypted via
    `encrypt_field`, the email/phone blind indexes computed over the normalized
    value, the plaintext `age_band` derived from the birth date, `public_form` /
    unowned / `New` / a fresh `correlation_id` — but tags the row with
    `demo_session_id` so it is the visitor's **own** record (Epic 6 reads it as
    `is_session_record=True`), never the shared `NULL` seed. The schema identifier
    comes only from the registry; every value is a bound parameter.
    """
    email_encrypted = await encrypt_field(tenant_id, template["email"])
    email_blind_index = await compute_blind_index(
        tenant_id, normalize_email(template["email"])
    )
    phone_encrypted = await encrypt_field(tenant_id, template["phone"])
    phone_blind_index = await compute_blind_index(
        tenant_id, normalize_phone(template["phone"])
    )
    date_of_birth_encrypted = await encrypt_field(
        tenant_id, template["date_of_birth"].isoformat()
    )
    age_band = age_band_for(template["date_of_birth"])

    street_address_encrypted = None
    if template["street_address"] is not None:
        street_address_encrypted = await encrypt_field(
            tenant_id, template["street_address"]
        )

    await db.execute(
        text(
            f"INSERT INTO {schema_name}.leads "
            "(id, first_name, last_name, email_encrypted, "
            "email_blind_index, phone_encrypted, phone_blind_index, "
            "date_of_birth_encrypted, age_band, zip_code, "
            "street_address_encrypted, product_lines_of_interest, "
            "preferred_contact_method, lead_source, status, "
            "correlation_id, demo_session_id) "
            "VALUES (:id, :first_name, :last_name, :email_encrypted, "
            ":email_blind_index, :phone_encrypted, :phone_blind_index, "
            ":date_of_birth_encrypted, :age_band, :zip_code, "
            ":street_address_encrypted, :product_lines_of_interest, "
            ":preferred_contact_method, :lead_source, :status, "
            ":correlation_id, :demo_session_id)"
        ),
        {
            "id": uuid.uuid4(),
            "first_name": template["first_name"],
            "last_name": template["last_name"],
            "email_encrypted": email_encrypted,
            "email_blind_index": email_blind_index,
            "phone_encrypted": phone_encrypted,
            "phone_blind_index": phone_blind_index,
            "date_of_birth_encrypted": date_of_birth_encrypted,
            "age_band": age_band,
            "zip_code": template["zip_code"],
            "street_address_encrypted": street_address_encrypted,
            "product_lines_of_interest": template["product_lines_of_interest"],
            "preferred_contact_method": template["preferred_contact_method"],
            "lead_source": LeadSource.PUBLIC_FORM.value,
            "status": LeadStatus.NEW.value,
            "correlation_id": uuid.uuid4(),
            "demo_session_id": demo_session_id,
        },
    )


async def ensure_session_leads(
    db: AsyncSession,
    tenant_config: TenantConfig,
    demo_session_id: uuid.UUID,
) -> int:
    """Instantiate this visit's private New queue in one tenant, ledger-guarded.

    If a ledger row for `(demo_session_id, tenant_config.slug)` already exists, this
    is a no-op (returns 0) — the guard is the **ledger**, not a per-lead blind-index
    skip, so a re-assume for an already-seeded visit/tenant inserts nothing and a
    second, distinct visit (a fresh `demo_session_id`) seeds its own copy even though
    the dup-bait email repeats. Otherwise it inserts every `SESSION_LEAD_TEMPLATES`
    row for the tenant as a session-tagged lead and writes the ledger marker, all in
    one tenant-scoped transaction. Emits no `lead.created` events. Returns the number
    of leads inserted (0 when the ledger already marked it seeded).

    The owning `tenant_id` is read from `platform.tenants` on the login-role `db`
    **before** scoping (the scoped tenant role cannot read that table); the read is a
    plain scalar so no ORM row survives into the scoped block, which
    `get_public_tenant_db` opens after rolling back any prior read transaction.
    """
    tenant_slug = tenant_config.slug

    tenant_id: Optional[uuid.UUID] = (
        await db.execute(
            select(Tenant.id).where(Tenant.slug == tenant_slug)
        )
    ).scalar_one_or_none()
    if tenant_id is None:
        # The demo always seeds every tenant, so an absent tenant row is a server
        # misconfiguration, not a client error — match the seed's loud-fail spirit.
        raise RuntimeError(
            f"cannot instantiate session leads: no tenant row for slug "
            f"{tenant_slug!r}"
        )

    templates = SESSION_LEAD_TEMPLATES.get(tenant_slug, [])

    async with get_public_tenant_db(tenant_slug, db) as scoped:
        # Ledger guard inside the scoped transaction: a present marker means this
        # visit's queue is already instantiated in this tenant — no-op.
        if await _ledger_row_exists(scoped, demo_session_id, tenant_slug):
            return 0

        for template in templates:
            await _insert_session_lead(
                scoped,
                tenant_config.schema_name,
                tenant_id,
                template,
                demo_session_id,
            )

        # Write the marker last, in the same transaction as the inserts, so the
        # ledger row and the leads land (or roll back) together — the transactional
        # idempotency invariant.
        await scoped.execute(
            text(
                "INSERT INTO platform.demo_session_tenant_seed "
                "(demo_session_id, tenant_slug) "
                "VALUES (:demo_session_id, :tenant_slug)"
            ),
            {"demo_session_id": demo_session_id, "tenant_slug": tenant_slug},
        )

    logger.info(
        "session leads instantiated: demo_session_id=%s tenant=%s leads=%d",
        demo_session_id,
        tenant_slug,
        len(templates),
    )
    return len(templates)
