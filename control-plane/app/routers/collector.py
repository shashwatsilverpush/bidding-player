"""Public telemetry collector. Returns 204 fast; never blocks the browser."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request, Response
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas.events import event_adapter
from app.services.ingest import ingest_event

router = APIRouter(tags=["collector"])

SessionDep = Depends(get_session)

_NO_CONTENT = Response(status_code=204)


def _client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


# Country as resolved by the CDN / edge in front of the collector. Only these
# well-known provider headers are read; a spoofed value can at worst mislabel a
# reporting dimension, never affect serving.
_EDGE_COUNTRY_HEADERS = (
    "cf-ipcountry",
    "cloudfront-viewer-country",
    "x-vercel-ip-country",
    "x-appengine-country",
    "fastly-geo-country-code",
)


def _edge_country(request: Request) -> str | None:
    for h in _EDGE_COUNTRY_HEADERS:
        v = (request.headers.get(h) or "").strip().upper()
        # XX / T1 (Tor) / ZZ are the providers' "unknown" markers.
        if len(v) == 2 and v.isalpha() and v not in ("XX", "T1", "ZZ"):
            return v
    return None


@router.post("/e")
async def collect(request: Request, session: AsyncSession = SessionDep) -> Response:
    """Accept one event. Tolerates ``text/plain`` bodies (navigator.sendBeacon).

    Always answers 204 — validation/consent/unknown-account drops are silent so the
    endpoint never leaks which accounts exist and never makes the page wait.
    """
    raw = await request.body()
    if not raw:
        return _NO_CONTENT
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return _NO_CONTENT

    try:
        event = event_adapter.validate_python(payload)
    except ValidationError:
        return _NO_CONTENT

    await ingest_event(
        session,
        event,
        ua=request.headers.get("user-agent"),
        ip=_client_ip(request),
        country=_edge_country(request),
    )
    return _NO_CONTENT
