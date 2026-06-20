"""The request schemas for the two lead intake routers.

Just the create request bodies. Responses are plain ``dict``s built by the masked
read builder (`app.leads.masking.build_masked_lead`) — the same style every
existing router uses — rather than Pydantic response models, so there is exactly
one place that decides what a masked lead looks like.

Two separate request models, one per route, deliberately **not** unified:

- `CreateLeadRequest` — the authenticated **agent** route's body. It stays
  lenient: a flat model carrying only structural typing plus the ≥1 product-line
  rule. The agent is a trusted, logged-in caller, so it needs no length caps or
  format hardening — its substrate already gates who may post.
- `PublicIntakeRequest` — the unauthenticated **public** route's body (Epic 10).
  It is the strict twin: every field carries a length cap and the formatted fields
  (email, phone, zip, date of birth, contact method) are format-validated, because
  this body arrives from anyone on the internet. A separate model keeps that
  hardening off the agent route — they can never drift onto each other.

Both mirror `pii_demo`'s `CreateRecordRequest` shape (a flat Pydantic model FastAPI
validates before the handler runs, `date_of_birth` typed as `date`), extended to
the lead's field set. The seven required fields are `first_name`, `last_name`,
`email`, `phone`, `date_of_birth`, `zip_code`, and `product_lines_of_interest`;
the three optional fields are `street_address`, `preferred_contact_method`, and
`notes`. `age_band` is never accepted from the client on either model — it is
always derived server-side from the required `date_of_birth` on write — so it has
no field here.

Neither schema checks product-line **key membership** (that each submitted key is
one the caller's tenant offers): that needs the per-request tenant context, so it
lives in each router. Both validators surface every failure as an HTTP 422 before
the handler runs — the automatic-validation style the `pii_demo` create relies on.
"""

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from ..pii.crypto import normalize_phone

__all__ = [
    "CreateLeadRequest",
    "PublicIntakeRequest",
    "RejectLeadRequest",
    "ResolveDuplicateRequest",
]

# The light email shape the public route accepts: one or more non-`@`, non-space
# characters, an `@`, the same again, a dot, and a final run. Deliberately loose —
# it rejects the obviously-malformed (no `@`, spaces) without pulling in the
# `email-validator` dependency that Pydantic's `EmailStr` would require.
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# A US ZIP code: five digits, optionally followed by a `-` and the ZIP+4 four.
_ZIP_PATTERN = re.compile(r"^\d{5}(-\d{4})?$")

# The earliest date of birth the public route accepts. A lower bound paired with
# the strictly-past upper bound brackets the date to a plausible human lifespan
# without imposing an age floor.
_EARLIEST_DATE_OF_BIRTH = date(1900, 1, 1)

# The contact methods the public route accepts when one is supplied.
_ALLOWED_CONTACT_METHODS = {"email", "phone", "text"}


class CreateLeadRequest(BaseModel):
    """The create request body for a lead.

    Mirrors `CreateRecordRequest` in `pii_demo/schemas.py`: a flat Pydantic model
    FastAPI validates before the handler runs. The seven required fields carry no
    default; the three optional fields default to ``None`` (an absent optional
    renders as ``null`` on read, never a masked-of-nothing string). A malformed
    `date_of_birth` (not an ISO date) is rejected by Pydantic as a 422 before any
    encryption happens.
    """

    first_name: str
    last_name: str
    email: str
    phone: str
    date_of_birth: date
    zip_code: str
    product_lines_of_interest: list[str]
    street_address: str | None = None
    preferred_contact_method: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def require_at_least_one_product_line(self) -> "CreateLeadRequest":
        """Reject the request unless at least one product line is selected.

        A lead must express interest in at least one product line, so an empty
        `product_lines_of_interest` list raises a `ValueError`, which FastAPI
        surfaces as a 422 before the handler runs — the same automatic-validation
        style the `pii_demo` create request relies on. Whether each supplied key
        is one the caller's tenant actually offers is checked in the router (it
        needs the per-request tenant context), not here.
        """
        if len(self.product_lines_of_interest) < 1:
            raise ValueError("supply at least one product line of interest")
        return self


