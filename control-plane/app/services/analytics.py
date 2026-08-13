"""Read-side analytics over the events table.

All bid-side (Prebid) metrics. Note: eCPM here is the *bid* CPM the auction
produced, not GAM-settled revenue — that reconciliation is Phase 2. `cpm_raw` vs
`cpm_biased` are reported separately so bias uplift never inflates reported yield.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Float, Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models import AdUnit, Event, Placement, Publisher, Site


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

    # Three distinct funnel levels that must never be used interchangeably:
    #   loads       - the tag booted (once per page load)
    #   views       - the slot became viewable and released the auction
    #   requests    - Prebid auctions run  (0 when Prebid fails to load)
    #   adRequests  - VAST calls to the ad server (fires on EVERY render path,
    #                 including the fallbacks that skip the auction entirely)
    # With ad refresh on, one load produces many requests/adRequests/impressions,
    # so any ratio that mixes a per-load numerator with a per-opportunity
    # denominator (or vice versa) is meaningless and can exceed 100%.
    loads = counts.get("player_load", 0)
    views = counts.get("player_view", 0)
    requests = counts.get("bid_request", 0)
    ad_requests = counts.get("ad_request", 0)
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

    # Fill = impressions per AD request. Engines older than 2.7.0 never emitted
    # ad_request, so for windows containing only legacy rows we fall back to the
    # bid-request denominator and say so, rather than reporting a blank.
    #
    # During the rollout a window holds BOTH kinds of row. Dividing every
    # impression (legacy + new) by only the new engines' ad requests would
    # overstate fill badly, so the modern basis counts numerator and denominator
    # over the same population: rows carrying an auction_id, which is exactly the
    # set of engines that also emit ad_request.
    if ad_requests:
        modern_impressions = (
            await session.execute(
                select(func.count()).where(
                    *conds, Event.event_type == "impression", Event.auction_id.isnot(None)
                )
            )
        ).scalar_one()
        # An ad-tag waterfall fires one ad_request PER TAG TRIED, but the whole
        # chain is a single ad opportunity sharing one auction_id. Counting raw
        # attempts here would report a 3-deep waterfall that filled on its last
        # tag as 33% fill instead of 100%. Count distinct opportunities instead.
        ad_opportunities = (
            await session.execute(
                select(func.count(func.distinct(Event.auction_id))).where(
                    *conds, Event.event_type == "ad_request", Event.auction_id.isnot(None)
                )
            )
        ).scalar_one()
        fill_rate, fill_basis = rate(modern_impressions, ad_opportunities), "ad_request"
    else:
        ad_opportunities = 0
        fill_rate, fill_basis = rate(impressions, requests), "bid_request(legacy)"

    return {
        "counts": counts,
        "loads": loads,
        "views": views,
        "requests": requests,
        # adRequests = raw VAST calls (one per waterfall tag tried).
        # adOpportunities = distinct chances to serve. Fill divides by the latter;
        # the ratio between them is the waterfall's average depth.
        "adRequests": ad_requests,
        "adOpportunities": ad_opportunities,
        "waterfallDepth": (round(ad_requests / ad_opportunities, 2) if ad_opportunities else None),
        "wins": wins,
        "impressions": impressions,
        "completes": completes,
        "errors": errors,
        "noDemand": no_demand,
        "viewRate": rate(views, loads),
        "winRate": rate(wins, requests),
        "fillRate": fill_rate,
        "fillRateBasis": fill_basis,
        "completeRate": rate(completes, impressions),
        # How many ad opportunities each page load actually produced. This is the
        # metric that shows refresh working; it is NOT a rate and can exceed 1.
        "adsPerLoad": round(impressions / loads, 3) if loads else None,
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


async def by_tag_position(
    session: AsyncSession,
    *,
    placement_id: str | None,
    ts_from: datetime | None,
    ts_to: datetime | None,
) -> list[dict[str, Any]]:
    """Waterfall performance per position: how often each tag was reached, and
    how often it was the one that filled.

    'Reached' is the count of ad_requests at that position. 'Filled' is the
    number of those opportunities that produced an impression — attributed by
    joining on auction_id and taking the DEEPEST position reached for that
    opportunity, since the engine stops the chain as soon as a tag fills.
    """
    conds = _filters(placement_id, ts_from, ts_to)
    idx = Event.props["tagIndex"].astext.cast(Integer)
    label = Event.props["tagLabel"].astext

    reached_rows = (
        await session.execute(
            select(idx.label("idx"), func.min(label).label("label"), func.count().label("n"))
            .where(*conds, Event.event_type == "ad_request", idx.isnot(None))
            .group_by(idx)
            .order_by(idx)
        )
    ).all()

    # Deepest tag position per opportunity == the tag that ended the chain.
    last_pos = (
        select(Event.auction_id.label("aid"), func.max(idx).label("idx"))
        .where(*conds, Event.event_type == "ad_request", Event.auction_id.isnot(None))
        .group_by(Event.auction_id)
        .subquery()
    )
    filled_aids = (
        select(Event.auction_id)
        .where(*conds, Event.event_type == "impression", Event.auction_id.isnot(None))
        .subquery()
    )
    filled_rows = (
        await session.execute(
            select(last_pos.c.idx, func.count())
            .join(filled_aids, filled_aids.c.auction_id == last_pos.c.aid)
            .group_by(last_pos.c.idx)
        )
    ).all()
    filled: dict[int, int] = {int(i): int(n) for i, n in filled_rows if i is not None}

    out: list[dict[str, Any]] = []
    for i, lbl, n in reached_rows:
        f = filled.get(i, 0)
        out.append(
            {
                "position": (i or 0) + 1,
                "label": lbl or f"tag {(i or 0) + 1}",
                "reached": n,
                "filled": f,
                "fillRate": round(f / n, 4) if n else None,
            }
        )
    return out


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


# Dimension -> the grouping column (joined events -> placement -> ad_unit -> site -> publisher).
_DIM_COLS = {
    "publisher": Publisher.name,
    "site": Site.domain,
    "ad_unit": AdUnit.gam_ad_unit_path,
    "placement": Placement.name,
    "format": AdUnit.format,
}


async def breakdown(
    session: AsyncSession,
    *,
    dimension: str,
    ts_from: datetime | None,
    ts_to: datetime | None,
) -> list[dict[str, Any]]:
    """Per-dimension funnel metrics, joining events up the tenant chain.
    dimension ∈ publisher | site | ad_unit | placement | format."""
    dim = _DIM_COLS.get(dimension, Publisher.name)

    def cnt(event: str) -> ColumnElement[int]:
        return func.count().filter(Event.event_type == event)

    conds: list[ColumnElement[bool]] = []
    if ts_from is not None:
        conds.append(Event.ts_server >= ts_from)
    if ts_to is not None:
        conds.append(Event.ts_server <= ts_to)

    stmt = (
        select(
            dim.label("key"),
            cnt("player_load").label("loads"),
            cnt("bid_request").label("requests"),
            cnt("ad_request").label("ad_requests"),
            cnt("auction_win").label("wins"),
            cnt("impression").label("impressions"),
            func.avg(Event.cpm_raw).label("avg_raw"),
            func.avg(Event.cpm_biased).label("avg_biased"),
        )
        .select_from(Event)
        .join(Placement, Event.placement_id == Placement.id)
        .join(AdUnit, Placement.ad_unit_id == AdUnit.id)
        .join(Site, AdUnit.site_id == Site.id)
        .join(Publisher, Site.publisher_id == Publisher.id)
        .where(*conds)
        .group_by(dim)
        .order_by(cnt("player_load").desc())
    )
    rows = (await session.execute(stmt)).all()
    out: list[dict[str, Any]] = []
    for key, loads, requests, ad_requests, wins, imps, avg_raw, avg_biased in rows:
        # Same denominator rule as summary(): fill is per ad request, with a
        # legacy fallback to bid requests for pre-2.7.0 rows.
        denom = ad_requests or requests
        out.append(
            {
                "key": key,
                "loads": loads,
                "requests": requests,
                "adRequests": ad_requests,
                "wins": wins,
                "impressions": imps,
                "fillRate": round(imps / denom, 4) if denom else None,
                "adsPerLoad": round(imps / loads, 3) if loads else None,
                "avgCpmRaw": round(float(avg_raw), 4) if avg_raw is not None else None,
                "avgCpmBiased": round(float(avg_biased), 4) if avg_biased is not None else None,
            }
        )
    return out
