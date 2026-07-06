"""Admin: generate the publisher embed `<script>` tag for a placement."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import AdminDep
from app.db import get_session
from app.schemas.config import RuntimeConfig
from app.services.config_assembly import PlacementNotFound, assemble_config
from app.services.embed import build_embed_tag
from app.settings import get_settings

router = APIRouter(prefix="/v1/admin", tags=["tags"], dependencies=[AdminDep])

SessionDep = Depends(get_session)


class EmbedResponse(BaseModel):
    placement_id: str
    channel: str
    tag: str
    config: RuntimeConfig


@router.get("/placements/{placement_id}/embed", response_model=EmbedResponse)
async def get_embed(
    placement_id: str,
    session: AsyncSession = SessionDep,
    channel: str | None = Query(default=None, description="auto|pinned; overrides placement"),
) -> EmbedResponse:
    try:
        cfg = await assemble_config(session, placement_id, require_active=False)
    except PlacementNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "placement not found") from exc

    if channel in ("auto", "pinned"):
        cfg = cfg.model_copy(update={"engineChannel": channel})

    tag = build_embed_tag(cfg, get_settings(), placement_id)
    return EmbedResponse(placement_id=placement_id, channel=cfg.engineChannel, tag=tag, config=cfg)
