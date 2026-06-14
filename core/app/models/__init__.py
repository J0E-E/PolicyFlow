"""The domain models for the shared `platform` schema.

Importing this package imports all the model modules, which registers their
tables on `Base.metadata`. That is what lets `app.models` be a single import that
populates the metadata for Alembic's autogenerate and for the no-Docker tests.
The models are also re-exported here for convenient direct import.
"""

from .audit_record import AuditRecord, PlatformAuditRecord
from .auth_session import AuthSession
from .pii_demo import PiiDemoRecord
from .tenant import Tenant
from .tenant_data_key import TenantDataKey
from .tenant_settings import TenantSettings
from .user import Role, User

__all__ = [
    "AuditRecord",
    "AuthSession",
    "PiiDemoRecord",
    "PlatformAuditRecord",
    "Role",
    "Tenant",
    "TenantDataKey",
    "TenantSettings",
    "User",
]
