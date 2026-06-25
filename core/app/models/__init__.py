"""The domain models for the shared `platform` schema.

Importing this package imports all the model modules, which registers their
tables on `Base.metadata`. That is what lets `app.models` be a single import that
populates the metadata for Alembic's autogenerate and for the no-Docker tests.
The models are also re-exported here for convenient direct import.
"""

from .audit_record import AuditRecord, PlatformAuditRecord
from .auth_session import AuthSession
from .contact import Contact
from .demo_session import DemoSession
from .demo_session_tenant_seed import DemoSessionTenantSeed
from .household import Household
from .lead import Lead
from .opportunity import Opportunity
from .outbox_event import OutboxEvent
from .pii_demo import PiiDemoRecord
from .processed_event import ProcessedEvent
from .task import Task
from .tenant import Tenant
from .tenant_data_key import TenantDataKey
from .tenant_settings import TenantSettings
from .user import Role, User

__all__ = [
    "AuditRecord",
    "AuthSession",
    "Contact",
    "DemoSession",
    "DemoSessionTenantSeed",
    "Household",
    "Lead",
    "Opportunity",
    "OutboxEvent",
    "PiiDemoRecord",
    "PlatformAuditRecord",
    "ProcessedEvent",
    "Task",
    "Tenant",
    "TenantDataKey",
    "TenantSettings",
    "User",
]
