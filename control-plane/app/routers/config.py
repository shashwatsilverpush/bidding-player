"""Public runtime-config endpoint consumed by the engine."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas.config import RuntimeConfig
from app.services.config_assembly import (
    PlacementNotFound,
    assemble_config,
    base_url_from_request,
)

router = APIRouter(prefix="/v1/config", tags=["config"])

SessionDep = Depends(get_session)


@router.get("/{placement_id}", response_model=RuntimeConfig)
async def get_config(
    placement_id: str, request: Request, response: Response, session: AsyncSession = SessionDep
) -> RuntimeConfig:
    try:
        cfg = await assemble_config(
            session, placement_id, request_base=base_url_from_request(request)
        )
    except PlacementNotFound as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail={"error": "placement_not_found", "id": placement_id}
        ) from exc
    # Edge-cacheable; the engine fetches this with a short timeout + localStorage
    # fallback. stale-while-revalidate lets an edge serve slightly-stale config
    # while it refreshes, so a control-plane blip never blocks the player.
    response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=86400"
    return cfg
