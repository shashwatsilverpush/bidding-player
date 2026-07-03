"""Read-side analytics over the events table.

All bid-side (Prebid) metrics. Note: eCPM here is the *bid* CPM the auction
produced, not GAM-settled revenue — that reconciliation is Phase 2. `cpm_raw` vs
`cpm_biased` are reported separately so bias uplift never inflates reported yield.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Float, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models import Event


def _filters(
    placement_id: str | None, ts_from: datetime | None, ts_to: datetime | None
) -> list[ColumnElement[bool]]:
    conds: list[ColumnElement[bool]] = []
    if placement_id:
        conds.append(Event.placement_id == placement_id)
    if ts_from is not None:
        conds.append(Event.ts_server >= ts_from)
    if ts_to is not None:
        conds.append(Event.ts_server <= ts_to)
    return conds


async def summary(
    session: AsyncSession,
    *,
    placement_id: str | None,
    ts_from: datetime | None,
    ts_to: datetime | None,
) -> dict[str, Any]:
    conds = _filters(placement_id, ts_from, ts_to)

    rows = (
        await session.execute(
            select(Event.event_type, func.count()).where(*conds).group_by(Event.event_type)
        )
    ).all()
    counts = {row[0]: row[1] for row in rows}

    win_stats = (
        await session.execute(
            select(func.avg(Event.cpm_raw), func.avg(Event.cpm_biased)).where(
                *conds, Event.event_type == "auction_win"
            )
        )
    ).one()
    avg_raw = float(win_stats[0]) if win_stats[0] is not None else None
    avg_biased = float(win_stats[1]) if win_stats[1] is not None else None

    loads = counts.get("player_load", 0)
    requests = counts.get("bid_request", 0)
    wins = counts.get("auction_win", 0)
    impressions = counts.get("impression", 0)
    completes = counts.get("ad_complete", 0)
    errors = counts.get("ad_error", 0)
    no_demand = counts.get("no_demand", 0)

    def rate(a: int, b: int) -> float | None:
        return round(a / b, 4) if b else None

    uplift = None
    if avg_raw and avg_biased and avg_raw > 0:
        uplift = round((avg_biased - avg_raw) / avg_raw * 100, 2)

    return {
        "counts": counts,
        "loads": loads,
        "requests": requests,
        "wins": wins,
        "impressions": impressions,
        "completes": completes,
        "errors": errors,
        "noDemand": no_demand,
        "winRate": rate(wins, requests),
        "fillRate": rate(impressions, loads),
        "completeRate": rate(completes, impressions),
        "avgCpmRaw": round(avg_raw, 4) if avg_raw is not None else None,
        "avgCpmBiased": round(avg_biased, 4) if avg_biased is not None else None,
        "biasUpliftPct": uplift,
    }


async def by_bidder(
    session: AsyncSession,
    *,
    placement_id: str | None,
    ts_from: datetime | None,
    ts_to: datetime | None,
) -> list[dict[str, Any]]:
    conds = _filters(placement_id, ts_from, ts_to)
    bidder = Event.props["bidder"].astext
    status = Event.props["status"].astext
    cpm = Event.props["cpm"].astext.cast(Float)
    latency = Event.props["latencyMs"].astext.cast(Float)

    resp_rows = (
        await session.execute(
            select(
                bidder.label("bidder"),
                status.label("status"),
                func.count().label("n"),
                func.avg(cpm).label("avg_cpm"),
                func.avg(latency).label("avg_latency"),
            )
            .where(*conds, Event.event_type == "bid_response")
            .group_by(bidder, status)
        )
    ).all()

    win_rows = (
        await session.execute(
            select(Event.bidder, func.count())
            .where(*conds, Event.event_type == "auction_win")
            .group_by(Event.bidder)
        )
    ).all()
    wins = {b: n for b, n in win_rows if b}

    agg: dict[str, dict[str, Any]] = {}
    for b, st, n, avg_cpm, avg_lat in resp_rows:
        if not b:
            continue
        rec = agg.setdefault(
            b,
            {
                "bidder": b,
                "bid": 0,
                "no-bid": 0,
                "timeout": 0,
                "error": 0,
                "avgCpm": None,
                "avgLatencyMs": None,
                "wins": 0,
            },
        )
        if st in ("bid", "no-bid", "timeout", "error"):
            rec[st] = n
        if st == "bid":
            rec["avgCpm"] = round(float(avg_cpm), 4) if avg_cpm is not None else None
            rec["avgLatencyMs"] = round(float(avg_lat), 1) if avg_lat is not None else None

    for b, n in wins.items():
        agg.setdefault(
            b,
            {
                "bidder": b,
                "bid": 0,
                "no-bid": 0,
                "timeout": 0,
                "error": 0,
                "avgCpm": None,
                "avgLatencyMs": None,
                "wins": 0,
            },
        )
        agg[b]["wins"] = n

    return sorted(agg.values(), key=lambda r: (-r["wins"], -r["bid"]))


async def timeseries(
    session: AsyncSession,
    *,
    placement_id: str | None,
    ts_from: datetime | None,
    ts_to: datetime | None,
    bucket: str = "day",
) -> list[dict[str, Any]]:
    if bucket not in ("hour", "day"):
        bucket = "day"
    conds = _filters(placement_id, ts_from, ts_to)
    trunc = func.date_trunc(bucket, Event.ts_server)
    rows = (
        await session.execute(
            select(trunc.label("ts"), Event.event_type, func.count())
            .where(*conds)
            .group_by(trunc, Event.event_type)
            .order_by(trunc)
        )
    ).all()
    return [
        {"ts": ts.isoformat() if isinstance(ts, datetime) else str(ts), "event": et, "count": n}
        for ts, et, n in rows
    ]


async def key_values(
    session: AsyncSession,
    *,
    placement_id: str | None,
    ts_from: datetime | None,
    ts_to: datetime | None,
) -> dict[str, Any]:
    conds = _filters(placement_id, ts_from, ts_to)
    hb_rows = (
        await session.execute(
            select(Event.hb_pb, func.count())
            .where(*conds, Event.event_type == "auction_win")
            .group_by(Event.hb_pb)
            .order_by(Event.hb_pb)
        )
    ).all()
    winner_rows = (
        await session.execute(
            select(Event.bidder, func.count())
            .where(*conds, Event.event_type == "auction_win")
            .group_by(Event.bidder)
            .order_by(func.count().desc())
        )
    ).all()
    return {
        "hb_pb": [{"value": v or "(none)", "count": n} for v, n in hb_rows],
        "hb_bidder": [{"value": b or "(none)", "count": n} for b, n in winner_rows],
    }
