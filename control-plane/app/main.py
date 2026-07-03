"""FastAPI application: router wiring, CORS, static admin UI, health."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, RedirectResponse

from app.routers import (
    admin_demand,
    admin_publishers,
    analytics,
    auth,
    collector,
    config,
    stats,
    tags,
)
from app.settings import get_settings

settings = get_settings()
logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("control_plane")

_STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="Bidding Player — Control Plane",
    version="0.1.0",
    description=(
        "Stores publishers/demand, serves runtime config by placement id, ingests "
        "player telemetry, generates embed tags, and reports analytics."
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


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    """Send humans to the admin dashboard."""
    return RedirectResponse(url="/admin")


@app.get("/admin", include_in_schema=False)
async def admin_ui() -> FileResponse:
    return FileResponse(_STATIC_DIR / "admin.html")


@app.get("/preview", include_in_schema=False)
async def preview_ui() -> FileResponse:
    """Self-contained tag preview + auction inspector (open with ?p=<placement_id>)."""
    return FileResponse(_STATIC_DIR / "preview.html")


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(admin_publishers.router)
app.include_router(admin_demand.router)
app.include_router(tags.router)
app.include_router(analytics.router)
app.include_router(stats.router)
app.include_router(config.router)
app.include_router(collector.router)