class PublicIntakeRequest(BaseModel):
    """The strict create request body for the unauthenticated public intake route.

    The hardened twin of `CreateLeadRequest`. It arrives from anyone on the
    internet, so every field carries a length cap (`Field(max_length=…)`) and the
    formatted fields are format-validated — all surfaced by FastAPI as a 422 before
    the handler runs, the same automatic-validation style the agent route relies on.
    The caps and formats are the public route's hardening; they are deliberately
    **not** on `CreateLeadRequest`, which stays lenient for its trusted agent caller.

    Beyond the agent body's field set it adds `website`, the **honeypot**: a hidden
    form field a human never fills but a bot scraping the form often does. It is not
    format-validated (any string is tolerated) — the route only checks it for
    non-emptiness and, when filled, drops the submission with a success-shaped
    response. `age_band` is still never accepted (it is derived server-side).

    The per-tenant product-line **key membership** check is not here (it needs the
    request's tenant context); the route re-checks it, exactly as the agent route does.
    """

    tenant_slug: str = Field(max_length=64)
    website: str | None = Field(default=None, max_length=200)
    first_name: str = Field(max_length=100)
    last_name: str = Field(max_length=100)
    email: str = Field(max_length=254)
    phone: str = Field(max_length=32)
    date_of_birth: date
    zip_code: str = Field(max_length=10)
    product_lines_of_interest: list[str]
    street_address: str | None = Field(default=None, max_length=200)
    preferred_contact_method: str | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("email")
    @classmethod
    def email_looks_well_formed(cls, value: str) -> str:
        """Reject an email that does not match the light `local@domain.tld` shape.

        A loose check — one or more non-`@`, non-space characters, an `@`, the same
        again, a dot, and a final run — that catches the obviously-malformed (no
        `@`, embedded spaces) without the `email-validator` dependency Pydantic's
        `EmailStr` would pull in. Raises a `ValueError` (→ 422) on a non-match.
        """
        if _EMAIL_PATTERN.match(value) is None:
            raise ValueError("email is not well-formed")
        return value

    @field_validator("phone")
    @classmethod
    def phone_has_enough_digits(cls, value: str) -> str:
        """Reject a phone whose digit-only fold is not 10–15 digits long.

        Folds the value to ASCII digits with the same `normalize_phone` the create
        core fingerprints on (so the validator and the stored fingerprint agree on
        what "the digits" are), then requires 10–15 of them — the plausible range
        for a national-to-international number. Raises a `ValueError` (→ 422) otherwise.
        """
        digit_count = len(normalize_phone(value))
        if not (10 <= digit_count <= 15):
            raise ValueError("phone must contain 10 to 15 digits")
        return value

    @field_validator("zip_code")
    @classmethod
    def zip_code_is_us_shaped(cls, value: str) -> str:
        """Reject a zip code that is not five digits or ZIP+4.

        Matches `^\\d{5}(-\\d{4})?$`: five digits, optionally a `-` and four more.
        Raises a `ValueError` (→ 422) on any other shape.
        """
        if _ZIP_PATTERN.match(value) is None:
            raise ValueError("zip code must be 5 digits or ZIP+4")
        return value

    @field_validator("date_of_birth")
    @classmethod
    def date_of_birth_is_a_plausible_past_date(cls, value: date) -> date:
        """Reject a date of birth that is not strictly in the past or is pre-1900.

        It must be strictly before today (a birth date is always in the past — no
        age floor beyond that) and on or after 1900-01-01 (the lower bracket on a
        plausible human lifespan). Raises a `ValueError` (→ 422) outside that range.
        """
        if value >= date.today():
            raise ValueError("date of birth must be in the past")
        if value < _EARLIEST_DATE_OF_BIRTH:
            raise ValueError("date of birth must be on or after 1900-01-01")
        return value

    @field_validator("preferred_contact_method")
    @classmethod
    def contact_method_is_known(cls, value: str | None) -> str | None:
        """Reject a supplied contact method outside {email, phone, text}.

        An absent (`None`) method is fine — the field is optional. When one is
        supplied it must be one of the three the system honors; any other value
        raises a `ValueError` (→ 422).
        """
        if value is not None and value not in _ALLOWED_CONTACT_METHODS:
            raise ValueError(
                "preferred contact method must be one of: email, phone, text"
            )
        return value

    @model_validator(mode="after")
    def product_line_count_within_bounds(self) -> "PublicIntakeRequest":
        """Reject the request unless 1–10 product lines are selected.

        A public lead must express interest in at least one product line and at most
        ten (an upper bound the agent route does not impose — abuse hardening for the
        public surface). Whether each supplied key is one the named tenant actually
        offers is checked in the route, not here, since it needs the tenant context.
        """
        if not (1 <= len(self.product_lines_of_interest) <= 10):
            raise ValueError("supply between 1 and 10 product lines of interest")
        return self


class RejectLeadRequest(BaseModel):
    """The request body for the reject action (`POST /api/leads/{id}/reject`).

    A single optional field: the free-text `reason` an agent may supply when
    rejecting a `Working` lead. It is **optional** — a reason-less reject is allowed
    (the `reason_kind = "qualify_reject"` on the `lead.rejected` event always
    categorizes the rejection) — and capped at 1000 characters, surfaced by FastAPI
    as a 422 before the handler runs. The reason is stored on the lead's
    `rejection_reason` column and shown in the masked read, but never carried on the
    event.
    """

    reason: str | None = Field(default=None, max_length=1000)


class ResolveDuplicateRequest(BaseModel):
    """The request body for the resolve-duplicate action.

    A single required field, `action`, naming how the agent resolves a lead the
    matcher flagged as a possible duplicate (`POST /api/leads/{id}/resolve-duplicate`):

    - `"link"` — confirm it is the same person: keep the `duplicate_of_lead_id`
      linkage and mark it `linked`.
    - `"new"` — it is genuinely a different person: clear the flag.
    - `"reject"` — discard it as a duplicate: move the `New` lead to `Rejected`.

    `action` is typed as a `Literal` of exactly those three strings, so any other
    value (a typo, an unknown action) is rejected by FastAPI as a 422 before the
    handler runs — the same automatic-validation style the other lead bodies rely on.
    """

    action: Literal["link", "new", "reject"]
