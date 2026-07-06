"""Admin: analytics read APIs + a dev-only demo-data seeder."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import AdminDep
from app.db import get_session
from app.services import analytics
from app.services.config_assembly import PlacementNotFound
from app.services.demo import seed_events
from app.settings import get_settings

router = APIRouter(prefix="/v1/admin/analytics", tags=["analytics"], dependencies=[AdminDep])

SessionDep = Depends(get_session)


@router.get("/summary")
async def summary(
    session: AsyncSession = SessionDep,
    placement_id: str | None = Query(default=None),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
) -> dict[str, Any]:
    return await analytics.summary(session, placement_id=placement_id, ts_from=from_, ts_to=to)


@router.get("/bidders")
async def bidders(
    session: AsyncSession = SessionDep,
    placement_id: str | None = Query(default=None),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
) -> list[dict[str, Any]]:
    return await analytics.by_bidder(session, placement_id=placement_id, ts_from=from_, ts_to=to)


@router.get("/timeseries")
async def timeseries(
    session: AsyncSession = SessionDep,
    placement_id: str | None = Query(default=None),
    bucket: str = Query(default="day"),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
) -> list[dict[str, Any]]:
    return await analytics.timeseries(
        session, placement_id=placement_id, ts_from=from_, ts_to=to, bucket=bucket
    )


@router.get("/breakdown")
async def breakdown(
    session: AsyncSession = SessionDep,
    dimension: str = Query(default="publisher"),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
) -> list[dict[str, Any]]:
    if dimension not in ("publisher", "site", "ad_unit", "placement", "format"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid dimension")
    return await analytics.breakdown(session, dimension=dimension, ts_from=from_, ts_to=to)


@router.get("/key-values")
async def key_values(
    session: AsyncSession = SessionDep,
    placement_id: str | None = Query(default=None),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
) -> dict[str, Any]:
    return await analytics.key_values(session, placement_id=placement_id, ts_from=from_, ts_to=to)


class SeedRequest(BaseModel):
    placement_id: str
    sessions: int = 200
    days: int = 7


@router.post("/dev/seed")
async def dev_seed(body: SeedRequest, session: AsyncSession = SessionDep) -> dict[str, Any]:
    """Insert synthetic events (dev only) so the dashboards have data to show."""
    if not get_settings().allow_dev_endpoints:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "dev endpoints disabled")
    if body.sessions < 1 or body.sessions > 5000:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "sessions must be 1..5000")
    try:
        made = await seed_events(session, body.placement_id, body.sessions, body.days)
    except PlacementNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "placement not found") from exc
    return {"seeded": made, "total": sum(made.values())}
