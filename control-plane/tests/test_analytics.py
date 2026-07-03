from __future__ import annotations

from httpx import AsyncClient
from tests.helpers import build_chain


async def _seed(client: AsyncClient, headers: dict[str, str], plc: str, n: int = 120) -> dict:
    r = await client.post(
        "/v1/admin/analytics/dev/seed", headers=headers, json={"placement_id": plc, "sessions": n}
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_demo_seed_and_summary(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    ids = await build_chain(client, auth_headers)
    plc = ids["placement_id"]
    seeded = await _seed(client, auth_headers, plc, 150)
    assert seeded["seeded"]["player_load"] == 150
    assert seeded["total"] > 150

    r = await client.get(f"/v1/admin/analytics/summary?placement_id={plc}", headers=auth_headers)
    assert r.status_code == 200
    s = r.json()
    assert s["loads"] == 150
    assert s["wins"] > 0
    # raw and biased are tracked separately; biased >= raw (floor bias inflates)
    assert s["avgCpmRaw"] is not None and s["avgCpmBiased"] is not None
    assert s["avgCpmBiased"] >= s["avgCpmRaw"]


async def test_bidders_and_keyvalues(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    ids = await build_chain(client, auth_headers)
    plc = ids["placement_id"]
    await _seed(client, auth_headers, plc, 150)

    bidders = (
        await client.get(f"/v1/admin/analytics/bidders?placement_id={plc}", headers=auth_headers)
    ).json()
    assert len(bidders) >= 1
    assert "wins" in bidders[0] and "bid" in bidders[0]

    kv = (
        await client.get(f"/v1/admin/analytics/key-values?placement_id={plc}", headers=auth_headers)
    ).json()
    assert "hb_pb" in kv and "hb_bidder" in kv
    assert sum(x["count"] for x in kv["hb_bidder"]) > 0


async def test_timeseries(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    ids = await build_chain(client, auth_headers)
    plc = ids["placement_id"]
    await _seed(client, auth_headers, plc, 80)
    ts = (
        await client.get(
            f"/v1/admin/analytics/timeseries?placement_id={plc}&bucket=day", headers=auth_headers
        )
    ).json()
    assert isinstance(ts, list) and len(ts) > 0
    assert {"ts", "event", "count"} <= set(ts[0].keys())


async def test_analytics_requires_auth(client: AsyncClient) -> None:
    r = await client.get("/v1/admin/analytics/summary")
    assert r.status_code in (401, 403)
