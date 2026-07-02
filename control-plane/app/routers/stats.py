"""Admin: minimal read API to sanity-check the telemetry pipeline."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import AdminDep
from app.db import get_session
from app.services.ingest import count_by_type

router = APIRouter(prefix="/v1/admin", tags=["stats"], dependencies=[AdminDep])

SessionDep = Depends(get_session)


class StatsResponse(BaseModel):
    placement_id: str | None
    from_: datetime | None
    to: datetime | None
    total: int
    counts: dict[str, int]


@router.get("/stats", response_model=StatsResponse)
async def stats(
    session: AsyncSession = SessionDep,
    placement_id: str | None = Query(default=None),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
) -> StatsResponse:
    counts = await count_by_type(session, placement_id=placement_id, ts_from=from_, ts_to=to)
    return StatsResponse(
        placement_id=placement_id,
        from_=from_,
        to=to,
        total=sum(counts.values()),
        counts=counts,
    )
