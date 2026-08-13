"""Dev-only synthetic event generator so the analytics dashboards have data to
show before real player traffic exists. Guarded by settings.allow_dev_endpoints.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import gen_id, utcnow
from app.models import AdUnit, Event, Placement, Publisher, PublisherDemand, Site
from app.services.config_assembly import PlacementNotFound


def _bucket(cpm: float) -> str:
    return f"{(int(cpm / 0.10) * 0.10):.2f}"


def _opportunity(
    mk: Any,
    rng: random.Random,
    bidders: list[str],
    sid: str,
    ts: datetime,
    placement_kind: str,
    tags: list[tuple[str, float]],
) -> None:
    """One ad opportunity: auction -> ad-server waterfall -> render.

    Event order mirrors the engine exactly. In particular ``ad_request`` fires on
    *every* path out of the auction (win, no demand) and once per waterfall tag
    tried — all sharing this opportunity's ``auction_id``, which is what lets
    reporting divide by opportunities rather than attempts.

    ``tags`` is [(label, base fill probability)] in waterfall order.
    """
    mk("bid_request", {"bidders": bidders, "timeout": 1200}, sid, ts)

    best_cpm = 0.0
    best_bidder: str | None = None
    for b in bidders:
        roll = rng.random()
        if roll < 0.55:
            cpm = round(rng.uniform(0.2, 3.0), 2)
            mk(
                "bid_response",
                {
                    "bidder": b,
                    "cpm": cpm,
                    "currency": "USD",
                    "status": "bid",
                    "latencyMs": rng.randint(60, 900),
                },
                sid,
                ts,
            )
            if cpm > best_cpm:
                best_cpm, best_bidder = cpm, b
        elif roll < 0.85:
            mk(
                "bid_response",
                {"bidder": b, "status": "no-bid", "latencyMs": rng.randint(50, 500)},
                sid,
                ts,
            )
        elif roll < 0.95:
            mk("bid_response", {"bidder": b, "status": "timeout", "latencyMs": 1200}, sid, ts)
        else:
            mk("bid_response", {"bidder": b, "status": "error"}, sid, ts)

    if best_bidder is None:
        mk("no_demand", {"phase": "auction", "fallbackServed": True}, sid, ts)
    else:
        raw = best_cpm
        biased = round(int((raw + 0.10) / 0.10) * 0.10, 2)
        mk(
            "auction_win",
            {
                "bidder": best_bidder,
                "cpmRaw": raw,
                "cpmBiased": biased,
                "hbPb": _bucket(biased),
                "floorApplied": True,
            },
            sid,
            ts,
            bidder=best_bidder,
            cpm_raw=raw,
            cpm_biased=biased,
            hb_pb=_bucket(biased),
        )
    # --- ad-server waterfall -------------------------------------------------
    # One ad_request per tag TRIED, all sharing this opportunity's auction_id.
    # The chain stops at the first tag that fills; the house tag (last) almost
    # always does, which is what makes the last position look near-100%.
    won = best_bidder is not None
    for pos, (label, fill_p) in enumerate(tags):
        mk(
            "ad_request",
            {"placement": placement_kind, "wonBid": won, "tagIndex": pos, "tagLabel": label},
            sid,
            ts,
        )
        # A bid winner is far likelier to fill on the primary tag.
        p = fill_p + (0.25 if (won and pos == 0) else 0.0)
        if rng.random() < min(p, 0.98):
            if rng.random() < 0.04:  # filled, then died mid-render
                mk("ad_error", {"errorCode": "900", "phase": "ima"}, sid, ts)
                return
            mk(
                "impression",
                {
                    "adId": gen_id("ad", 6),
                    "creativeId": gen_id("cr", 6),
                    "adDuration": rng.choice([15.0, 30.0]),
                },
                sid,
                ts,
            )
            if rng.random() < 0.88:
                mk("ad_complete", {"viewedPct": 100.0, "quartiles": [1, 2, 3, 4]}, sid, ts)
            return
        # This tag returned nothing — record why, then fall through to the next.
        mk("ad_error", {"errorCode": "1009", "phase": "ima_loader"}, sid, ts)

    # Every tag in the chain failed.
    mk("no_demand", {"phase": "waterfall_exhausted", "fallbackServed": False}, sid, ts)


async def seed_events(
    session: AsyncSession,
    placement_id: str,
    sessions: int,
    days: int = 7,
    refresh: bool = True,
) -> dict[str, int]:
    """Insert ``sessions`` synthetic player sessions spread over the last ``days``.
    Distribution: ~85% fill, realistic per-bidder statuses; both raw and biased CPM.

    Each session is a page load that yields one or more *ad opportunities* (when
    ``refresh``), each with its own ``auction_id`` and incrementing
    ``refresh_index`` — mirroring what the engine emits so the funnel metrics are
    exercised the same way real traffic will exercise them."""
    plc = await session.get(Placement, placement_id)
    if plc is None:
        raise PlacementNotFound(placement_id)

    chain = await _load_chain(session, plc)
    account_id = chain["account_id"]
    ad_unit_path = chain["ad_unit_path"]
    bidders: list[str] = chain["bidders"] or ["limelightDigital", "appnexus", "pubmatic"]
    pcfg = plc.config_json or {}
    placement_kind = pcfg.get("placement", "instream")

    # Mirror the placement's real waterfall so seeded data matches the shape the
    # engine will actually produce. Fill probability decays down the chain (the
    # deeper tags are backfill), and the last position behaves like a house tag
    # that nearly always serves.
    cfg_tags = pcfg.get("adTags") or ([{"url": pcfg["adTag"]}] if pcfg.get("adTag") else [])
    tags: list[tuple[str, float]] = []
    for i, t in enumerate(cfg_tags):
        label = (t or {}).get("label") or f"tag {i + 1}"
        last = i == len(cfg_tags) - 1
        tags.append((label, 0.90 if last and i > 0 else max(0.60 - i * 0.15, 0.2)))
    if not tags:
        tags = [("primary", 0.85)]

    rng = random.Random(hash(placement_id) & 0xFFFFFFFF)
    now = utcnow()
    rows: list[dict[str, Any]] = []
    made = {
        "player_load": 0,
        "player_view": 0,
        "bid_request": 0,
        "ad_request": 0,
        "bid_response": 0,
        "auction_win": 0,
        "impression": 0,
        "ad_complete": 0,
        "ad_error": 0,
        "no_demand": 0,
    }

    # Set per opportunity by the loop below; every event inherits the identity of
    # the opportunity it belongs to.
    cur: dict[str, Any] = {"auction_id": None, "refresh_index": 0}

    def mk(event: str, props: dict[str, Any], sid: str, when: datetime, **extra: Any) -> None:
        rows.append(
            {
                "id": gen_id("evt"),
                "event_id": gen_id("dm", 16),
                "event_type": event,
                "ts_client": int(when.timestamp() * 1000),
                "ts_server": when,
                "account_id": account_id,
                "placement_id": placement_id,
                "ad_unit_path": ad_unit_path,
                "page_url": "https://demo.example/article",
                "session_id": sid,
                "auction_id": cur["auction_id"],
                "refresh_index": cur["refresh_index"],
                "engine_version": "2.7.0",
                "props": props,
                **extra,
            }
        )
        made[event] += 1

    for _ in range(sessions):
        ts = now - timedelta(
            days=rng.randint(0, max(days - 1, 0)),
            hours=rng.randint(0, 23),
            minutes=rng.randint(0, 59),
        )
        sid = gen_id("sess", 8)
        cur["auction_id"], cur["refresh_index"] = gen_id("auc", 12), 0
        mk("player_load", {"placement": placement_kind}, sid, ts)

        # ~8% of loads never scroll into view, so they never release an auction.
        if rng.random() < 0.08:
            continue
        ts += timedelta(seconds=rng.randint(0, 20))
        mk("player_view", {"placement": placement_kind, "delayMs": rng.randint(0, 20000)}, sid, ts)

        # Opportunities on this page load: the first, plus refresh cycles for as
        # long as the user stays in view.
        opportunities = 1 + (rng.randint(0, 4) if refresh else 0)
        for idx in range(opportunities):
            if idx:
                cur["auction_id"], cur["refresh_index"] = gen_id("auc", 12), idx
                ts += timedelta(seconds=rng.randint(30, 90))
            _opportunity(mk, rng, bidders, sid, ts, placement_kind, tags)

    session.add_all([Event(**r) for r in rows])
    await session.commit()
    return made


async def _load_chain(session: AsyncSession, plc: Placement) -> dict[str, Any]:
    au = await session.get(AdUnit, plc.ad_unit_id)
    assert au is not None, "ad_unit missing for placement"
    site = await session.get(Site, au.site_id)
    assert site is not None, "site missing for ad_unit"
    pub = await session.get(Publisher, site.publisher_id)
    assert pub is not None, "publisher missing for site"

    dp_rows = (
        (
            await session.execute(
                select(PublisherDemand).where(
                    PublisherDemand.publisher_id == pub.id, PublisherDemand.enabled.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    codes: list[str] = []
    for pd in dp_rows:
        await session.refresh(pd, ["demand_partner"])
        codes.append(pd.demand_partner.code)
    return {"account_id": pub.account_id, "ad_unit_path": au.gam_ad_unit_path, "bidders": codes}
