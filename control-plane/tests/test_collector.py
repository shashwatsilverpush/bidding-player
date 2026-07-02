from __future__ import annotations

import json

from app.services.seed import BOOTSTRAP_ACCOUNT_ID
from httpx import AsyncClient
from tests.helpers import build_chain


def _envelope(event: str, event_id: str, placement_id: str, **props) -> dict:
    return {
        "v": 1,
        "event": event,
        "ts": 1710000000000,
        "eventId": event_id,
        "account": BOOTSTRAP_ACCOUNT_ID,
        "placementId": placement_id,
        "adUnitPath": "/21775744923/acme/video",
        "pageUrl": "https://acme.example/article",
        "sessionId": "sess-1",
        "engineVersion": "2.5.0",
        "props": props,
    }


async def _stats(client: AsyncClient, headers: dict[str, str]) -> dict:
    r = await client.get("/v1/admin/stats", headers=headers)
    return r.json()


async def test_all_event_types_accepted(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    ids = await build_chain(client, auth_headers)
    plc = ids["placement_id"]
    events = [
        _envelope("player_load", "e1", plc, placement="instream"),
        _envelope("bid_request", "e2", plc, bidders=["limelightDigital"], timeout=1200),
        _envelope("bid_response", "e3", plc, bidder="limelightDigital", status="bid", cpm=1.2),
        _envelope(
            "auction_win",
            "e4",
            plc,
            bidder="limelightDigital",
            cpmRaw=1.2,
            cpmBiased=1.3,
            hbPb="1.30",
        ),
        _envelope("impression", "e5", plc, adId="a1", creativeId="c1"),
        _envelope("ad_complete", "e6", plc, viewedPct=100.0),
        _envelope("ad_error", "e7", plc, errorCode="900", phase="ima"),
        _envelope("no_demand", "e8", plc, fallbackServed=True),
    ]
    for ev in events:
        r = await client.post("/e", json=ev)
        assert r.status_code == 204, ev["event"]

    stats = await _stats(client, auth_headers)
    assert stats["total"] == 8
    assert stats["counts"]["auction_win"] == 1


async def test_sendbeacon_text_plain_body(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    ids = await build_chain(client, auth_headers)
    ev = _envelope("player_load", "beacon-1", ids["placement_id"])
    r = await client.post(
        "/e", content=json.dumps(ev), headers={"Content-Type": "text/plain;charset=UTF-8"}
    )
    assert r.status_code == 204
    stats = await _stats(client, auth_headers)
    assert stats["total"] == 1


async def test_idempotent_dedup(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    ids = await build_chain(client, auth_headers)
    ev = _envelope("player_load", "dup-1", ids["placement_id"])
    await client.post("/e", json=ev)
    await client.post("/e", json=ev)  # same eventId
    stats = await _stats(client, auth_headers)
    assert stats["total"] == 1


async def test_win_fields_promoted(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    from app.db import SessionLocal
    from app.models import Event
    from sqlalchemy import select

    ids = await build_chain(client, auth_headers)
    ev = _envelope(
        "auction_win",
        "win-1",
        ids["placement_id"],
        bidder="limelightDigital",
        cpmRaw=2.0,
        cpmBiased=2.1,
        hbPb="2.10",
        floorApplied=True,
    )
    await client.post("/e", json=ev)
    async with SessionLocal() as s:
        row = (await s.execute(select(Event).where(Event.event_id == "win-1"))).scalar_one()
        assert float(row.cpm_raw) == 2.0
        assert float(row.cpm_biased) == 2.1
        assert row.hb_pb == "2.10"
        assert row.bidder == "limelightDigital"


async def test_unknown_account_dropped(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    ids = await build_chain(client, auth_headers)
    ev = _envelope("player_load", "unk-1", ids["placement_id"])
    ev["account"] = "acc_nonexistent"
    r = await client.post("/e", json=ev)
    assert r.status_code == 204  # still 204 (don't leak)
    stats = await _stats(client, auth_headers)
    assert stats["total"] == 0


async def test_invalid_event_type_dropped(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    ids = await build_chain(client, auth_headers)
    ev = _envelope("not_a_real_event", "bad-1", ids["placement_id"])
    r = await client.post("/e", json=ev)
    assert r.status_code == 204
    stats = await _stats(client, auth_headers)
    assert stats["total"] == 0


async def test_consent_anonymize(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    from app.db import SessionLocal
    from app.models import Event
    from sqlalchemy import select

    ids = await build_chain(client, auth_headers)
    ev = _envelope("player_load", "consent-1", ids["placement_id"])
    ev["consent"] = {"gdpr": True}  # gdpr applies, no tcString -> anonymize
    r = await client.post("/e", json=ev)
    assert r.status_code == 204
    async with SessionLocal() as s:
        row = (await s.execute(select(Event).where(Event.event_id == "consent-1"))).scalar_one()
        assert row.page_url is None  # stripped
        assert row.gdpr_applies is True
