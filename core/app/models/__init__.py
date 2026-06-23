"""The domain models for the shared `platform` schema.

Importing this package imports all the model modules, which registers their
tables on `Base.metadata`. That is what lets `app.models` be a single import that
populates the metadata for Alembic's autogenerate and for the no-Docker tests.
The models are also re-exported here for convenient direct import.
"""

from .audit_record import AuditRecord, PlatformAuditRecord
from .auth_session import AuthSession
from .demo_session import DemoSession
from .demo_session_tenant_seed import DemoSessionTenantSeed
from .lead import Lead
from .outbox_event import OutboxEvent
from .pii_demo import PiiDemoRecord
from .processed_event import ProcessedEvent
from .tenant import Tenant
from .tenant_data_key import TenantDataKey
from .tenant_settings import TenantSettings
from .user import Role, User

__all__ = [
    "AuditRecord",
    "AuthSession",
    "DemoSession",
    "DemoSessionTenantSeed",
    "Lead",
    "OutboxEvent",
    "PiiDemoRecord",
    "PlatformAuditRecord",
    "ProcessedEvent",
    "Role",
    "Tenant",
    "TenantDataKey",
    "TenantSettings",
    "User",
]
