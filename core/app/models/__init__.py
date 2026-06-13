"""The domain models for the shared `platform` schema.

Importing this package imports all the model modules, which registers their
tables on `Base.metadata`. That is what lets `app.models` be a single import that
populates the metadata for Alembic's autogenerate and for the no-Docker tests.
The models are also re-exported here for convenient direct import.
"""

from .auth_session import AuthSession
from .tenant import Tenant
from .tenant_data_key import TenantDataKey
from .tenant_settings import TenantSettings
from .user import Role, User

__all__ = [
    "AuthSession",
    "Role",
    "Tenant",
    "TenantDataKey",
    "TenantSettings",
    "User",
]
