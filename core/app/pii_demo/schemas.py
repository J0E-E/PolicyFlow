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

from pydantic import BaseModel


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
