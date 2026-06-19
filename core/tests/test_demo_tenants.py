"""Unit tests for the demo router's public tenant list (`GET /api/tenants`).

Pure unit tests — no DB, no Docker — matching the no-Docker style of
`test_router.py`. The real `demo_router` is mounted on a throwaway FastAPI app +
`TestClient`. There are **no** dependency overrides: the route has no `get_db`
dependency and no auth dependency, so the bare client exercises it exactly as
production would.

The cases prove the endpoint's contract: it returns 200 and the exact body —
both registry tenants, in registry order (Sunshine, then Florida), each with its
slug, display name, and Guide brand color; it succeeds with **no `pf_session`
cookie** (it is public); the response carries exactly the four whitelisted keys
per tenant and nothing else (no ids, emails, schema names, db roles, or any
person-level field — no PII); and it works with **no DB wiring at all**, proving
it never reads the database.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.demo.router import router as demo_router

# The exact body `GET /api/tenants` must return: both registry tenants in
# registry order (Sunshine, then Florida), each carrying its slug, display name,
# the Guide §2.3 brand primary, and its product-line catalog (each `{key, label}`
# in registry order).
EXPECTED_TENANTS_BODY = {
    "tenants": [
        {
            "slug": "sunshine-senior-benefits",
            "display_name": "Sunshine Senior Benefits",
            "brand_primary_color": "#9C4A1E",
            "product_lines": [
                {"key": "medicare_advantage", "label": "Medicare Advantage"},
                {"key": "medicare_supplement", "label": "Medicare Supplement"},
                {"key": "final_expense", "label": "Final Expense"},
                {"key": "dental_vision_hearing", "label": "Dental, Vision & Hearing"},
            ],
        },
        {
            "slug": "florida-family-planning",
            "display_name": "Florida Family Planning",
            "brand_primary_color": "#0F6A72",
            "product_lines": [
                {"key": "term_life", "label": "Term Life Insurance"},
                {"key": "whole_life", "label": "Whole Life Insurance"},
                {"key": "health", "label": "Health Insurance"},
                {"key": "critical_illness", "label": "Critical Illness"},
            ],
        },
    ]
}

# The only keys any tenant entry may carry — the public whitelist. Anything else
# (ids, emails, schema names, db roles, person-level fields) would be a leak.
ALLOWED_TENANT_KEYS = {
    "slug",
    "display_name",
    "brand_primary_color",
    "product_lines",
}

# The only keys any product-line entry may carry — the public whitelist for the
# nested `{key, label}` shape.
ALLOWED_PRODUCT_LINE_KEYS = {"key", "label"}


def build_app() -> FastAPI:
    """A throwaway app mounting the real demo router with no DB or auth wiring.

    There are deliberately no dependency overrides — the route depends on neither
    `get_db` nor any auth dependency, so a bare app is the whole production wiring.
    """
    app = FastAPI()
    app.include_router(demo_router)
    return app


# --- happy path ------------------------------------------------------------


def test_list_tenants_returns_exact_body_in_registry_order():
    """`GET /api/tenants` → 200 and the exact body, Sunshine then Florida."""
    client = TestClient(build_app())

    response = client.get("/api/tenants")

    assert response.status_code == 200
    assert response.json() == EXPECTED_TENANTS_BODY


# --- acceptance guarantees (public, no PII, no DB read) --------------------


def test_list_tenants_is_public_with_no_session_cookie():
    """The request succeeds with no `pf_session` cookie — the endpoint is public."""
    client = TestClient(build_app())
    # No cookie is ever set on this client.
    assert "pf_session" not in client.cookies

    response = client.get("/api/tenants")

    assert response.status_code == 200
    assert response.json() == EXPECTED_TENANTS_BODY


def test_list_tenants_exposes_only_the_whitelisted_keys_and_no_pii():
    """Each tenant entry carries exactly the four public keys and nothing else.

    No ids, emails, schema names, db roles, or any person-level field — the
    response is PII-free.
    """
    client = TestClient(build_app())

    response = client.get("/api/tenants")

    assert response.status_code == 200
    tenants = response.json()["tenants"]
    assert tenants  # non-empty, so the key check below is meaningful
    for tenant in tenants:
        assert set(tenant.keys()) == ALLOWED_TENANT_KEYS


def test_list_tenants_product_lines_carry_only_key_and_label():
    """Each tenant's `product_lines` is a non-empty list of `{key, label}` entries.

    The nested shape is whitelisted just like the tenant entry: a product-line
    entry carries exactly `key` and `label` and nothing else.
    """
    client = TestClient(build_app())

    response = client.get("/api/tenants")

    assert response.status_code == 200
    tenants = response.json()["tenants"]
    assert tenants  # non-empty, so the checks below are meaningful
    for tenant in tenants:
        product_lines = tenant["product_lines"]
        assert product_lines  # every tenant offers at least one line
        for product_line in product_lines:
            assert set(product_line.keys()) == ALLOWED_PRODUCT_LINE_KEYS


def test_list_tenants_works_with_no_database_wiring():
    """The route is correct on a bare client with no DB available — no DB read.

    `build_app()` overrides nothing and provides no `get_db`. A route that read
    the database would fail wiring up its session against the unreachable engine;
    this one returns the full body, proving it never depends on `get_db`.
    """
    client = TestClient(build_app())

    response = client.get("/api/tenants")

    assert response.status_code == 200
    assert response.json() == EXPECTED_TENANTS_BODY
