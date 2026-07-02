from __future__ import annotations

from app.services.seed import BOOTSTRAP_ACCOUNT_ID
from httpx import AsyncClient
from tests.helpers import build_chain


async def test_stats_requires_auth(client: AsyncClient) -> None:
    r = await client.get("/v1/admin/stats")
    assert r.status_code in (401, 403)


async def test_stats_counts_by_type_and_placement_filter(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    ids = await build_chain(client, auth_headers)
    plc = ids["placement_id"]

    def env(event: str, eid: str) -> dict:
        base = {
            "v": 1,
            "event": event,
            "eventId": eid,
            "account": BOOTSTRAP_ACCOUNT_ID,
            "placementId": plc,
            "props": {},
        }
        if event == "auction_win":
            base["props"] = {"bidder": "x", "cpmRaw": 1.0, "cpmBiased": 1.1}
        if event == "bid_response":
            base["props"] = {"bidder": "x", "status": "bid"}
        return base

    for event, eid in [
        ("player_load", "s1"),
        ("player_load", "s2"),
        ("bid_request", "s3"),
        ("auction_win", "s4"),
    ]:
        await client.post("/e", json=env(event, eid))

    r = await client.get(f"/v1/admin/stats?placement_id={plc}", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["counts"]["player_load"] == 2
    assert body["counts"]["bid_request"] == 1
    assert body["total"] == 4

    # filter to a placement with no events
    r2 = await client.get("/v1/admin/stats?placement_id=plc_other", headers=auth_headers)
    assert r2.json()["total"] == 0
