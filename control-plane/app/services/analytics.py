"""Read-side analytics over the events table.

All bid-side (Prebid) metrics. Note: eCPM here is the *bid* CPM the auction
produced, not GAM-settled revenue — that reconciliation is Phase 2. `cpm_raw` vs
`cpm_biased` are reported separately so bias uplift never inflates reported yield.

Every read takes a :class:`Scope` — the same filter set (tenant chain, format,
country, device, time window, timezone) — so the KPI tiles, funnel, charts and
report table on one screen always describe exactly the same slice of traffic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Float, Integer, case, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models import AdUnit, Event, Placement, Publisher, Site


@dataclass(frozen=True)
class Scope:
    """Filters shared by every analytics read. ``tz`` decides where a "day"
    starts, both for day buckets and for ``date_from``/``date_to``."""

    publisher_id: str | None = None
    site_id: str | None = None
    ad_unit_id: str | None = None
    placement_id: str | None = None
    format: str | None = None
    player_type: str | None = None
    country: str | None = None
    device: str | None = None
    ts_from: datetime | None = None
    ts_to: datetime | None = None
    tz: str = "UTC"

    @property
    def needs_chain(self) -> bool:
        return any((self.publisher_id, self.site_id, self.ad_unit_id, self.format))


def window(
    ts_from: datetime | None,
    ts_to: datetime | None,
    date_from: date | None,
    date_to: date | None,
    tz: str,
) -> tuple[datetime | None, datetime | None]:
    """Resolve the time window. Calendar dates are inclusive and interpreted in
    ``tz`` (so "2026-09-24" in Europe/Prague is that day in Prague, not in UTC);
    they win over raw timestamps when both are given."""
    zone = ZoneInfo(tz)
    if date_from is not None:
        ts_from = datetime.combine(date_from, time.min, zone)
    if date_to is not None:
        # exclusive upper bound handled by <= on the last microsecond of the day
        ts_to = datetime.combine(date_to + timedelta(days=1), time.min, zone) - timedelta(
            microseconds=1
        )
    return ts_from, ts_to


# Coarse device class from the User-Agent. Order matters: tablets and TVs also
# advertise "Android", and iPads identify as desktop Safari only in iPadOS 13+
# (those land in desktop — nothing server-side can tell them apart).
device_class: ColumnElement[str] = case(
    (Event.ua.is_(None), literal("unknown")),
    (
        Event.ua.op("~*")("smart-?tv|tizen|webos|roku|appletv|crkey|bravia|hbbtv|aft[a-z]"),
        literal("ctv"),
    ),
    (Event.ua.op("~*")("ipad|tablet|kindle|silk|(android(?!.*mobile))"), literal("tablet")),
    (Event.ua.op("~*")("mobi|iphone|ipod|android|windows phone"), literal("mobile")),
    else_=literal("desktop"),
)

# instream / outstream, from the placement's own config.
player_type_expr: ColumnElement[str] = func.coalesce(
    Placement.config_json["placement"].astext, literal("instream")
)


def _filters(scope: Scope) -> list[ColumnElement[bool]]:
    conds: list[ColumnElement[bool]] = []
    if scope.placement_id:
        conds.append(Event.placement_id == scope.placement_id)
    if scope.ts_from is not None:
        conds.append(Event.ts_server >= scope.ts_from)
    if scope.ts_to is not None:
        conds.append(Event.ts_server <= scope.ts_to)
    if scope.country:
        if scope.country == "unknown":
            conds.append(Event.ip_country.is_(None))
        else:
            conds.append(Event.ip_country == scope.country.upper())
    if scope.device:
        conds.append(device_class == scope.device)
    if scope.needs_chain or scope.player_type:
        # Tenant-chain filters resolve to a set of placement ids, so reads that
        # never join the chain (summary, bidders, …) can still honour them.
        sub = select(Placement.id).join(AdUnit, Placement.ad_unit_id == AdUnit.id)
        sub = sub.join(Site, AdUnit.site_id == Site.id)
        if scope.publisher_id:
            sub = sub.where(Site.publisher_id == scope.publisher_id)
        if scope.site_id:
            sub = sub.where(Site.id == scope.site_id)
        if scope.ad_unit_id:
            sub = sub.where(AdUnit.id == scope.ad_unit_id)
        if scope.format:
            sub = sub.where(AdUnit.format == scope.format)
        if scope.player_type:
            sub = sub.where(player_type_expr == scope.player_type)
        # correlate(None): the report query joins these same tables, and
        # auto-correlation would otherwise bind the subquery to the outer row.
        conds.append(Event.placement_id.in_(sub.correlate(None)))
    return conds


async def summary(
    session: AsyncSession,
    scope: Scope,
) -> dict[str, Any]:
    conds = _filters(scope)

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

    money = await totals(session, scope)
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
        **{k: money.get(k) for k in ("revenue", "ecpm", "rpm")},
    }


async def by_bidder(
    session: AsyncSession,
    scope: Scope,
) -> list[dict[str, Any]]:
    conds = _filters(scope)
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
    scope: Scope,
) -> list[dict[str, Any]]:
    """Waterfall performance per position: how often each tag was reached, and
    how often it was the one that filled.

    'Reached' is the count of ad_requests at that position. 'Filled' is the
    number of those opportunities that produced an impression — attributed by
    joining on auction_id and taking the DEEPEST position reached for that
    opportunity, since the engine stops the chain as soon as a tag fills.
    """
    conds = _filters(scope)
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
    scope: Scope,
    bucket: str = "day",
) -> list[dict[str, Any]]:
    if bucket not in ("hour", "day"):
        bucket = "day"
    conds = _filters(scope)
    trunc = func.date_trunc(bucket, func.timezone(scope.tz, Event.ts_server))
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
    scope: Scope,
) -> dict[str, Any]:
    conds = _filters(scope)
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


def _money(v: Any, nd: int = 4) -> float | None:
    return round(float(v), nd) if v is not None else None


def _derived(
    *,
    loads: int,
    views: int,
    requests: int,
    ad_requests: int,
    opportunities: int,
    wins: int,
    impressions: int,
    modern_impressions: int,
    completes: int,
    errors: int,
    no_demand: int,
    avg_raw: Any,
    avg_biased: Any,
    revenue: Any,
) -> dict[str, Any]:
    """Every metric the report shows, from raw counts. Shared by report rows and
    the totals row so a total can never be computed differently from its rows."""

    def rate(a: int, b: int) -> float | None:
        return round(a / b, 4) if b else None

    # Same fill rule as summary(): distinct opportunities on the modern basis,
    # bid requests for windows holding only pre-2.7.0 rows.
    if opportunities:
        fill, basis = rate(modern_impressions, opportunities), "ad_request"
    else:
        fill, basis = rate(impressions, requests), "bid_request(legacy)"
    rev = float(revenue) if revenue is not None else 0.0
    return {
        "loads": loads,
        "views": views,
        "viewRate": rate(views, loads),
        "requests": requests,
        "adRequests": ad_requests,
        "adOpportunities": opportunities,
        "wins": wins,
        "winRate": rate(wins, requests),
        "impressions": impressions,
        "fillRate": fill,
        "fillRateBasis": basis,
        "completes": completes,
        "completeRate": rate(completes, impressions),
        "errors": errors,
        "noDemand": no_demand,
        "adsPerLoad": round(impressions / loads, 3) if loads else None,
        "avgCpmRaw": _money(avg_raw),
        "avgCpmBiased": _money(avg_biased),
        # Derived money metrics — raw CPM only, so floor bias never inflates them.
        #   revenue : sum of winning bid CPMs / 1000 for wins that rendered
        #   ecpm    : revenue per 1000 impressions (ALL impressions, incl. ones GAM
        #             filled without a header-bidding win — so it sits below
        #             avgCpmRaw whenever direct/house demand fills)
        #   rpm     : revenue per 1000 page loads
        "revenue": round(rev, 4),
        "ecpm": round(rev / impressions * 1000, 4) if impressions else None,
        "rpm": round(rev / loads * 1000, 4) if loads else None,
    }


# Report dimensions -> grouping expression. Time dimensions bucket in scope.tz.
TIME_DIMS = ("day", "week", "month", "hour")
CHAIN_DIMS = ("publisher", "site", "ad_unit", "placement", "format", "player_type")
DIMENSIONS = (
    *TIME_DIMS,
    *CHAIN_DIMS,
    "country",
    "device",
    "engine_version",
    "refresh",
)
METRICS = (
    "loads", "views", "viewRate", "requests", "adRequests", "adOpportunities", "wins",
    "winRate", "impressions", "fillRate", "completes", "completeRate", "errors",
    "noDemand", "adsPerLoad", "avgCpmRaw", "avgCpmBiased", "revenue", "ecpm", "rpm",
)  # fmt: skip


def _dim_expr(dim: str, tz: str) -> Any:
    if dim in TIME_DIMS:
        return func.date_trunc(dim, func.timezone(tz, Event.ts_server))
    return {
        "publisher": Publisher.name,
        "site": Site.domain,
        "ad_unit": AdUnit.gam_ad_unit_path,
        "placement": Placement.name,
        "format": AdUnit.format,
        "player_type": player_type_expr,
        "country": func.coalesce(Event.ip_country, literal("unknown")),
        "device": device_class,
        "engine_version": func.coalesce(Event.engine_version, literal("unknown")),
        "refresh": case(
            (func.coalesce(Event.refresh_index, 0) == 0, literal("initial")),
            else_=literal("refresh"),
        ),
    }[dim]


# Entity dimensions group by id as well as by display name: two publishers (or
# sites) may share a name, and grouping on the name alone would silently merge
# their traffic into one row.
DIM_IDS: dict[str, Any] = {
    "publisher": Publisher.id,
    "site": Site.id,
    "ad_unit": AdUnit.id,
    "placement": Placement.id,
}


def _dim_value(dim: str, v: Any) -> Any:
    if dim in TIME_DIMS and isinstance(v, datetime):
        if dim == "hour":
            return v.strftime("%Y-%m-%d %H:00")
        if dim == "month":
            return v.strftime("%Y-%m")
        return v.date().isoformat()  # day, and week (= its Monday)
    return v


async def report(
    session: AsyncSession,
    scope: Scope,
    *,
    dimensions: list[str],
    sort: str | None = None,
    order: str | None = None,
    limit: int = 1000,
) -> dict[str, Any]:
    """Grouped funnel + money metrics by up to three dimensions (e.g. publisher x
    day). Rows are sorted server-side on any dimension or metric, then capped at
    ``limit``; ``total`` reports how many groups existed before the cap."""
    conds = _filters(scope)
    exprs = [_dim_expr(d, scope.tz).label(f"d{i}") for i, d in enumerate(dimensions)]
    id_exprs = [DIM_IDS[d].label(f"id{i}") for i, d in enumerate(dimensions) if d in DIM_IDS]

    def cnt(event: str) -> ColumnElement[int]:
        return func.count().filter(Event.event_type == event)

    # Impressions attributable to an opportunity; revenue only counts wins that
    # actually rendered. Legacy (pre-2.7.0) rows carry no auction_id, so their
    # wins cannot be matched to an impression and are counted as-is.
    rendered = (
        select(Event.auction_id)
        .where(*conds, Event.event_type == "impression", Event.auction_id.isnot(None))
        .correlate(None)
        .scalar_subquery()
    )
    win_rendered = (Event.event_type == "auction_win") & (
        Event.auction_id.is_(None) | Event.auction_id.in_(rendered)
    )

    stmt = select(
        *exprs,
        *id_exprs,
        cnt("player_load").label("loads"),
        cnt("player_view").label("views"),
        cnt("bid_request").label("requests"),
        cnt("ad_request").label("ad_requests"),
        func.count(func.distinct(Event.auction_id))
        .filter(Event.event_type == "ad_request")
        .label("opportunities"),
        cnt("auction_win").label("wins"),
        cnt("impression").label("impressions"),
        func.count()
        .filter(Event.event_type == "impression", Event.auction_id.isnot(None))
        .label("modern_impressions"),
        cnt("ad_complete").label("completes"),
        cnt("ad_error").label("errors"),
        cnt("no_demand").label("no_demand"),
        func.avg(Event.cpm_raw).label("avg_raw"),
        func.avg(Event.cpm_biased).label("avg_biased"),
        (func.sum(Event.cpm_raw).filter(win_rendered) / 1000).label("revenue"),
    ).select_from(Event)
    if any(d in CHAIN_DIMS for d in dimensions):
        # Inner joins: events whose placement no longer resolves (hard-deleted
        # chain) drop out of chain breakdowns, exactly as before.
        stmt = (
            stmt.join(Placement, Event.placement_id == Placement.id)
            .join(AdUnit, Placement.ad_unit_id == AdUnit.id)
            .join(Site, AdUnit.site_id == Site.id)
            .join(Publisher, Site.publisher_id == Publisher.id)
        )
    stmt = stmt.where(*conds)
    if exprs:
        stmt = stmt.group_by(*exprs, *id_exprs)
    rows = (await session.execute(stmt)).mappings().all()

    out: list[dict[str, Any]] = []
    for r in rows:
        rec: dict[str, Any] = {}
        for i, d in enumerate(dimensions):
            rec[d] = _dim_value(d, r[f"d{i}"])
            if d in DIM_IDS:
                rec[f"{d}_id"] = r[f"id{i}"]
        rec.update(
            _derived(
                loads=r["loads"],
                views=r["views"],
                requests=r["requests"],
                ad_requests=r["ad_requests"],
                opportunities=r["opportunities"],
                wins=r["wins"],
                impressions=r["impressions"],
                modern_impressions=r["modern_impressions"],
                completes=r["completes"],
                errors=r["errors"],
                no_demand=r["no_demand"],
                avg_raw=r["avg_raw"],
                avg_biased=r["avg_biased"],
                revenue=r["revenue"],
            )
        )
        out.append(rec)

    # Defaults: a time-led report is newest first; a single entity dimension is
    # biggest first; a multi-dimension report (publisher x day) is grouped by
    # its leading dimension so each publisher's days sit together.
    if sort not in (*dimensions, *METRICS):
        if not dimensions:
            sort = "loads"
        elif dimensions[0] in TIME_DIMS or len(dimensions) > 1:
            sort = dimensions[0]
        else:
            sort = "loads"
    if order not in ("asc", "desc"):
        order = "asc" if sort in dimensions and sort not in TIME_DIMS else "desc"
    # Nulls always sort last, whichever direction. Ties fall back to the other
    # dimensions in order — entities A→Z, time newest first.
    present = [r for r in out if r.get(sort) is not None]
    missing = [r for r in out if r.get(sort) is None]
    for d in reversed([d for d in dimensions if d != sort]):
        present.sort(key=lambda r: str(r.get(d) or ""), reverse=d in TIME_DIMS)  # noqa: B023
    present.sort(key=lambda r: r[sort], reverse=order == "desc")

    return {
        "dimensions": dimensions,
        "sort": sort,
        "order": order,
        "tz": scope.tz,
        "total": len(out),
        "truncated": len(out) > limit,
        "rows": (present + missing)[:limit],
    }


async def totals(session: AsyncSession, scope: Scope) -> dict[str, Any]:
    """The report's grand-total row: the same aggregate with no grouping."""
    rep = await report(session, scope, dimensions=[])
    return rep["rows"][0] if rep["rows"] else {}


