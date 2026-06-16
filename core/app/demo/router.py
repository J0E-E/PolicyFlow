"""The demo HTTP surface: the public, pre-login tenant list.

This is the one authoritative source the pre-login tenant-selection screen asks
"which tenants exist, what are they called, and what is each one's brand color?"
It answers straight from the registry — the in-code list of tenants — so it
touches **no database** and exposes **no personal data**.

Endpoints under `/api`:

- `GET /tenants` returns the canonical tenant list (`slug`, `display_name`,
  `brand_primary_color`) in registry order (Sunshine, then Florida). It is
  **public**: it has no auth dependency and no `get_db` dependency, since it runs
  before anyone signs in and reads only the in-memory registry.

The body uses the `{"tenants": [...]}` envelope, mirroring the tenant router's
`{"tenant": {...}}` / `{"settings": {...}}` style. The router carries the `/api`
prefix (not `/api/demo`) so Epic 2 can add `POST /demo/assume-persona` to the same
router — the two demo endpoints live at different sub-paths under `/api`.
"""

from fastapi import APIRouter

from ..tenancy.registry import TENANTS

router = APIRouter(prefix="/api")


@router.get("/tenants")
async def list_tenants() -> dict:
    """Return the public tenant list straight from the registry.

    Loops the registry's `TENANTS` tuple — so the order is Sunshine, then
    Florida — and returns exactly the three public fields per tenant under the
    `{"tenants": [...]}` envelope. Nothing here reads the database or exposes any
    person-level data: the registry is pure in-memory configuration, so the
    response carries only each tenant's `slug`, `display_name`, and
    `brand_primary_color`.
    """
    return {
        "tenants": [
            {
                "slug": tenant.slug,
                "display_name": tenant.display_name,
                "brand_primary_color": tenant.brand_primary_color,
            }
            for tenant in TENANTS
        ]
    }
