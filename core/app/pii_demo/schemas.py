"""The request schema for the `pii_demo` demonstrator router.

Just the create request body. Responses are plain ``dict``s built by the router's
masked-response builder — the same style every existing router (auth, tenant)
uses — rather than Pydantic response models, so there is exactly one place that
decides what a masked record looks like.

`display_name`, `email`, and `date_of_birth` are required; `phone` and
`mock_medicare_id` are optional and default to ``None`` (an absent optional field
renders as ``null`` on read, never a masked-of-nothing string). `age_band` is
never accepted from the client — it is always derived from the required
`date_of_birth` on write — so it has no field here.
"""

from datetime import date

from pydantic import BaseModel, model_validator


class CreateRecordRequest(BaseModel):
    """The create request body for a `pii_demo` record.

    Mirrors `LoginRequest` in `auth/router.py`: a flat Pydantic model FastAPI
    validates before the handler runs. `email` and `date_of_birth` are required
    alongside `display_name`; `phone` and `mock_medicare_id` are optional. A
    malformed `date_of_birth` (not an ISO date) is rejected by Pydantic as a 422
    before any encryption happens.
    """

    display_name: str
    email: str
    date_of_birth: date
    phone: str | None = None
    mock_medicare_id: str | None = None


class LookupRequest(BaseModel):
    """The blind-index lookup request body: exactly one of `email` or `phone`.

    The lookup endpoint matches records by the blind-index fingerprint of a
    single field, so the request carries exactly one search term. Both fields are
    optional on their own, but the `model_validator` below requires that exactly
    one is supplied — neither (an empty body) and both (an ambiguous request) are
    each rejected by Pydantic as a 422 before the handler runs, the same
    automatic-validation style the create request relies on.
    """

    email: str | None = None
    phone: str | None = None

    @model_validator(mode="after")
    def require_exactly_one_field(self) -> "LookupRequest":
        """Reject the request unless exactly one of `email` / `phone` is given.

        Counts how many of the two search terms are present. Zero (nothing to look
        up) and two (an ambiguous request) both raise a `ValueError`, which
        FastAPI surfaces as a 422 — so a caller must always supply one and only
        one field.
        """
        supplied_field_count = sum(
            field_value is not None for field_value in (self.email, self.phone)
        )
        if supplied_field_count != 1:
            raise ValueError("supply exactly one of 'email' or 'phone'")
        return self


class RevealRequest(BaseModel):
    """The reveal request body: which one field to unmask for this record.

    A flat Pydantic model carrying a single `field` name (the request says which
    field to reveal; the record is identified by the `{record_id}` path segment).
    `field` is deliberately a plain `str`, **not** a `Literal`/enum: the handler
    must distinguish the Medicare-specific 422 ("field is never revealable") from
    the generic 422 ("field is not revealable"), and a schema-level enum would
    collapse both refusals into one indistinguishable validation 422. (Same
    reasoning recorded for `LookupRequest` — the validation that needs a
    field-specific message stays in the handler, not the schema.)
    """

    field: str
