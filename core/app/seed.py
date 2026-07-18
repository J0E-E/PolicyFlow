"""Idempotent seed for the core service: two demo tenants and nine demo users.

The container entrypoint runs ``migrate -> seed -> serve`` on every boot, so this
module is where the demo data appears. It seeds the full RBAC role matrix so a
fresh boot is immediately signable-in: two demo tenants and nine demo users (per
tenant two Agents, one Tenant Admin, one Read-Only; plus one global tenantless
Platform Admin).

Seeding is **idempotent** — re-running on every reboot inserts only what is
absent (keyed by tenant ``slug`` and user ``username``), never duplicating or
erroring. Each persona logs in with their email: ``username`` and ``email`` hold
the same email-style string, and every persona shares the password from
``settings.seed_user_password``.

The module stays runnable as ``python -m app.seed`` via the thin sync ``run()``
entrypoint the container relies on.
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .auth.passwords import hash_password
from .config import settings
from .db import session_factory
from .events.catalog import (
    ENRICHMENT_STUB,
    SCHEMA_VERSION,
    EventType,
    consumers_for_event_type,
)
from .events.enrichment import enrichment_result_summary
from .leads.state import LeadSource, LeadStatus
from .models import Role, Tenant, TenantDataKey, User
from .pii.crypto import normalize_email, normalize_phone, wrap_key
from .pii.masking import age_band_for
from .pii.service import compute_blind_index, encrypt_field
from .policies.service import policy_number
from .tenancy.registry import FLORIDA, SUNSHINE, TENANTS, tenant_by_slug

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# A tenant's root key is 32 random bytes; HKDF later derives the encryption and
# blind-index subkeys from it (see app/pii/keys.py).
ROOT_KEY_LENGTH_BYTES = 32


# --- The persona spec (pure data, no DB) -------------------------------------
#
# These module-level structures describe the demo data declaratively so the
# matrix can be unit-tested without touching a database.

# (slug, display name) for each demo tenant, derived from the tenant registry so
# the seed and the registry can never disagree about which tenants exist.
DEMO_TENANTS: tuple[tuple[str, str], ...] = tuple(
    (config.slug, config.display_name) for config in TENANTS
)

# The local part (before the @) and role of every per-tenant persona.
TENANT_USER_TEMPLATES: tuple[tuple[str, Role], ...] = (
    ("agent.one", Role.AGENT),
    ("agent.two", Role.AGENT),
    ("admin", Role.TENANT_ADMIN),
    ("readonly", Role.READ_ONLY),
)

# The single tenantless platform administrator (tenant_id stays None).
PLATFORM_ADMIN_EMAIL = "platform.admin@policyflow.example"

# The demo presentation settings for each tenant, keyed by slug. These are
# presentation content (logo, welcome message), so they live here in the seed
# rather than in the tenant registry, which is reserved for isolation config the
# migration imports. The brand colour is the one exception: it lives only in the
# registry (`TenantConfig.brand_primary_color`, the single source of truth) and
# the seed derives each tenant's `tenant_settings` colour from there, so
# `/api/tenants` and the seeded rows can never diverge. The seed writes one row
# per tenant into that tenant's own `tenant_settings` table. The logo URL is a
# distinct per-tenant placeholder built from the registry schema name.
DEMO_TENANT_SETTINGS: dict[str, dict[str, str]] = {
    "sunshine-senior-benefits": {
        "welcome_message": (
            "Welcome to Sunshine Senior Benefits — Medicare coverage made "
            "simple."
        ),
    },
    "florida-family-planning": {
        "welcome_message": (
            "Welcome to Florida Family Planning — coverage for every stage of "
            "your family's life."
        ),
    },
}


# The synthetic demo PII records seeded into each tenant's own `pii_demo` table,
# keyed by tenant slug. All values are fabricated (not real people). The personas
# are chosen to exercise both ends of the masked write/read demonstrator:
#
# - Sunshine Senior Benefits gets a 65+ persona **with** a mock Medicare id (and a
#   phone), so a row carries every field treatment, including the never-revealable
#   Medicare id, and lands in the `65+` age band.
# - Florida Family Planning gets younger personas **without** a Medicare id, one
#   with a phone and one without, so an absent optional field is exercised too.
#
# `age_band` is not stored here — it is always derived from `date_of_birth` at
# seed time, exactly as the create endpoint derives it. The birth dates are far
# enough from any plausible run date that the bands stay stable over time.
DEMO_PII_RECORDS: dict[str, list[dict]] = {
    "sunshine-senior-benefits": [
        {
            "display_name": "Margaret Sunshine",
            "email": "margaret.sunshine@example.com",
            "date_of_birth": date(1950, 4, 12),
            "phone": "+1 (305) 555-0142",
            "mock_medicare_id": "555-12-7788",
        },
        {
            "display_name": "Harold Brightwater",
            "email": "harold.brightwater@example.com",
            "date_of_birth": date(1948, 11, 3),
            "phone": "+1 (561) 555-0199",
            "mock_medicare_id": "555-34-9911",
        },
    ],
    "florida-family-planning": [
        {
            "display_name": "Ana Marisol",
            "email": "ana.marisol@example.com",
            "date_of_birth": date(1994, 7, 22),
            "phone": "+1 (786) 555-0123",
            "mock_medicare_id": None,
        },
        {
            "display_name": "Diego Familia",
            "email": "diego.familia@example.com",
            "date_of_birth": date(1989, 2, 9),
            "phone": None,
            "mock_medicare_id": None,
        },
    ],
}


# The per-session New-queue lead templates, keyed by tenant slug. These are the
# canonical set `app.demo.instantiation.ensure_session_leads` stamps into a
# visitor's **own** private queue (session-tagged) on first `assume-persona` — they
# are **not** seeded by the boot seed (P1.8 Epic 7 split them out of the shared
# `NULL` baseline so concurrent visitors each work their own claimable queue without
# touching shared seed; the shared-historical read-only set is Epic 8's). Every row
# is a **queue lead**: `public_form` source, unowned (`owner_user_id` null), born
# `New` — exactly the shape the unassigned queue filter surfaces.
#
# Each tenant gets 3 ordinary filler leads + 1 duplicate-bait (8 templates total).
# The fillers are clearly synthetic — `example.com` emails, `555-01xx` phones —
# with distinct, all-decimal phones and distinct emails (the matcher-collision
# gotcha: low-entropy contact details in the shared container DB flag unrelated
# leads), a spread of dates of birth across age bands, and a mix of present/absent
# `street_address`. Product-line keys are validated against the tenant's registry
# set (Epic 4) — Sunshine's Medicare/expense lines, Florida's life/health lines.
#
# The **duplicate-bait** is the *same identity* in both tenants (Jordan Rivera,
# same email + phone), so the "Try a duplicate scenario" prefill is one payload
# that flags in whichever tenant the shopper submits to. Its normalized email +
# phone are the cross-epic contract that prefill must submit (the frontend's
# `shopperIntakePrefills.ts` mirrors these constants verbatim). Only its product
# line differs per tenant (each tenant's first registry key). The bait is now
# **session-tagged** per visit (not the shared `NULL` bait), so a visitor's "Try a
# duplicate" flags against seed ∪ their own rows only (Epic 5's matcher scoping).
#
# `age_band` is never stored here — it is derived from `date_of_birth` at
# instantiation time, exactly as the create path derives it. The birth dates are
# far enough from any plausible run date that the bands stay stable over time.
JORDAN_RIVERA_BAIT_EMAIL = "jordan.rivera@example.com"
JORDAN_RIVERA_BAIT_PHONE = "(407) 555-0188"

SESSION_LEAD_TEMPLATES: dict[str, list[dict]] = {
    "sunshine-senior-benefits": [
        {
            "first_name": "Eleanor",
            "last_name": "Whitfield",
            "email": "eleanor.whitfield@example.com",
            "phone": "(305) 555-0142",
            "date_of_birth": date(1947, 9, 4),
            "zip_code": "33139",
            "street_address": "1820 Collins Avenue",
            "preferred_contact_method": "phone",
            "product_lines_of_interest": ["medicare_advantage"],
        },
        {
            "first_name": "Marcus",
            "last_name": "Delgado",
            "email": "marcus.delgado@example.com",
            "phone": "(561) 555-0173",
            "date_of_birth": date(1955, 1, 27),
            "zip_code": "33401",
            "street_address": None,
            "preferred_contact_method": "email",
            "product_lines_of_interest": ["medicare_supplement", "final_expense"],
        },
        {
            # Priya is intentionally **under 65** (planning ahead before she ages in)
            # **and** inquiring about a Medicare line, so converting her yields a
            # Medicare-gated, under-65 opportunity the agent can demonstrate the
            # *Quoted* block on (walkthrough step 8) — no ad-hoc data entry needed
            # (P2.2 Epic 9, Risk R1). Her DOB sits comfortably under 65 so the scripted
            # block stays reliable for years.
            "first_name": "Priya",
            "last_name": "Nakamura",
            "email": "priya.nakamura@example.com",
            "phone": "(786) 555-0156",
            "date_of_birth": date(1965, 6, 11),
            "zip_code": "33156",
            "street_address": "640 Sunset Drive",
            "preferred_contact_method": "email",
            "product_lines_of_interest": ["medicare_advantage"],
        },
        {
            "first_name": "Jordan",
            "last_name": "Rivera",
            "email": JORDAN_RIVERA_BAIT_EMAIL,
            "phone": JORDAN_RIVERA_BAIT_PHONE,
            "date_of_birth": date(1958, 6, 15),
            "zip_code": "32801",
            "street_address": "742 Marina Bay Drive",
            "preferred_contact_method": "email",
            "product_lines_of_interest": ["medicare_advantage"],
        },
        {
            # The decline-thread fixture (P2.3 R3 / C4): a session-queue lead whose
            # email contains `deny`, so once the agent converts it and submits its
            # application the deterministic carrier decision DECLINES (the value is
            # never surfaced — TDD §5.6). Contacts have no email-edit path, so the
            # `deny` email must originate on a seeded lead. `final_expense` is
            # non-Medicare-gated, so the round-trip to a quote is unblocked — the
            # decline walkthrough (step 12) and the Epic 14 decline acceptance thread
            # ride this lead. Analogous to Priya, the under-65 Medicare seed-nudge.
            "first_name": "Darnell",
            "last_name": "Updike",
            "email": "darnell.deny@example.com",
            "phone": "(305) 555-0244",
            "date_of_birth": date(1950, 3, 12),
            "zip_code": "33139",
            "street_address": "77 Decline Court",
            "preferred_contact_method": "email",
            "product_lines_of_interest": ["final_expense"],
        },
    ],
    "florida-family-planning": [
        {
            "first_name": "Tomas",
            "last_name": "Esperanza",
            "email": "tomas.esperanza@example.com",
            "phone": "(813) 555-0119",
            "date_of_birth": date(1996, 3, 30),
            "zip_code": "33602",
            "street_address": "210 Channelside Drive",
            "preferred_contact_method": "text",
            "product_lines_of_interest": ["term_life"],
        },
        {
            "first_name": "Sofia",
            "last_name": "Almeida",
            "email": "sofia.almeida@example.com",
            "phone": "(904) 555-0134",
            "date_of_birth": date(1983, 12, 5),
            "zip_code": "32202",
            "street_address": None,
            "preferred_contact_method": "phone",
            "product_lines_of_interest": ["whole_life", "critical_illness"],
        },
        {
            "first_name": "Devin",
            "last_name": "Okonkwo",
            "email": "devin.okonkwo@example.com",
            "phone": "(727) 555-0167",
            "date_of_birth": date(1971, 8, 19),
            "zip_code": "33701",
            "street_address": "95 Beach Drive Northeast",
            "preferred_contact_method": "email",
            "product_lines_of_interest": ["health"],
        },
        {
            "first_name": "Jordan",
            "last_name": "Rivera",
            "email": JORDAN_RIVERA_BAIT_EMAIL,
            "phone": JORDAN_RIVERA_BAIT_PHONE,
            "date_of_birth": date(1958, 6, 15),
            "zip_code": "32801",
            "street_address": "742 Marina Bay Drive",
            "preferred_contact_method": "email",
            "product_lines_of_interest": ["term_life"],
        },
        {
            # The decline-thread fixture (P2.3 R3 / C4), mirroring Sunshine's Darnell:
            # a session-queue lead whose email contains `deny`, so submitting its
            # application takes the deterministic carrier-decline path. `term_life` is
            # non-Medicare-gated, so the round-trip to a quote is unblocked.
            "first_name": "Bianca",
            "last_name": "Denholm",
            "email": "bianca.deny@example.com",
            "phone": "(813) 555-0188",
            "date_of_birth": date(1980, 7, 22),
            "zip_code": "33602",
            "street_address": "300 Harbour Island Boulevard",
            "preferred_contact_method": "email",
            "product_lines_of_interest": ["term_life"],
        },
    ],
}


# The shared read-only historical lead set, keyed by tenant slug. These are the
# worked/historical leads the boot seed stamps into each tenant's `leads` table as
# the shared `NULL` baseline (`demo_session_id IS NULL`), so lists and dashboards
# render non-trivially from seed alone — context every visitor sees, none can claim
# (P1.8 Epic 8). They are the complement of `SESSION_LEAD_TEMPLATES`: that set is
# the per-visit *claimable* New queue; this set is the shared *read-only* history.
#
# 6 rows per tenant — **2 Working / 2 Qualified / 2 Rejected** — all **owned**, split
# 3/3 across `agent.one` and `agent.two` (`owner_local_part`, resolved to the seeded
# user's id + email at seed time). There are deliberately **no unowned / `New` rows**:
# an unowned `New` row would surface in the Unassigned-queue tab looking claimable
# while the Epic 5 write guard silently `409`s a live-session caller acting on it, so
# every historical row is owned and past `New`. Each **Rejected** row is a
# `Working → Rejected` outcome and carries a `rejection_reason` (the reject path's
# free-text), so it reads as a real worked-then-declined lead. `lead_source` is
# `agent_entered` — these are agent-worked records, not fresh public submissions.
#
# `created_at_offset_days` backdates each row relative to boot (computed at seed time,
# so the rows stay recent — spread over the last few weeks): they sort **below**
# today's fresh session queue and read as history. Emails are distinct and clearly
# synthetic (`example.com`); phones are distinct and **all-decimal** (the matcher-
# collision gotcha: low-entropy contact details in the shared container DB flag
# unrelated leads). Product-line keys come from each tenant's registry set (Sunshine's
# Medicare/expense lines, Florida's life/health lines); dates of birth spread across
# the age bands; `street_address` mixes present/absent.
#
# `age_band` is never stored here — it is derived from `date_of_birth` at seed time,
# exactly as the create path derives it. The birth dates are far enough from any
# plausible run date that the bands stay stable over time.
SHARED_HISTORICAL_LEADS: dict[str, list[dict]] = {
    "sunshine-senior-benefits": [
        {
            "first_name": "Gloria",
            "last_name": "Hampton",
            "email": "gloria.hampton@example.com",
            "phone": "(305) 555-0201",
            "date_of_birth": date(1951, 2, 18),
            "zip_code": "33139",
            "street_address": "1450 Ocean Drive",
            "preferred_contact_method": "phone",
            "product_lines_of_interest": ["medicare_advantage"],
            "status": LeadStatus.WORKING,
            "owner_local_part": "agent.one",
            "rejection_reason": None,
            "created_at_offset_days": 4,
        },
        {
            "first_name": "Walter",
            "last_name": "Brennan",
            "email": "walter.brennan@example.com",
            "phone": "(561) 555-0212",
            "date_of_birth": date(1956, 10, 7),
            "zip_code": "33401",
            "street_address": None,
            "preferred_contact_method": "email",
            "product_lines_of_interest": ["medicare_supplement"],
            "status": LeadStatus.WORKING,
            "owner_local_part": "agent.two",
            "rejection_reason": None,
            "created_at_offset_days": 9,
        },
        {
            "first_name": "Estelle",
            "last_name": "Marchetti",
            "email": "estelle.marchetti@example.com",
            "phone": "(786) 555-0223",
            "date_of_birth": date(1948, 6, 25),
            "zip_code": "33156",
            "street_address": "980 Brickell Avenue",
            "preferred_contact_method": "phone",
            "product_lines_of_interest": ["final_expense"],
            "status": LeadStatus.QUALIFIED,
            "owner_local_part": "agent.one",
            "rejection_reason": None,
            "created_at_offset_days": 13,
        },
        {
            "first_name": "Raymond",
            "last_name": "Castellano",
            "email": "raymond.castellano@example.com",
            "phone": "(954) 555-0234",
            "date_of_birth": date(1953, 12, 1),
            "zip_code": "33301",
            "street_address": "60 Las Olas Boulevard",
            "preferred_contact_method": "email",
            "product_lines_of_interest": ["dental_vision_hearing", "medicare_advantage"],
            "status": LeadStatus.QUALIFIED,
            "owner_local_part": "agent.two",
            "rejection_reason": None,
            "created_at_offset_days": 17,
        },
        {
            "first_name": "Doris",
            "last_name": "Whitlock",
            "email": "doris.whitlock@example.com",
            "phone": "(727) 555-0245",
            "date_of_birth": date(1959, 3, 14),
            "zip_code": "33701",
            "street_address": None,
            "preferred_contact_method": "phone",
            "product_lines_of_interest": ["medicare_supplement"],
            "status": LeadStatus.REJECTED,
            "owner_local_part": "agent.one",
            "rejection_reason": "Outside service area — referred to another carrier.",
            "created_at_offset_days": 21,
        },
        {
            "first_name": "Clifford",
            "last_name": "Yamamoto",
            "email": "clifford.yamamoto@example.com",
            "phone": "(813) 555-0256",
            "date_of_birth": date(1962, 8, 30),
            "zip_code": "33602",
            "street_address": "415 Bayshore Boulevard",
            "preferred_contact_method": "email",
            "product_lines_of_interest": ["medicare_advantage"],
            "status": LeadStatus.REJECTED,
            "owner_local_part": "agent.two",
            "rejection_reason": "Not yet Medicare-eligible — follow up at 65.",
            "created_at_offset_days": 26,
        },
    ],
    "florida-family-planning": [
        {
            "first_name": "Bianca",
            "last_name": "Castro",
            "email": "bianca.castro@example.com",
            "phone": "(813) 555-0301",
            "date_of_birth": date(1990, 5, 12),
            "zip_code": "33602",
            "street_address": "300 Channelside Drive",
            "preferred_contact_method": "text",
            "product_lines_of_interest": ["term_life"],
            "status": LeadStatus.WORKING,
            "owner_local_part": "agent.one",
            "rejection_reason": None,
            "created_at_offset_days": 5,
        },
        {
            "first_name": "Andre",
            "last_name": "Solomon",
            "email": "andre.solomon@example.com",
            "phone": "(904) 555-0312",
            "date_of_birth": date(1978, 9, 3),
            "zip_code": "32202",
            "street_address": None,
            "preferred_contact_method": "email",
            "product_lines_of_interest": ["whole_life"],
            "status": LeadStatus.WORKING,
            "owner_local_part": "agent.two",
            "rejection_reason": None,
            "created_at_offset_days": 10,
        },
        {
            "first_name": "Renata",
            "last_name": "Oliveira",
            "email": "renata.oliveira@example.com",
            "phone": "(727) 555-0323",
            "date_of_birth": date(1985, 1, 28),
            "zip_code": "33701",
            "street_address": "120 Beach Drive Northeast",
            "preferred_contact_method": "phone",
            "product_lines_of_interest": ["health"],
            "status": LeadStatus.QUALIFIED,
            "owner_local_part": "agent.one",
            "rejection_reason": None,
            "created_at_offset_days": 14,
        },
        {
            "first_name": "Felix",
            "last_name": "Nordquist",
            "email": "felix.nordquist@example.com",
            "phone": "(954) 555-0334",
            "date_of_birth": date(1969, 11, 19),
            "zip_code": "33301",
            "street_address": "25 Las Olas Boulevard",
            "preferred_contact_method": "email",
            "product_lines_of_interest": ["critical_illness", "whole_life"],
            "status": LeadStatus.QUALIFIED,
            "owner_local_part": "agent.two",
            "rejection_reason": None,
            "created_at_offset_days": 18,
        },
        {
            "first_name": "Camila",
            "last_name": "Reyes",
            "email": "camila.reyes@example.com",
            "phone": "(305) 555-0345",
            "date_of_birth": date(2003, 4, 6),
            "zip_code": "33139",
            "street_address": None,
            "preferred_contact_method": "text",
            "product_lines_of_interest": ["term_life"],
            "status": LeadStatus.REJECTED,
            "owner_local_part": "agent.one",
            "rejection_reason": "Duplicate of an existing household policy.",
            "created_at_offset_days": 22,
        },
        {
            "first_name": "Hassan",
            "last_name": "Abdullah",
            "email": "hassan.abdullah@example.com",
            "phone": "(561) 555-0356",
            "date_of_birth": date(1995, 7, 24),
            "zip_code": "33401",
            "street_address": "78 Clematis Street",
            "preferred_contact_method": "phone",
            "product_lines_of_interest": ["health"],
            "status": LeadStatus.REJECTED,
            "owner_local_part": "agent.two",
            "rejection_reason": "No longer interested — declined to proceed.",
            "created_at_offset_days": 27,
        },
    ],
}


# --- Baseline money-path chains (P2.4 Epic 5) --------------------------------
#
# Whole baseline chains — lead → household → contact → opportunity → application →
# policy — seeded into BOTH tenants as shared read-only rows (`demo_session_id IS
# NULL`), so the renewal sweeps and the cross-sell prompt have real targets in a
# fresh demo session (there are otherwise no baseline money-path entities — only
# baseline leads). Money-path tables carry **no DB foreign keys** (app-enforced
# integrity), so the chain is stitched by copying ids forward, mirroring what the
# live conversion → application → policy path leaves behind.
#
# One household + one contact per tenant, with several issued policies rolling up
# to it (exactly like a real lead conversion: one contact, one household, one
# opportunity per product line). The coverage shape each household presents drives
# the cross-sell demo (Epic 13): Sunshine's Ramirez household covers three of its
# four lines (partial → a prompt for the uncovered `dental_vision_hearing`), while
# Florida's Familia household covers all four lines (full → no prompt).
#
# `agent.one` owns every chain's opportunities and policies, so each generated
# renewal-review Task lands on a deterministic assignee for the queue demo. The
# synthetic contact PII is clearly fabricated — `example.com` emails and distinct,
# all-decimal `555-01xx` phones — and never the Jordan Rivera duplicate-bait
# identity, so the boot seed's backing leads never false-flag the duplicate matcher.

# The three ways a baseline policy's `issued_at` is placed relative to the seed-run
# date (`today`), each exercising one branch of the renewal sweeps:
#   - "recent"                — issued a few weeks ago; well clear of any anniversary
#                               window (used for AEP and no-renewal lines).
#   - "anniversary_in_window" — back-dated so the next yearly anniversary is ~30 days
#                               out, i.e. mid-way inside the 60-day anniversary window
#                               → the anniversary sweep renews it (Epic 8 target).
#   - "recent_out_of_window"  — back-dated so the next anniversary is >60 days out →
#                               the anniversary sweep skips it (a full-coverage line
#                               that must NOT generate a renewal).
ISSUE_RULE_RECENT = "recent"
ISSUE_RULE_ANNIVERSARY_IN_WINDOW = "anniversary_in_window"
ISSUE_RULE_RECENT_OUT_OF_WINDOW = "recent_out_of_window"

# A "recent" policy is issued this many days before the seed-run date.
RECENT_ISSUE_OFFSET_DAYS = 30
# An "anniversary_in_window" policy's next anniversary is placed this many days out —
# comfortably inside the 60-day window and not on its very edge (mid-window).
ANNIVERSARY_IN_WINDOW_DAYS = 30
# A "recent_out_of_window" policy's next anniversary is placed this many days out —
# comfortably beyond the 60-day window so the anniversary sweep never selects it.
OUT_OF_WINDOW_ANNIVERSARY_DAYS = 120
# How many whole years back a window-derived issue date is placed, so the policy
# reads as issued a few years ago while its next anniversary lands where we want it.
BASELINE_ISSUE_YEARS_BACK = 3


def _issue_date_for_anniversary(next_anniversary_date: date) -> date:
    """Return an issue date whose next anniversary is ``next_anniversary_date``.

    Places the issue date ``BASELINE_ISSUE_YEARS_BACK`` whole years before the target
    anniversary's year, sharing its month and day, so the policy reads as issued a
    few years ago while `rules.next_anniversary` lands exactly on the target date. A
    February 29 target falling in a non-leap issue year is observed on February 28 —
    the same leap-year rule `rules.next_anniversary` applies, kept in step here so the
    computed issue date and the sweep's anniversary math never disagree.
    """
    issue_year = next_anniversary_date.year - BASELINE_ISSUE_YEARS_BACK
    try:
        return date(issue_year, next_anniversary_date.month, next_anniversary_date.day)
    except ValueError:
        return date(issue_year, 2, 28)


def baseline_issued_at(issue_rule: str, today: date) -> date:
    """Return a baseline policy's `issued_at` date for ``issue_rule`` given ``today``.

    Pure and clock-injected (``today`` is passed, never read) so the placement is
    trivially unit-testable at each boundary. "recent" sits a few weeks in the past;
    "anniversary_in_window" and "recent_out_of_window" are back-dated so the next
    yearly anniversary lands ~30 days out (inside the 60-day window) or ~120 days out
    (beyond it) respectively — matching `rules.anniversary_within` on the same date.
    Any other rule raises ``ValueError`` so a typo fails loudly rather than silently
    placing a policy today.
    """
    if issue_rule == ISSUE_RULE_RECENT:
        return today - timedelta(days=RECENT_ISSUE_OFFSET_DAYS)
    if issue_rule == ISSUE_RULE_ANNIVERSARY_IN_WINDOW:
        return _issue_date_for_anniversary(
            today + timedelta(days=ANNIVERSARY_IN_WINDOW_DAYS)
        )
    if issue_rule == ISSUE_RULE_RECENT_OUT_OF_WINDOW:
        return _issue_date_for_anniversary(
            today + timedelta(days=OUT_OF_WINDOW_ANNIVERSARY_DAYS)
        )
    raise ValueError(f"unknown baseline issue rule {issue_rule!r}")


# The baseline household spec per tenant (pure data, no DB). Each tenant seeds one
# household with one contact and several issued policies rolling up to it. `contact`
# holds the synthetic PII the backing lead and the contact both carry (the contact
# mirrors the lead, exactly as the live conversion does). Each `policies` entry names
# a tenant product-line key and the `issue_rule` that places its `issued_at`; the
# carrier / labels / premiums / coverage are read from that line's first registry
# quote template at seed time, so the seeded terms can never drift from the catalog.
BASELINE_MONEY_PATH_HOUSEHOLDS: dict[str, dict] = {
    SUNSHINE.slug: {
        "household_last_name": "Ramirez",
        "owner_local_part": "agent.one",
        "contact": {
            "first_name": "Margaret",
            "last_name": "Ramirez",
            "email": "margaret.ramirez@example.com",
            "phone": "(305) 555-0170",
            "date_of_birth": date(1949, 3, 22),
            "zip_code": "33139",
            "street_address": "88 Coral Way",
        },
        # Covered {ma, medsupp, fe}; `dental_vision_hearing` left uncovered → a
        # PARTIAL cross-sell household (Epic 13 prompts for the one open line).
        "policies": [
            {
                "product_line": "medicare_advantage",  # aep — the SOLE Sunshine MA
                "issue_rule": ISSUE_RULE_RECENT,        # policy (Epic 6 stays {1,0})
            },
            {
                "product_line": "medicare_supplement",  # anniversary — inside the
                "issue_rule": ISSUE_RULE_ANNIVERSARY_IN_WINDOW,  # 60-day window
            },
            {
                "product_line": "final_expense",  # none — generates no renewal
                "issue_rule": ISSUE_RULE_RECENT,
            },
        ],
    },
    FLORIDA.slug: {
        "household_last_name": "Familia",
        "owner_local_part": "agent.one",
        "contact": {
            "first_name": "Diego",
            "last_name": "Familia",
            "email": "diego.familia@example.com",
            "phone": "(786) 555-0171",
            "date_of_birth": date(1985, 6, 14),
            "zip_code": "33602",
            "street_address": "410 Bayshore Boulevard",
        },
        # All four Florida lines covered → a FULLY-covered household (Epic 13 prompt
        # suppressed). `health` / `critical_illness` are issued out-of-window so the
        # anniversary sweep never renews them; the life lines never renew at all.
        "policies": [
            {"product_line": "term_life", "issue_rule": ISSUE_RULE_RECENT},
            {"product_line": "whole_life", "issue_rule": ISSUE_RULE_RECENT},
            {"product_line": "health", "issue_rule": ISSUE_RULE_RECENT_OUT_OF_WINDOW},
            {
                "product_line": "critical_illness",
                "issue_rule": ISSUE_RULE_RECENT_OUT_OF_WINDOW,
            },
        ],
    },
}

# The baseline note-tasks per tenant (pure data, no DB). Plain `note` tasks hung off
# the household's contact, so the agent task queue (Epic 10/11) renders non-trivially
# from seed alone. Assignees split `agent.one` / `agent.two` in Sunshine to exercise
# the role-scoped queue; Florida seeds a single `agent.one` note.
BASELINE_NOTE_TASKS: dict[str, list[dict]] = {
    SUNSHINE.slug: [
        {
            "assignee_local_part": "agent.one",
            "body": "Follow up on Margaret's Medicare Advantage plan questions.",
        },
        {
            "assignee_local_part": "agent.two",
            "body": "Confirm the supplement premium payment method.",
        },
    ],
    FLORIDA.slug: [
        {
            "assignee_local_part": "agent.one",
            "body": "Review the Familia household's coverage after the new policy.",
        },
    ],
}


def _baseline_quote_template(tenant_slug: str, product_line_key: str):
    """Return the first registry quote template for a tenant's product line.

    The baseline policy copies its carrier / label / coverage / premiums from this
    template, so the seeded issued terms are exactly a catalog option and can never
    drift from the registry. Raises ``KeyError`` if the line has no template — a
    misconfigured spec fails loudly rather than seeding a premium-less policy.
    """
    for product_line in tenant_by_slug(tenant_slug).product_lines:
        if product_line.key == product_line_key:
            if not product_line.quote_options:
                raise KeyError(
                    f"{product_line_key} has no quote template to seed a policy from"
                )
            return product_line.quote_options[0]
    raise KeyError(f"{product_line_key} is not a {tenant_slug} product line")


def demo_tenants() -> tuple[tuple[str, str], ...]:
    """Return the (slug, display name) pairs for the demo tenants."""
    return DEMO_TENANTS


def demo_users_for(tenant_slug: str) -> tuple[tuple[str, Role, str], ...]:
    """Return the (email, role, tenant_slug) tuples for one tenant's personas.

    Username equals email, so the first element doubles as both. The email is
    built from each template's local part and the tenant's email domain, read
    from the tenant registry.
    """
    domain = tenant_by_slug(tenant_slug).email_domain
    return tuple(
        (f"{local_part}@{domain}", role, tenant_slug)
        for local_part, role in TENANT_USER_TEMPLATES
    )


def demo_user_specs() -> tuple[tuple[str, Role, Optional[str]], ...]:
    """Return a flat (email==username, role, tenant_slug | None) tuple per user.

    This is the whole nine-persona matrix: four per-tenant personas for each of
    the two tenants, then the one tenantless platform admin (tenant_slug None).
    """
    specs: list[tuple[str, Role, Optional[str]]] = []
    for tenant_slug, _display_name in DEMO_TENANTS:
        specs.extend(demo_users_for(tenant_slug))
    specs.append((PLATFORM_ADMIN_EMAIL, Role.PLATFORM_ADMIN, None))
    return tuple(specs)


# --- The idempotent async seed (insert-if-absent) ----------------------------


async def seed_tenant_data_keys(
    db: AsyncSession, tenant_ids: Iterable[uuid.UUID]
) -> int:
    """Mint one master-key-wrapped root key per tenant, insert-if-absent.

    For each tenant id that has no key row yet, generate a fresh random 32-byte
    root key, wrap it under ``settings.pii_master_key``, and add a
    ``TenantDataKey`` row. Returns the number of keys newly created.

    Insert-if-absent (never re-wrap): a tenant that already has a wrapped key is
    skipped, because the container re-seeds on every boot and overwriting the key
    would orphan all of that tenant's already-encrypted PII. The plaintext root
    key lives only in the local variable during wrapping; only the wrapped blob
    persists. Rows are added to the session here and flushed by the caller's
    single ``commit``.
    """
    tenant_ids = list(tenant_ids)
    if not tenant_ids:
        return 0

    existing_tenant_ids = set(
        (
            await db.execute(
                select(TenantDataKey.tenant_id).where(
                    TenantDataKey.tenant_id.in_(tenant_ids)
                )
            )
        )
        .scalars()
        .all()
    )

    keys_created = 0
    for tenant_id in tenant_ids:
        if tenant_id in existing_tenant_ids:
            continue
        root_key = os.urandom(ROOT_KEY_LENGTH_BYTES)
        wrapped_root_key = wrap_key(settings.pii_master_key, root_key)
        db.add(
            TenantDataKey(
                tenant_id=tenant_id,
                wrapped_root_key=wrapped_root_key,
            )
        )
        keys_created += 1
    return keys_created


async def seed_pii_demo_records(
    db: AsyncSession, slug_to_tenant_id: dict[str, uuid.UUID]
) -> int:
    """Insert the synthetic demo PII records into each tenant's `pii_demo` table.

    For each tenant, skips entirely if that tenant's `pii_demo` already holds any
    rows (count-based idempotency — the container re-seeds on every boot, and the
    records have no natural unique key to conflict on). Otherwise it encrypts each
    PII field via `encrypt_field`, computes the email (and phone) blind index over
    the normalized value via `compute_blind_index`, derives the plaintext
    `age_band` from the birth date, and `INSERT`s the row with raw SQL. Returns the
    total number of records newly inserted.

    The schema identifier is interpolated **only** from the registry (never user
    input), exactly like the `tenant_settings` seed; every value is a bound
    parameter. The per-tenant keys this resolves are read by `get_tenant_keys`
    through its **own** session, so the caller must have already committed the
    seeded `tenant_data_keys` before calling this — otherwise the key load (a
    separate session) cannot see them.
    """
    records_inserted = 0
    for tenant_slug, tenant_id in slug_to_tenant_id.items():
        config = tenant_by_slug(tenant_slug)
        existing_count = (
            await db.execute(
                text(f"SELECT COUNT(*) FROM {config.schema_name}.pii_demo")
            )
        ).scalar_one()
        if existing_count > 0:
            continue

        for demo_record in DEMO_PII_RECORDS.get(tenant_slug, []):
            email_encrypted = await encrypt_field(tenant_id, demo_record["email"])
            email_blind_index = await compute_blind_index(
                tenant_id, normalize_email(demo_record["email"])
            )
            date_of_birth_encrypted = await encrypt_field(
                tenant_id, demo_record["date_of_birth"].isoformat()
            )
            age_band = age_band_for(demo_record["date_of_birth"])

            phone_encrypted = None
            phone_blind_index = None
            if demo_record["phone"] is not None:
                phone_encrypted = await encrypt_field(
                    tenant_id, demo_record["phone"]
                )
                phone_blind_index = await compute_blind_index(
                    tenant_id, normalize_phone(demo_record["phone"])
                )

            mock_medicare_id_encrypted = None
            if demo_record["mock_medicare_id"] is not None:
                mock_medicare_id_encrypted = await encrypt_field(
                    tenant_id, demo_record["mock_medicare_id"]
                )

            await db.execute(
                text(
                    f"INSERT INTO {config.schema_name}.pii_demo "
                    "(id, display_name, email_encrypted, email_blind_index, "
                    "phone_encrypted, phone_blind_index, date_of_birth_encrypted, "
                    "age_band, mock_medicare_id_encrypted) "
                    "VALUES (:id, :display_name, :email_encrypted, "
                    ":email_blind_index, :phone_encrypted, :phone_blind_index, "
                    ":date_of_birth_encrypted, :age_band, "
                    ":mock_medicare_id_encrypted)"
                ),
                {
                    "id": uuid.uuid4(),
                    "display_name": demo_record["display_name"],
                    "email_encrypted": email_encrypted,
                    "email_blind_index": email_blind_index,
                    "phone_encrypted": phone_encrypted,
                    "phone_blind_index": phone_blind_index,
                    "date_of_birth_encrypted": date_of_birth_encrypted,
                    "age_band": age_band,
                    "mock_medicare_id_encrypted": mock_medicare_id_encrypted,
                },
            )
            records_inserted += 1
    return records_inserted


async def seed_shared_historical_leads(
    db: AsyncSession, slug_to_tenant_id: dict[str, uuid.UUID]
) -> int:
    """Insert the shared read-only historical leads into each tenant's `leads` table.

    For each tenant, skips entirely if that tenant's `leads` already holds any
    shared-baseline row (`demo_session_id IS NULL`) — count-based idempotency, the
    same shape `seed_pii_demo_records` uses, because the container re-seeds on every
    boot and these rows have no natural unique key to conflict on. Scoping the count
    to `demo_session_id IS NULL` keeps it from being defeated by a visitor's own
    session-tagged rows in the shared container (those are `NOT NULL`). Otherwise it
    resolves each row's owner (`agent.one` / `agent.two`) to a seeded user id, encrypts
    every PII field via `encrypt_field`, computes the email/phone blind indexes over the
    normalized value, derives the plaintext `age_band`, backdates `created_at` by the
    row's offset, and `INSERT`s the row as a shared (`demo_session_id IS NULL`) lead
    with its `status` / owner / `rejection_reason`. Returns the total newly inserted.

    The schema identifier is interpolated **only** from the registry (never user
    input), exactly like `seed_pii_demo_records`; every value is a bound parameter.
    The per-tenant keys this resolves are read by `get_tenant_keys` through its **own**
    session, so the caller must have already committed the seeded `tenant_data_keys`
    before calling this — the same ordering `seed_pii_demo_records` relies on.
    """
    boot_time = datetime.now(timezone.utc)
    leads_inserted = 0
    for tenant_slug, tenant_id in slug_to_tenant_id.items():
        config = tenant_by_slug(tenant_slug)
        existing_count = (
            await db.execute(
                text(
                    f"SELECT COUNT(*) FROM {config.schema_name}.leads "
                    "WHERE demo_session_id IS NULL"
                )
            )
        ).scalar_one()
        if existing_count > 0:
            continue

        # Resolve each historical row's owner (agent.one / agent.two) to the seeded
        # user's id and email-style username. The usernames are built from the
        # registry email domain, exactly as `demo_users_for` builds them, so the
        # lookup can never disagree with the seeded personas.
        owner_username_by_local_part = {
            local_part: f"{local_part}@{config.email_domain}"
            for local_part in ("agent.one", "agent.two")
        }
        owner_id_by_username = {
            username: user_id
            for user_id, username in (
                await db.execute(
                    select(User.id, User.username).where(
                        User.username.in_(owner_username_by_local_part.values())
                    )
                )
            ).all()
        }

        for historical_lead in SHARED_HISTORICAL_LEADS.get(tenant_slug, []):
            email_encrypted = await encrypt_field(
                tenant_id, historical_lead["email"]
            )
            email_blind_index = await compute_blind_index(
                tenant_id, normalize_email(historical_lead["email"])
            )
            phone_encrypted = await encrypt_field(
                tenant_id, historical_lead["phone"]
            )
            phone_blind_index = await compute_blind_index(
                tenant_id, normalize_phone(historical_lead["phone"])
            )
            date_of_birth_encrypted = await encrypt_field(
                tenant_id, historical_lead["date_of_birth"].isoformat()
            )
            age_band = age_band_for(historical_lead["date_of_birth"])

            street_address_encrypted = None
            if historical_lead["street_address"] is not None:
                street_address_encrypted = await encrypt_field(
                    tenant_id, historical_lead["street_address"]
                )

            owner_username = owner_username_by_local_part[
                historical_lead["owner_local_part"]
            ]
            owner_user_id = owner_id_by_username[owner_username]
            created_at = boot_time - timedelta(
                days=historical_lead["created_at_offset_days"]
            )

            # The lead's id and correlation_id are minted here and reused by both
            # the lead INSERT below and the synthesized event trail, so every event
            # carries the lead's own trace id — exactly as the live writers reuse
            # the row's `correlation_id` across `lead.created` and every later event.
            lead_id = uuid.uuid4()
            correlation_id = uuid.uuid4()

            await db.execute(
                text(
                    f"INSERT INTO {config.schema_name}.leads "
                    "(id, first_name, last_name, email_encrypted, "
                    "email_blind_index, phone_encrypted, phone_blind_index, "
                    "date_of_birth_encrypted, age_band, zip_code, "
                    "street_address_encrypted, product_lines_of_interest, "
                    "preferred_contact_method, rejection_reason, lead_source, "
                    "status, owner_user_id, owner_username, correlation_id, "
                    "demo_session_id, created_at, updated_at) "
                    "VALUES (:id, :first_name, :last_name, :email_encrypted, "
                    ":email_blind_index, :phone_encrypted, :phone_blind_index, "
                    ":date_of_birth_encrypted, :age_band, :zip_code, "
                    ":street_address_encrypted, :product_lines_of_interest, "
                    ":preferred_contact_method, :rejection_reason, :lead_source, "
                    ":status, :owner_user_id, :owner_username, :correlation_id, "
                    ":demo_session_id, :created_at, :created_at)"
                ),
                {
                    "id": lead_id,
                    "first_name": historical_lead["first_name"],
                    "last_name": historical_lead["last_name"],
                    "email_encrypted": email_encrypted,
                    "email_blind_index": email_blind_index,
                    "phone_encrypted": phone_encrypted,
                    "phone_blind_index": phone_blind_index,
                    "date_of_birth_encrypted": date_of_birth_encrypted,
                    "age_band": age_band,
                    "zip_code": historical_lead["zip_code"],
                    "street_address_encrypted": street_address_encrypted,
                    "product_lines_of_interest": historical_lead[
                        "product_lines_of_interest"
                    ],
                    "preferred_contact_method": historical_lead[
                        "preferred_contact_method"
                    ],
                    "rejection_reason": historical_lead["rejection_reason"],
                    "lead_source": LeadSource.AGENT_ENTERED.value,
                    "status": historical_lead["status"].value,
                    "owner_user_id": owner_user_id,
                    "owner_username": owner_username,
                    "correlation_id": correlation_id,
                    "demo_session_id": None,
                    "created_at": created_at,
                },
            )
            leads_inserted += 1

            # Synthesize this lead's status-derived event trail (P1.9 Epic 5) so a
            # baseline lead opens with a coherent, non-empty timeline that matches
            # its status — the same fan-out a live delivery would have produced.
            await _seed_lead_event_trail(
                db,
                schema_name=config.schema_name,
                tenant_id=tenant_id,
                lead_id=lead_id,
                correlation_id=correlation_id,
                status=historical_lead["status"],
                created_at=created_at,
            )
    return leads_inserted


def _synthesized_lead_events(
    status: LeadStatus, created_at: datetime
) -> list[tuple[EventType, datetime]]:
    """Return one baseline lead's status-derived `(event_type, occurred_at)` trail.

    The sequence mirrors the live lifecycle writers, oldest-first: `lead.created`
    always (at the lead's backdated `created_at`); `+ lead.assigned` at +1h because
    every baseline lead is owned (it carries an `owner_local_part`); then the
    terminal `lead.qualified` / `lead.rejected` at +2h for a Qualified / Rejected
    lead. A Working lead stops after `lead.assigned`. Because `created_at` is days
    in the past, every stamp stays comfortably before now.
    """
    events: list[tuple[EventType, datetime]] = [
        (EventType.LEAD_CREATED, created_at),
        (EventType.LEAD_ASSIGNED, created_at + timedelta(hours=1)),
    ]
    if status is LeadStatus.QUALIFIED:
        events.append((EventType.LEAD_QUALIFIED, created_at + timedelta(hours=2)))
    elif status is LeadStatus.REJECTED:
        events.append((EventType.LEAD_REJECTED, created_at + timedelta(hours=2)))
    return events


async def _seed_lead_event_trail(
    db: AsyncSession,
    *,
    schema_name: str,
    tenant_id: uuid.UUID,
    lead_id: uuid.UUID,
    correlation_id: uuid.UUID,
    status: LeadStatus,
    created_at: datetime,
) -> None:
    """Insert one baseline lead's synthesized `outbox` + `processed_events` trail.

    For each status-derived event (`_synthesized_lead_events`): one `outbox` row —
    a fresh `event_id`, the lead's own `correlation_id`, `demo_session_id NULL`,
    `published_at = occurred_at` (so the timeline read derives a *terminal*
    reaction, not pending), and a payload of `{"entity_id": <lead id>}` plus
    `"entity_type": "lead"` on `lead.created` only (mirroring the live writers; the
    timeline read filters on `entity_id` alone). Then, for each consumer the catalog
    fans the event out to (`consumers_for_event_type`, registry-ordered), one
    `processed_events` row — the row's existence *is* `done` in the read-time
    derivation, `processed_at` = the event's `occurred_at` + 1 min, and a
    `result_summary` of `enrichment_result_summary(event_id)` for `enrichment.stub`
    (reused, never re-derived, so the seeded score equals a live delivery's) or
    NULL for `sync.logger`. Both writes use the schema-qualified raw `text()` INSERT
    idiom the surrounding seed uses — not the search-path-bound ORM `enqueue_event`,
    which would leave `published_at` NULL.
    """
    for event_type, occurred_at in _synthesized_lead_events(status, created_at):
        event_id = uuid.uuid4()
        payload: dict[str, str] = {"entity_id": str(lead_id)}
        if event_type is EventType.LEAD_CREATED:
            payload["entity_type"] = "lead"

        await db.execute(
            text(
                f"INSERT INTO {schema_name}.outbox "
                "(id, event_id, event_type, schema_version, tenant_id, "
                "correlation_id, causation_id, actor_user_id, actor_role, "
                "demo_session_id, payload, occurred_at, published_at) "
                "VALUES (:id, :event_id, :event_type, :schema_version, "
                ":tenant_id, :correlation_id, NULL, NULL, NULL, NULL, "
                "CAST(:payload AS jsonb), :occurred_at, :published_at)"
            ),
            {
                "id": uuid.uuid4(),
                "event_id": event_id,
                "event_type": event_type.value,
                "schema_version": SCHEMA_VERSION,
                "tenant_id": tenant_id,
                "correlation_id": correlation_id,
                "payload": json.dumps(payload),
                "occurred_at": occurred_at,
                "published_at": occurred_at,
            },
        )

        processed_at = occurred_at + timedelta(minutes=1)
        for consumer_name in consumers_for_event_type(event_type.value):
            result_summary = (
                enrichment_result_summary(event_id)
                if consumer_name == ENRICHMENT_STUB
                else None
            )
            await db.execute(
                text(
                    f"INSERT INTO {schema_name}.processed_events "
                    "(id, consumer_name, event_id, tenant_id, event_type, "
                    "correlation_id, processed_at, result_summary) "
                    "VALUES (:id, :consumer_name, :event_id, :tenant_id, "
                    ":event_type, :correlation_id, :processed_at, "
                    ":result_summary)"
                ),
                {
                    "id": uuid.uuid4(),
                    "consumer_name": consumer_name,
                    "event_id": event_id,
                    "tenant_id": tenant_id,
                    "event_type": event_type.value,
                    "correlation_id": correlation_id,
                    "processed_at": processed_at,
                    "result_summary": result_summary,
                },
            )


async def seed_baseline_money_paths(
    db: AsyncSession, slug_to_tenant_id: dict[str, uuid.UUID]
) -> int:
    """Insert whole baseline money-path chains into each tenant, insert-if-absent.

    For each tenant, skips entirely if that tenant already holds any baseline
    (`demo_session_id IS NULL`) household — count-based idempotency keyed on a
    **money-path** entity, the same shape `seed_shared_historical_leads` uses. The key
    is deliberately the household count, **not** the NULL-leads count: the chain's
    backing leads below are also `NULL`, and `seed_shared_historical_leads` owns the
    NULL-leads gate, so keying on leads here would let the two seeds defeat each
    other's idempotency. Otherwise it builds each tenant's one household → contact →
    N (opportunity → application → policy) chain, plus a few baseline `note` tasks hung
    off the contact (so the agent task queue renders from seed), all as shared baseline
    rows, and returns the total number of policy chains newly inserted.

    Money-path tables carry **no DB foreign keys** (integrity is app-enforced), so the
    chain is stitched by copying pre-minted ids forward. The contact PII is encrypted
    via `encrypt_field` (contacts have no blind-index columns); the backing lead
    additionally carries the `email`/`phone` blind indexes its schema requires. The
    schema identifier is interpolated **only** from the registry (never user input),
    exactly like `seed_shared_historical_leads`; every value is a bound parameter. The
    per-tenant keys this resolves are read by `get_tenant_keys` through its **own**
    session, so the caller must have already committed the seeded `tenant_data_keys`
    before calling this — the same ordering the other encrypting seeds rely on.
    """
    today = datetime.now(timezone.utc).date()
    chains_inserted = 0
    for tenant_slug, tenant_id in slug_to_tenant_id.items():
        household_spec = BASELINE_MONEY_PATH_HOUSEHOLDS.get(tenant_slug)
        if household_spec is None:
            continue
        config = tenant_by_slug(tenant_slug)

        existing_households = (
            await db.execute(
                text(
                    f"SELECT COUNT(*) FROM {config.schema_name}.households "
                    "WHERE demo_session_id IS NULL"
                )
            )
        ).scalar_one()
        if existing_households > 0:
            continue

        # Resolve the owning / assignee agents to seeded user ids + email-style
        # usernames, built from the registry email domain exactly as `demo_users_for`
        # builds them, so the lookup can never disagree with the seeded personas.
        owner_username_by_local_part = {
            local_part: f"{local_part}@{config.email_domain}"
            for local_part in ("agent.one", "agent.two")
        }
        owner_id_by_username = {
            username: user_id
            for user_id, username in (
                await db.execute(
                    select(User.id, User.username).where(
                        User.username.in_(owner_username_by_local_part.values())
                    )
                )
            ).all()
        }

        owner_username = owner_username_by_local_part[
            household_spec["owner_local_part"]
        ]
        owner_user_id = owner_id_by_username[owner_username]

        contact_spec = household_spec["contact"]
        last_name = household_spec["household_last_name"]
        policy_specs = household_spec["policies"]

        # Pre-mint every id so the backing lead can carry its converted refs and the
        # whole FK-free chain can be stitched by copying ids forward.
        household_id = uuid.uuid4()
        contact_id = uuid.uuid4()
        backing_lead_id = uuid.uuid4()
        conversion_correlation_id = uuid.uuid4()
        opportunity_ids = [uuid.uuid4() for _ in policy_specs]

        # Encrypt the contact PII once — the backing lead and the contact carry the
        # same values, exactly as a live conversion re-encrypts the lead's fields onto
        # the new contact.
        email_encrypted = await encrypt_field(tenant_id, contact_spec["email"])
        phone_encrypted = await encrypt_field(tenant_id, contact_spec["phone"])
        date_of_birth_encrypted = await encrypt_field(
            tenant_id, contact_spec["date_of_birth"].isoformat()
        )
        street_address_encrypted = await encrypt_field(
            tenant_id, contact_spec["street_address"]
        )
        age_band = age_band_for(contact_spec["date_of_birth"])

        # The backing lead needs blind indexes (NOT NULL on `leads`); the contact has
        # no blind-index columns.
        email_blind_index = await compute_blind_index(
            tenant_id, normalize_email(contact_spec["email"])
        )
        phone_blind_index = await compute_blind_index(
            tenant_id, normalize_phone(contact_spec["phone"])
        )

        # --- household ---
        await db.execute(
            text(
                f"INSERT INTO {config.schema_name}.households "
                "(id, name, correlation_id, demo_session_id) "
                "VALUES (:id, :name, :correlation_id, NULL)"
            ),
            {
                "id": household_id,
                "name": f"{last_name} Household",
                "correlation_id": conversion_correlation_id,
            },
        )

        # --- backing lead (a minimal `Converted` lead the contact chains back to) ---
        await db.execute(
            text(
                f"INSERT INTO {config.schema_name}.leads "
                "(id, first_name, last_name, email_encrypted, email_blind_index, "
                "phone_encrypted, phone_blind_index, date_of_birth_encrypted, "
                "age_band, zip_code, street_address_encrypted, "
                "product_lines_of_interest, preferred_contact_method, lead_source, "
                "status, owner_user_id, owner_username, converted_contact_id, "
                "converted_opportunity_ids, correlation_id, demo_session_id) "
                "VALUES (:id, :first_name, :last_name, :email_encrypted, "
                ":email_blind_index, :phone_encrypted, :phone_blind_index, "
                ":date_of_birth_encrypted, :age_band, :zip_code, "
                ":street_address_encrypted, :product_lines_of_interest, "
                ":preferred_contact_method, :lead_source, :status, :owner_user_id, "
                ":owner_username, :converted_contact_id, :converted_opportunity_ids, "
                ":correlation_id, NULL)"
            ),
            {
                "id": backing_lead_id,
                "first_name": contact_spec["first_name"],
                "last_name": contact_spec["last_name"],
                "email_encrypted": email_encrypted,
                "email_blind_index": email_blind_index,
                "phone_encrypted": phone_encrypted,
                "phone_blind_index": phone_blind_index,
                "date_of_birth_encrypted": date_of_birth_encrypted,
                "age_band": age_band,
                "zip_code": contact_spec["zip_code"],
                "street_address_encrypted": street_address_encrypted,
                "product_lines_of_interest": [
                    policy_spec["product_line"] for policy_spec in policy_specs
                ],
                "preferred_contact_method": "email",
                "lead_source": LeadSource.AGENT_ENTERED.value,
                "status": LeadStatus.CONVERTED.value,
                "owner_user_id": owner_user_id,
                "owner_username": owner_username,
                "converted_contact_id": contact_id,
                "converted_opportunity_ids": opportunity_ids,
                "correlation_id": conversion_correlation_id,
            },
        )

        # --- contact (PII mirrors the lead; no blind-index columns) ---
        await db.execute(
            text(
                f"INSERT INTO {config.schema_name}.contacts "
                "(id, household_id, first_name, last_name, zip_code, age_band, "
                "email_encrypted, phone_encrypted, date_of_birth_encrypted, "
                "street_address_encrypted, lead_source, owner_user_id, "
                "owner_username, source_lead_id, correlation_id, demo_session_id) "
                "VALUES (:id, :household_id, :first_name, :last_name, :zip_code, "
                ":age_band, :email_encrypted, :phone_encrypted, "
                ":date_of_birth_encrypted, :street_address_encrypted, :lead_source, "
                ":owner_user_id, :owner_username, :source_lead_id, :correlation_id, "
                "NULL)"
            ),
            {
                "id": contact_id,
                "household_id": household_id,
                "first_name": contact_spec["first_name"],
                "last_name": contact_spec["last_name"],
                "zip_code": contact_spec["zip_code"],
                "age_band": age_band,
                "email_encrypted": email_encrypted,
                "phone_encrypted": phone_encrypted,
                "date_of_birth_encrypted": date_of_birth_encrypted,
                "street_address_encrypted": street_address_encrypted,
                "lead_source": LeadSource.AGENT_ENTERED.value,
                "owner_user_id": owner_user_id,
                "owner_username": owner_username,
                "source_lead_id": backing_lead_id,
                "correlation_id": conversion_correlation_id,
            },
        )

        # --- one opportunity → application → policy chain per covered line ---
        # The policy number matches `policies.service.policy_number` (prefix = the
        # first three schema-name letters, upper-cased), so a seeded policy reads the
        # same shape as a live-issued one.
        policy_prefix = config.schema_name[:3].upper()
        for opportunity_id, policy_spec in zip(opportunity_ids, policy_specs):
            product_line = policy_spec["product_line"]
            quote = _baseline_quote_template(tenant_slug, product_line)
            chain_correlation_id = uuid.uuid4()
            application_id = uuid.uuid4()
            policy_id = uuid.uuid4()
            issued_date = baseline_issued_at(policy_spec["issue_rule"], today)
            # `policies.issued_at` is a timestamptz; place the issue at UTC midnight.
            issued_at = datetime(
                issued_date.year,
                issued_date.month,
                issued_date.day,
                tzinfo=timezone.utc,
            )

            # opportunity — a `conversion` opportunity already advanced to Policy
            # Active, carrying the owner / contact / household the renewal sweep and
            # cross-sell coverage join read forward.
            await db.execute(
                text(
                    f"INSERT INTO {config.schema_name}.opportunities "
                    "(id, contact_id, household_id, product_line, stage, "
                    "owner_user_id, owner_username, estimated_annual_premium, "
                    "origin, source_lead_id, correlation_id, demo_session_id) "
                    "VALUES (:id, :contact_id, :household_id, :product_line, "
                    "'Policy Active', :owner_user_id, :owner_username, "
                    ":estimated_annual_premium, 'conversion', :source_lead_id, "
                    ":correlation_id, NULL)"
                ),
                {
                    "id": opportunity_id,
                    "contact_id": contact_id,
                    "household_id": household_id,
                    "product_line": product_line,
                    "owner_user_id": owner_user_id,
                    "owner_username": owner_username,
                    "estimated_annual_premium": quote.premium_annual,
                    "source_lead_id": backing_lead_id,
                    "correlation_id": chain_correlation_id,
                },
            )

            # application — Approved, the frozen issued terms copied from the quote.
            await db.execute(
                text(
                    f"INSERT INTO {config.schema_name}.applications "
                    "(id, opportunity_id, contact_id, product_line, "
                    "selected_quote_id, status, carrier, product_label, "
                    "coverage_amount, premium_monthly, premium_annual, decision, "
                    "decided_at, correlation_id, demo_session_id) "
                    "VALUES (:id, :opportunity_id, :contact_id, :product_line, "
                    ":selected_quote_id, 'Approved', :carrier, :product_label, "
                    ":coverage_amount, :premium_monthly, :premium_annual, "
                    "'approved', :decided_at, :correlation_id, NULL)"
                ),
                {
                    "id": application_id,
                    "opportunity_id": opportunity_id,
                    "contact_id": contact_id,
                    "product_line": product_line,
                    # No quotes/quote_requests are seeded; `selected_quote_id` is NOT
                    # NULL but FK-free, so a synthetic uuid satisfies the column.
                    "selected_quote_id": uuid.uuid4(),
                    "carrier": quote.carrier,
                    "product_label": quote.product_label,
                    "coverage_amount": quote.coverage_amount,
                    "premium_monthly": quote.premium_monthly,
                    "premium_annual": quote.premium_annual,
                    "decided_at": datetime.now(timezone.utc),
                    "correlation_id": chain_correlation_id,
                },
            )

            # policy — Active, terms copied from the application, back-dated issue.
            await db.execute(
                text(
                    f"INSERT INTO {config.schema_name}.policies "
                    "(id, opportunity_id, application_id, contact_id, "
                    "policy_number, carrier, product_label, coverage_amount, "
                    "premium_monthly, premium_annual, status, correlation_id, "
                    "demo_session_id, issued_at) "
                    "VALUES (:id, :opportunity_id, :application_id, :contact_id, "
                    ":policy_number, :carrier, :product_label, :coverage_amount, "
                    ":premium_monthly, :premium_annual, 'Active', :correlation_id, "
                    "NULL, :issued_at)"
                ),
                {
                    "id": policy_id,
                    "opportunity_id": opportunity_id,
                    "application_id": application_id,
                    "contact_id": contact_id,
                    "policy_number": policy_number(
                        policy_prefix, application_id, issued_date.year
                    ),
                    "carrier": quote.carrier,
                    "product_label": quote.product_label,
                    "coverage_amount": quote.coverage_amount,
                    "premium_monthly": quote.premium_monthly,
                    "premium_annual": quote.premium_annual,
                    "correlation_id": chain_correlation_id,
                    "issued_at": issued_at,
                },
            )
            chains_inserted += 1

        # --- baseline note-tasks hung off the household's contact ---
        # Plain `note` tasks so the agent task queue (Epic 10/11) renders from seed
        # alone. Assignees split agent.one / agent.two in Sunshine to exercise the
        # role-scoped queue; they share the conversion correlation and stay `open`.
        for note_task in BASELINE_NOTE_TASKS.get(tenant_slug, []):
            assignee_username = owner_username_by_local_part[
                note_task["assignee_local_part"]
            ]
            await db.execute(
                text(
                    f"INSERT INTO {config.schema_name}.tasks "
                    "(id, related_entity_type, related_entity_id, task_type, body, "
                    "assignee_user_id, assignee_username, status, correlation_id, "
                    "demo_session_id) "
                    "VALUES (:id, 'contact', :related_entity_id, 'note', :body, "
                    ":assignee_user_id, :assignee_username, 'open', :correlation_id, "
                    "NULL)"
                ),
                {
                    "id": uuid.uuid4(),
                    "related_entity_id": contact_id,
                    "body": note_task["body"],
                    "assignee_user_id": owner_id_by_username[assignee_username],
                    "assignee_username": assignee_username,
                    "correlation_id": conversion_correlation_id,
                },
            )
    return chains_inserted


async def seed(db: AsyncSession) -> None:
    """Insert any missing demo tenants and users, then commit once.

    Idempotent: existing tenant slugs and usernames are read first, and only the
    absent rows are added. Logs how many of each were inserted versus already
    present so the boot logs show the seed result.
    """
    # --- Tenants: read what already exists, insert what is missing. ---
    existing_tenant_slugs = set(
        (await db.execute(select(Tenant.slug))).scalars().all()
    )
    slug_to_tenant_id: dict[str, uuid.UUID] = {}
    tenants_inserted = 0
    for slug, display_name in DEMO_TENANTS:
        if slug in existing_tenant_slugs:
            continue
        tenant_id = uuid.uuid4()
        config = tenant_by_slug(slug)
        db.add(
            Tenant(
                id=tenant_id,
                slug=slug,
                name=display_name,
                schema_name=config.schema_name,
                db_role=config.db_role,
            )
        )
        slug_to_tenant_id[slug] = tenant_id
        tenants_inserted += 1

    # Load the tenants that were already present so users in those tenants can be
    # linked to the right tenant_id, and so their schema_name / db_role can be
    # backfilled from the registry. Loading full ORM objects (rather than just
    # slug + id) lets us set the columns in place; the mutations flush on the
    # single commit below. Always setting to the registry value keeps this
    # idempotent, and orphan rows never appear here because already_present_slugs
    # is built from the registry-derived DEMO_TENANTS.
    already_present_slugs = [
        slug for slug, _name in DEMO_TENANTS if slug in existing_tenant_slugs
    ]
    if already_present_slugs:
        present_tenants = (
            await db.execute(
                select(Tenant).where(Tenant.slug.in_(already_present_slugs))
            )
        ).scalars().all()
        for tenant in present_tenants:
            config = tenant_by_slug(tenant.slug)
            tenant.schema_name = config.schema_name
            tenant.db_role = config.db_role
            slug_to_tenant_id[tenant.slug] = tenant.id

    # --- Users: read existing usernames, insert the missing personas. ---
    existing_usernames = set(
        (await db.execute(select(User.username))).scalars().all()
    )
    password_hash = hash_password(settings.seed_user_password)
    users_inserted = 0
    for email, role, tenant_slug in demo_user_specs():
        if email in existing_usernames:
            continue
        tenant_id = (
            slug_to_tenant_id[tenant_slug] if tenant_slug is not None else None
        )
        db.add(
            User(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                username=email,
                email=email,
                password_hash=password_hash,
                role=role,
            )
        )
        users_inserted += 1

    # --- Tenant settings: one distinct row per tenant, in its own schema. ---
    # slug_to_tenant_id now covers both inserted and already-present tenants, so
    # each registry tenant has a known id. The schema identifier comes only from
    # the registry (never user input); the values are bound parameters. The
    # INSERT ... ON CONFLICT (tenant_id) DO NOTHING makes a re-seed idempotent.
    settings_inserted = 0
    for tenant_slug, tenant_id in slug_to_tenant_id.items():
        config = tenant_by_slug(tenant_slug)
        demo_settings = DEMO_TENANT_SETTINGS[tenant_slug]
        brand_logo_url = (
            f"https://assets.policyflow.example/{config.schema_name}/logo.svg"
        )
        # The brand colour comes from the registry (the single source of truth),
        # so the seeded row can never diverge from `/api/tenants`.
        result = await db.execute(
            text(
                f"INSERT INTO {config.schema_name}.tenant_settings "
                "(tenant_id, brand_primary_color, brand_logo_url, "
                "welcome_message) "
                "VALUES (:tenant_id, :brand_primary_color, :brand_logo_url, "
                ":welcome_message) "
                "ON CONFLICT (tenant_id) DO NOTHING"
            ),
            {
                "tenant_id": tenant_id,
                "brand_primary_color": config.brand_primary_color,
                "brand_logo_url": brand_logo_url,
                "welcome_message": demo_settings["welcome_message"],
            },
        )
        settings_inserted += result.rowcount or 0

    # --- Data keys: one master-key-wrapped root key per tenant, insert-if-
    # absent. slug_to_tenant_id covers both inserted and already-present tenants,
    # so this is the full set of registry tenant ids.
    keys_inserted = await seed_tenant_data_keys(db, slug_to_tenant_id.values())

    # Commit the tenants, users, settings, and data keys before seeding the demo
    # PII records. `seed_pii_demo_records` encrypts each field, and the per-tenant
    # key it needs is read by `get_tenant_keys` through its **own** session — which
    # cannot see the just-added `tenant_data_keys` rows until this commit lands.
    await db.commit()

    # --- Demo PII records: synthetic encrypted rows per tenant, in each tenant's
    # own `pii_demo` table. They encrypt on write and so need the data keys above
    # to be durable (the key load runs in its own session), which the commit above
    # guarantees. The boot seed seeds no per-session New-queue `leads` rows: P1.8
    # Epic 7 moved that set to per-session instantiation (`SESSION_LEAD_TEMPLATES`,
    # stamped session-tagged on `assume-persona`). It does seed the shared-historical
    # read-only `leads` set below.
    pii_demo_rows_inserted = await seed_pii_demo_records(db, slug_to_tenant_id)

    # --- Shared historical leads: the read-only `demo_session_id IS NULL` baseline
    # (worked/qualified/rejected, owned) per tenant, so lists and dashboards render
    # non-trivially from seed alone (P1.8 Epic 8). Like `seed_pii_demo_records` it
    # encrypts on write (needs the durable data keys above) and resolves each row's
    # owner to a seeded user committed above — both guaranteed by the commit above.
    historical_leads_inserted = await seed_shared_historical_leads(
        db, slug_to_tenant_id
    )

    # --- Baseline money-path chains: whole household → contact → opportunity →
    # application → policy chains per tenant (P2.4 Epic 5), so the renewal sweeps and
    # the cross-sell prompt have real targets in a fresh session. Runs AFTER the
    # shared-historical leads so that seed keeps ownership of the NULL-leads
    # idempotency gate (the chains' backing leads are also NULL); its own gate is the
    # baseline-household count. Like the seeds above it encrypts on write (needs the
    # durable data keys committed above) and resolves owners to committed users.
    money_path_chains_inserted = await seed_baseline_money_paths(
        db, slug_to_tenant_id
    )
    await db.commit()

    total_tenants = len(DEMO_TENANTS)
    total_users = len(demo_user_specs())
    logger.info(
        "seed complete: tenants inserted=%d already-present=%d; "
        "users inserted=%d already-present=%d; settings rows inserted=%d; "
        "data keys inserted=%d; pii_demo rows inserted=%d; "
        "historical leads inserted=%d; money-path chains inserted=%d",
        tenants_inserted,
        total_tenants - tenants_inserted,
        users_inserted,
        total_users - users_inserted,
        settings_inserted,
        keys_inserted,
        pii_demo_rows_inserted,
        historical_leads_inserted,
        money_path_chains_inserted,
    )


def run() -> None:
    """Open a session and drive the async seed to completion.

    The thin sync wrapper the container entrypoint calls via
    ``python -m app.seed`` after migrations and before serving traffic.
    """

    async def main() -> None:
        async with session_factory() as db:
            await seed(db)

    asyncio.run(main())


if __name__ == "__main__":
    run()
