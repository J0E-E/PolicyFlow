"""Core FastAPI application entry point.

Creates the FastAPI app and mounts the health, auth, tenant, and platform
routers. uvicorn serves this `app` object inside the container (see
core/Dockerfile).
"""

from fastapi import FastAPI

from .auth.router import router as auth_router
from .health import router as health_router
from .platform.router import router as platform_router
from .tenant.router import router as tenant_router

app = FastAPI(title="PolicyFlow Core")
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(tenant_router)
app.include_router(platform_router)
