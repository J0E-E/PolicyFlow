"""Unit test for the four P2.1 conversion ORM twins.

Pure metadata introspection — no DB / no Docker / no async. Asserts that
``Household`` / ``Contact`` / ``Opportunity`` / ``Task`` are registered on
``Base.metadata``, are **schema-less** (resolved via ``search_path`` like ``Lead``,
not bound to a schema), and carry the columns the Epic-1 migration ``0015`` created
with the same nullability. The expected shapes are hand-transcribed from TDD §5.2,
so this is a genuine cross-check against the spec rather than a tautology over the
models — the lock-step partner of the substrate test
``test_lead_conversion_migration.py``.
"""

from app.db import Base
from app.models import Contact, Household, Opportunity, Task

# Per model: table name -> the columns it must declare, column name -> is-nullable.
# Hand-transcribed from TDD §5.2 / migration 0015's DDL.
EXPECTED_MODELS = {
    Household: (
        "households",
        {
            "id": False,
            "name": False,
            "correlation_id": False,
            "demo_session_id": True,
            "created_at": False,
            "updated_at": False,
        },
    ),
    Contact: (
        "contacts",
        {
            "id": False,
            "household_id": False,
            "first_name": False,
            "last_name": False,
            "zip_code": False,
            "age_band": False,
            "email_encrypted": False,
            "phone_encrypted": False,
            "date_of_birth_encrypted": False,
            "street_address_encrypted": True,
            "lead_source": False,
            "owner_user_id": True,
            "owner_username": True,
            "source_lead_id": False,
            "correlation_id": False,
            "demo_session_id": True,
            "created_at": False,
            "updated_at": False,
        },
    ),
    Opportunity: (
        "opportunities",
        {
            "id": False,
            "contact_id": False,
            "household_id": False,
            "product_line": False,
            "stage": False,
            "owner_user_id": True,
            "owner_username": True,
            "estimated_annual_premium": True,
            "target_close_date": True,
            "origin": False,
            "source_lead_id": False,
            "correlation_id": False,
            "demo_session_id": True,
            "created_at": False,
            "updated_at": False,
        },
    ),
    Task: (
        "tasks",
        {
            "id": False,
            "related_entity_type": False,
            "related_entity_id": False,
            "task_type": False,
            "body": False,
            "assignee_user_id": True,
            "assignee_username": True,
            "due_date": True,
            "status": True,
            "correlation_id": False,
            "demo_session_id": True,
            "created_at": False,
            "updated_at": False,
        },
    ),
}


def test_conversion_models_are_registered_and_schema_less():
    """Each twin is on `Base.metadata` under its table name, bound to no schema."""
    for model, (table_name, _expected_columns) in EXPECTED_MODELS.items():
        assert model.__tablename__ == table_name
        # Schema-less like `Lead` / `PiiDemoRecord`: resolved via `search_path`,
        # so the migration (not the model) owns the per-tenant physical tables.
        assert model.__table__.schema is None
        assert table_name in Base.metadata.tables


def test_conversion_models_have_the_expected_columns_and_nullability():
    """Each twin declares exactly the migration-0015 columns with matching nullability."""
    for model, (table_name, expected_columns) in EXPECTED_MODELS.items():
        actual_columns = {
            column.name: column.nullable for column in model.__table__.columns
        }
        assert actual_columns == expected_columns, table_name


def test_conversion_models_use_an_app_side_uuid_primary_key():
    """Each twin's `id` is the single PK with an app-side `uuid.uuid4` default."""
    for model in EXPECTED_MODELS:
        primary_key_columns = list(model.__table__.primary_key.columns)
        assert [column.name for column in primary_key_columns] == ["id"]
        assert model.__table__.c.id.default is not None
