"""Pure shape guard for the two audit ORM models (no DB / no Docker / no async).

`alembic check` (the migration-hygiene drift proof) verifies
`PlatformAuditRecord` against migration `0007`, but it deliberately **cannot** see
the schema-less `AuditRecord` — that default-schema copy is excluded from the
drift comparison by `core/alembic/env.py` `include_object`. So nothing in the
drift check stops the two models from silently diverging. This fast, pure test is
the **only** guard on the schema-less model's shape: it pins each model's
table/schema binding, asserts the two classes expose column-for-column identical
shapes, and checks both against an independent transcription of the migration's
ten columns.

The expected column contract below is hand-transcribed from
`core/alembic/versions/0007_audit_records.py` (the same independent-transcription
idiom `test_audit_records.py` uses), so each assertion is a genuine cross-check
against the migration rather than a tautology over the models under test.
"""

import sqlalchemy as sa

from app.models.audit_record import AuditRecord, PlatformAuditRecord

# Independent transcription of the ten `0007_audit_records.py` columns:
# column name -> (SQLAlchemy type class, is_nullable, is_primary_key). Hand-built
# here on purpose, separate from the models, so it is a real spec cross-check.
EXPECTED_COLUMNS: dict[str, tuple[type, bool, bool]] = {
    "id": (sa.Uuid, False, True),
    "occurred_at": (sa.TIMESTAMP, False, False),
    "tenant_id": (sa.Uuid, True, False),
    "actor_user_id": (sa.Uuid, True, False),
    "actor_role": (sa.Text, True, False),
    "event_type": (sa.Text, False, False),
    "entity_type": (sa.Text, True, False),
    "entity_id": (sa.Uuid, True, False),
    "field_names": (sa.ARRAY, True, False),
    "outcome": (sa.Text, False, False),
}

EXPECTED_PRIMARY_KEY_CONSTRAINT_NAME = "pk_audit_records"


def test_platform_audit_record_is_bound_to_the_platform_schema():
    """`PlatformAuditRecord` maps `audit_records` in the `platform` schema."""
    assert PlatformAuditRecord.__table__.name == "audit_records"
    assert PlatformAuditRecord.__table__.schema == "platform"


def test_audit_record_is_schema_less():
    """`AuditRecord` maps `audit_records` with no schema (resolved via search_path)."""
    assert AuditRecord.__table__.name == "audit_records"
    assert AuditRecord.__table__.schema is None


def test_both_models_expose_the_same_column_names():
    """The two classes carry an identical set of column names."""
    platform_columns = set(PlatformAuditRecord.__table__.columns.keys())
    tenant_columns = set(AuditRecord.__table__.columns.keys())
    assert platform_columns == tenant_columns


def test_both_models_agree_column_for_column():
    """Per shared column the two classes agree on type, nullability, and PK flag."""
    for column_name in PlatformAuditRecord.__table__.columns.keys():
        platform_column = PlatformAuditRecord.__table__.columns[column_name]
        tenant_column = AuditRecord.__table__.columns[column_name]
        assert type(platform_column.type) is type(tenant_column.type), column_name
        assert platform_column.nullable == tenant_column.nullable, column_name
        assert platform_column.primary_key == tenant_column.primary_key, column_name


def test_models_match_the_migration_column_contract():
    """Both models carry exactly the migration's ten columns, each as specified."""
    for model in (PlatformAuditRecord, AuditRecord):
        columns = model.__table__.columns
        assert set(columns.keys()) == set(EXPECTED_COLUMNS), model.__name__

        for column_name, expected in EXPECTED_COLUMNS.items():
            expected_type, expected_nullable, expected_primary_key = expected
            column = columns[column_name]
            assert isinstance(column.type, expected_type), (
                model.__name__,
                column_name,
            )
            assert column.nullable == expected_nullable, (
                model.__name__,
                column_name,
            )
            assert column.primary_key == expected_primary_key, (
                model.__name__,
                column_name,
            )


def test_primary_key_is_id_named_pk_audit_records():
    """Both models' single-column PK is `id`, constraint named `pk_audit_records`."""
    for model in (PlatformAuditRecord, AuditRecord):
        primary_key = model.__table__.primary_key
        assert [column.name for column in primary_key.columns] == ["id"], (
            model.__name__
        )
        assert primary_key.name == EXPECTED_PRIMARY_KEY_CONSTRAINT_NAME, (
            model.__name__
        )


def test_id_default_is_app_side_uuid4():
    """`id` is generated app-side via `default=uuid.uuid4` (no DB-side default).

    The callable is matched by name rather than identity: Python 3.12 swaps in a
    C-accelerated `uuid.uuid4` after import, so `is uuid.uuid4` is unreliable.
    """
    for model in (PlatformAuditRecord, AuditRecord):
        id_column = model.__table__.columns["id"]
        assert id_column.default is not None, model.__name__
        assert callable(id_column.default.arg), model.__name__
        assert id_column.default.arg.__name__ == "uuid4", model.__name__
        assert id_column.server_default is None, model.__name__
