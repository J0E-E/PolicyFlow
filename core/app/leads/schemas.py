"""The request schema for the lead intake routers.

Just the create request body. Responses are plain ``dict``s built by the masked
read builder (`app.leads.masking.build_masked_lead`) — the same style every
existing router uses — rather than Pydantic response models, so there is exactly
one place that decides what a masked lead looks like.

Mirrors `pii_demo`'s `CreateRecordRequest` shape (a flat Pydantic model FastAPI
validates before the handler runs, `date_of_birth` typed as `date`), extended to
the lead's field set. The seven required fields are `first_name`, `last_name`,
`email`, `phone`, `date_of_birth`, `zip_code`, and `product_lines_of_interest`;
the three optional fields are `street_address`, `preferred_contact_method`, and
`notes`. `age_band` is never accepted from the client — it is always derived
server-side from the required `date_of_birth` on write — so it has no field here.

This schema's only validation beyond structural typing is the ≥1 product-line
rule (a lead must express interest in at least one product line). The
key-membership check — that each submitted key is one the caller's tenant offers
— is **not** here: it needs the per-request tenant context, so it lives in the
router. Length caps / abuse controls are deliberately **not** here either — those
are the public-route's hardening (Epic 10), not this walking-skeleton's.
"""

from datetime import date

from pydantic import BaseModel, model_validator

__all__ = ["CreateLeadRequest"]


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