async def breakdown(
    session: AsyncSession,
    scope: Scope,
    *,
    dimension: str,
) -> list[dict[str, Any]]:
    """Back-compat single-dimension shape: ``key`` + metrics, biggest first."""
    rep = await report(session, scope, dimensions=[dimension], sort="loads", order="desc")
    return [{"key": r.pop(dimension), **r} for r in rep["rows"]]


async def filter_options(session: AsyncSession) -> dict[str, Any]:
    """Everything the report's filter bar can offer. Soft-deleted entities are
    included (their historical traffic is still reportable) and flagged."""
    pubs = (await session.execute(select(Publisher).order_by(Publisher.name))).scalars().all()
    sites = (await session.execute(select(Site).order_by(Site.domain))).scalars().all()
    aus = (await session.execute(select(AdUnit).order_by(AdUnit.gam_ad_unit_path))).scalars().all()
    plcs = (await session.execute(select(Placement).order_by(Placement.name))).scalars().all()
    countries = (
        (
            await session.execute(
                select(Event.ip_country)
                .where(Event.ip_country.isnot(None))
                .distinct()
                .order_by(Event.ip_country)
            )
        )
        .scalars()
        .all()
    )
    return {
        "publishers": [
            {"id": p.id, "name": p.name, "deleted": p.deleted_at is not None} for p in pubs
        ],
        "sites": [
            {"id": s.id, "name": s.domain, "publisher_id": s.publisher_id,
             "deleted": s.deleted_at is not None}
            for s in sites
        ],
        "ad_units": [
            {"id": a.id, "name": a.gam_ad_unit_path, "site_id": a.site_id, "format": a.format,
             "deleted": a.deleted_at is not None}
            for a in aus
        ],
        "placements": [
            {"id": p.id, "name": p.name, "ad_unit_id": p.ad_unit_id,
             "deleted": p.deleted_at is not None}
            for p in plcs
        ],
        "formats": sorted({a.format for a in aus}),
        "player_types": ["instream", "outstream"],
        "countries": [*countries, "unknown"],
        "devices": ["desktop", "mobile", "tablet", "ctv", "unknown"],
        "dimensions": list(DIMENSIONS),
    }  # fmt: skip
