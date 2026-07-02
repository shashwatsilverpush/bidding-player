"""FastAPI application: router wiring, CORS, health."""

from __future__ import annotations

import logging

from app.routers import (
    admin_demand,
    admin_publishers,
    auth,
    collector,
    config,
    stats,
)
from app.settings import get_settings
from fastapi import FastAPI, Request, Response

settings = get_settings()
logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("control_plane")

app = FastAPI(
    title="Bidding Player — Control Plane",
    version="0.1.0",
    description=(
        "Stores publishers/demand, serves runtime config by placement id, and ingests "
        "player telemetry. Phases 0–1."
    ),
)


def _is_public(path: str) -> bool:
    return path == "/e" or path.startswith("/v1/config")


def _is_admin(path: str) -> bool:
    return path.startswith("/v1/admin") or path.startswith("/auth")


@app.middleware("http")
async def cors(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Per-route CORS: public routes allow any origin; admin routes are restricted
    to the configured allowlist. A single global middleware can't express both, so
    we set headers by path here."""
    origin = request.headers.get("origin")
    path = request.url.path

    # Preflight
    if request.method == "OPTIONS":
        resp = Response(status_code=204)
    else:
        resp = await call_next(request)

    if _is_public(path):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers.setdefault("Vary", "Origin")
    elif _is_admin(path) and origin is not None:
        allowed = settings.admin_cors_list
        if "*" in allowed:
            resp.headers["Access-Control-Allow-Origin"] = "*"
        elif origin in allowed:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            resp.headers.setdefault("Vary", "Origin")
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, PUT, DELETE, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"

    return resp


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(admin_publishers.router)
app.include_router(admin_demand.router)
app.include_router(stats.router)
app.include_router(config.router)
app.include_router(collector.router)
