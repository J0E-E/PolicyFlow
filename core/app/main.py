"""Core FastAPI application entry point.

Creates the FastAPI app and mounts the health, auth, tenant, platform, pii-demo,
audit, and demo routers. uvicorn serves this `app` object inside the container
(see core/Dockerfile).

The app also carries the event-bus **lifespan** (`event_bus_lifespan`): on a real
boot it starts the polling relay and the stub consumers, and stops them on shutdown.
The lifespan is the production runtime path only — the in-process test client's
ASGITransport does not fire lifespan events, so tests drive the relay/consumers
explicitly.
"""

from fastapi import FastAPI

from .audit.router import router as audit_router
from .auth.router import router as auth_router
from .demo.router import router as demo_router
from .events.runtime import event_bus_lifespan
from .health import router as health_router
from .pii_demo.router import router as pii_demo_router
from .platform.router import router as platform_router
from .tenant.router import router as tenant_router

app = FastAPI(title="PolicyFlow Core", lifespan=event_bus_lifespan)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(tenant_router)
app.include_router(platform_router)
app.include_router(pii_demo_router)
app.include_router(audit_router)
app.include_router(demo_router)
