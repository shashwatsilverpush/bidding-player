"""Admin: analytics read APIs + a dev-only demo-data seeder."""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import AdminDep
from app.db import get_session
from app.services import analytics
from app.services.analytics import Scope
from app.services.config_assembly import PlacementNotFound
from app.services.demo import seed_events
from app.settings import get_settings

router = APIRouter(prefix="/v1/admin/analytics", tags=["analytics"], dependencies=[AdminDep])

SessionDep = Depends(get_session)


def scope_params(
    placement_id: str | None = Query(default=None),
    publisher_id: str | None = Query(default=None),
    site_id: str | None = Query(default=None),
    ad_unit_id: str | None = Query(default=None),
    format: str | None = Query(default=None, description="ad unit format, e.g. video"),
    player_type: str | None = Query(default=None, description="instream | outstream"),
    country: str | None = Query(default=None, description="ISO-3166 alpha-2, or 'unknown'"),
    device: str | None = Query(default=None, description="desktop|mobile|tablet|ctv|unknown"),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    date_from: date | None = Query(default=None, description="inclusive, in tz"),
    date_to: date | None = Query(default=None, description="inclusive, in tz"),
    tz: str = Query(default="UTC", description="IANA timezone for day buckets and dates"),
) -> Scope:
    """The filter set every analytics endpoint accepts, so all widgets on a
    screen can be driven by one query string."""
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid tz") from exc
    if player_type is not None and player_type not in ("instream", "outstream"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid player_type")
    if device is not None and device not in ("desktop", "mobile", "tablet", "ctv", "unknown"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid device")
    ts_from, ts_to = analytics.window(from_, to, date_from, date_to, tz)
    return Scope(
        publisher_id=publisher_id or None,
        site_id=site_id or None,
        ad_unit_id=ad_unit_id or None,
        placement_id=placement_id or None,
        format=format or None,
        player_type=player_type,
        country=country or None,
        device=device,
        ts_from=ts_from,
        ts_to=ts_to,
        tz=tz,
    )


ScopeDep = Depends(scope_params)


@router.get("/summary")
async def summary(session: AsyncSession = SessionDep, scope: Scope = ScopeDep) -> dict[str, Any]:
    return await analytics.summary(session, scope)


@router.get("/bidders")
async def bidders(
    session: AsyncSession = SessionDep, scope: Scope = ScopeDep
) -> list[dict[str, Any]]:
    return await analytics.by_bidder(session, scope)


@router.get("/tag-positions")
async def tag_positions(
    session: AsyncSession = SessionDep, scope: Scope = ScopeDep
) -> list[dict[str, Any]]:
    """Ad-server waterfall performance per position: reached vs. filled."""
    return await analytics.by_tag_position(session, scope)


@router.get("/timeseries")
async def timeseries(
    session: AsyncSession = SessionDep,
    scope: Scope = ScopeDep,
    bucket: str = Query(default="day"),
) -> list[dict[str, Any]]:
    return await analytics.timeseries(session, scope, bucket=bucket)


@router.get("/breakdown")
async def breakdown(
    session: AsyncSession = SessionDep,
    scope: Scope = ScopeDep,
    dimension: str = Query(default="publisher"),
) -> list[dict[str, Any]]:
    if dimension not in analytics.DIMENSIONS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid dimension")
    return await analytics.breakdown(session, scope, dimension=dimension)


def _dims(raw: str) -> list[str]:
    dims = [d.strip() for d in raw.split(",") if d.strip()]
    if not 1 <= len(dims) <= 3 or len(set(dims)) != len(dims):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "1-3 distinct dimensions")
    bad = [d for d in dims if d not in analytics.DIMENSIONS]
    if bad:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"invalid dimension: {bad[0]}")
    return dims


@router.get("/report")
async def report(
    session: AsyncSession = SessionDep,
    scope: Scope = ScopeDep,
    dimensions: str = Query(default="day", description="comma list, e.g. publisher,day"),
    sort: str | None = Query(default=None, description="any dimension or metric"),
    order: str | None = Query(default=None, description="asc | desc"),
    limit: int = Query(default=1000, ge=1, le=10000),
) -> dict[str, Any]:
    """Dimensional report: funnel + money metrics grouped by up to three
    dimensions (time, tenant chain, country, device, engine, refresh), plus a
    grand-total row computed by the same aggregate."""
    dims = _dims(dimensions)
    rep = await analytics.report(
        session, scope, dimensions=dims, sort=sort, order=order, limit=limit
    )
    rep["totals"] = await analytics.totals(session, scope)
    return rep


@router.get("/report.csv")
async def report_csv(
    session: AsyncSession = SessionDep,
    scope: Scope = ScopeDep,
    dimensions: str = Query(default="day"),
    sort: str | None = Query(default=None),
    order: str | None = Query(default=None),
    limit: int = Query(default=10000, ge=1, le=10000),
) -> Response:
    """The same report as a CSV download — every metric, no row cap below 10k."""
    dims = _dims(dimensions)
    rep = await analytics.report(
        session, scope, dimensions=dims, sort=sort, order=order, limit=limit
    )
    ids = [f"{d}_id" for d in dims if d in analytics.DIM_IDS]
    cols = [*dims, *ids, *analytics.METRICS]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rep["rows"]:
        w.writerow(["" if r.get(c) is None else r.get(c) for c in cols])
    name = "report_" + "_".join(dims) + ".csv"
    return Response(
        buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/errors")
async def errors(
    session: AsyncSession = SessionDep,
    scope: Scope = ScopeDep,
    by_day: bool = Query(default=False),
) -> dict[str, Any]:
    """Ad errors grouped by type (no ad / request failed / playback / bad VAST)
    and IMA code, with share of ad requests; optionally per day."""
    return await analytics.errors(session, scope, by_day=by_day)


@router.get("/filters")
async def filters(session: AsyncSession = SessionDep) -> dict[str, Any]:
    """Options for the report filter bar (tenant chain, formats, countries, …)."""
    return await analytics.filter_options(session)


@router.get("/key-values")
async def key_values(session: AsyncSession = SessionDep, scope: Scope = ScopeDep) -> dict[str, Any]:
    return await analytics.key_values(session, scope)


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
