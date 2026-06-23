"""Core FastAPI application entry point.

Creates the FastAPI app and mounts the health, auth, tenant, platform, pii-demo,
audit, demo, agent-leads, and public-leads routers. uvicorn serves this `app`
object inside the container (see core/Dockerfile).

The app carries a **composed lifespan stack** (`app_lifespan`): on a real boot it
enters the event-bus lifespan (`event_bus_lifespan` — the polling relay + stub
consumers) and the demo-lifecycle lifespan (`demo_lifecycle_lifespan` — the
background purge scheduler), and exits both on shutdown. The lifespans are the
production runtime path only — the in-process test client's ASGITransport does not
fire lifespan events, so tests drive the relay/consumers/scheduler explicitly. Any
future startup/shutdown task adds another `async with` to this stack rather than
replacing the `FastAPI(lifespan=...)` arg.
"""

import contextlib

from fastapi import FastAPI

from .audit.router import router as audit_router
from .auth.router import router as auth_router
from .demo.router import router as demo_router
from .demo.runtime import demo_lifecycle_lifespan
from .events.runtime import event_bus_lifespan
from .health import router as health_router
from .leads.public_router import router as public_leads_router
from .leads.router import router as leads_router
from .pii_demo.router import router as pii_demo_router
from .platform.router import router as platform_router
from .tenant.router import router as tenant_router


@contextlib.asynccontextmanager
async def app_lifespan(app: FastAPI):
    """The composed lifespan stack — enter every startup/shutdown task in turn.

    Enters `event_bus_lifespan` (the relay + consumers) and `demo_lifecycle_lifespan`
    (the purge scheduler) via one `AsyncExitStack`, so both run for the app's lifetime
    and unwind cleanly on shutdown in reverse order. A new lifecycle task is one more
    `enter_async_context` here, not a replacement of the `FastAPI(lifespan=...)` arg.
    """
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(event_bus_lifespan(app))
        await stack.enter_async_context(demo_lifecycle_lifespan(app))
        yield


app = FastAPI(title="PolicyFlow Core", lifespan=app_lifespan)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(tenant_router)
app.include_router(platform_router)
app.include_router(pii_demo_router)
app.include_router(audit_router)
app.include_router(demo_router)
app.include_router(leads_router)
app.include_router(public_leads_router)
