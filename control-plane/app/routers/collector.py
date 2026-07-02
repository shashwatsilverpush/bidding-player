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
    )
    return _NO_CONTENT
