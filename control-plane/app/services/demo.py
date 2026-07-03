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


async def seed_events(
    session: AsyncSession, placement_id: str, sessions: int, days: int = 7
) -> dict[str, int]:
    """Insert ``sessions`` synthetic player sessions spread over the last ``days``.
    Distribution: ~85% fill, realistic per-bidder statuses; both raw and biased CPM."""
    plc = await session.get(Placement, placement_id)
    if plc is None:
        raise PlacementNotFound(placement_id)

    chain = await _load_chain(session, plc)
    account_id = chain["account_id"]
    ad_unit_path = chain["ad_unit_path"]
    bidders: list[str] = chain["bidders"] or ["limelightDigital", "appnexus", "pubmatic"]
    placement_kind = (plc.config_json or {}).get("placement", "instream")

    rng = random.Random(hash(placement_id) & 0xFFFFFFFF)
    now = utcnow()
    rows: list[dict[str, Any]] = []
    made = {
        "player_load": 0,
        "bid_request": 0,
        "bid_response": 0,
        "auction_win": 0,
        "impression": 0,
        "ad_complete": 0,
        "ad_error": 0,
        "no_demand": 0,
    }

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
                "engine_version": "2.5.0",
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
        mk("player_load", {"placement": placement_kind}, sid, ts)
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
            continue

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

        if rng.random() < 0.06:
            mk(
                "ad_error",
                {"errorCode": str(rng.choice([303, 900, 1009])), "phase": "ima"},
                sid,
                ts,
            )
            continue
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
