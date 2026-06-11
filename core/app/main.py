"""Core FastAPI application entry point.

Creates the FastAPI app and mounts the health router. uvicorn serves this
`app` object inside the container (see core/Dockerfile).
"""

from fastapi import FastAPI

from .health import router as health_router

app = FastAPI(title="PolicyFlow Core")
app.include_router(health_router)
