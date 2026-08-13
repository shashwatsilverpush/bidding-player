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


async def test_fill_rate_is_per_ad_request_not_per_load(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Fill = impressions / ad requests. Because refresh makes one page load
    produce several ad opportunities, dividing by loads can exceed 100% and is
    not fill at all."""
    ids = await build_chain(client, auth_headers)
    plc = ids["placement_id"]
    await _seed(client, auth_headers, plc, 150)

    s = (
        await client.get(f"/v1/admin/analytics/summary?placement_id={plc}", headers=auth_headers)
    ).json()

    assert s["fillRateBasis"] == "ad_request"
    assert s["adRequests"] > 0
    # Refresh means more opportunities than page loads.
    assert s["adRequests"] > s["loads"]
    assert s["fillRate"] == round(s["impressions"] / s["adRequests"], 4)
    # A real rate never exceeds 1; the old impressions/loads ratio would here.
    assert 0 < s["fillRate"] <= 1
    assert s["adsPerLoad"] > 1
    # Viewability gate: some loads never scroll into view, so views < loads.
    assert 0 < s["views"] < s["loads"]


async def test_waterfall_fill_counts_opportunities_not_attempts(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """A 3-deep waterfall fires 1-3 ad_requests per opportunity. Fill must divide
    by distinct opportunities — dividing by raw attempts would report a chain
    that filled on its last tag as 33% fill."""
    ids = await build_chain(client, auth_headers)
    plc = ids["placement_id"]
    await client.patch(
        f"/v1/admin/placements/{plc}",
        headers=auth_headers,
        json={
            "config": {
                "adTags": [
                    {"url": "https://a.example/vast", "label": "Primary"},
                    {"url": "https://b.example/vast", "label": "Backfill"},
                    {"url": "https://c.example/house", "label": "House"},
                ]
            }
        },
    )
    await _seed(client, auth_headers, plc, 150)

    s = (
        await client.get(f"/v1/admin/analytics/summary?placement_id={plc}", headers=auth_headers)
    ).json()
    # More raw attempts than opportunities => the waterfall really fell through.
    assert s["adRequests"] > s["adOpportunities"] > 0
    assert s["waterfallDepth"] > 1
    assert s["fillRate"] == round(s["impressions"] / s["adOpportunities"], 4)
    assert 0 < s["fillRate"] <= 1

    pos = (
        await client.get(
            f"/v1/admin/analytics/tag-positions?placement_id={plc}", headers=auth_headers
        )
    ).json()
    assert [p["position"] for p in pos] == [1, 2, 3]
    assert [p["label"] for p in pos] == ["Primary", "Backfill", "House"]
    # Deeper positions are reached less often — they only run when earlier ones fail.
    assert pos[0]["reached"] > pos[1]["reached"] > pos[2]["reached"]
    assert sum(p["filled"] for p in pos) == s["impressions"]


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


async def test_breakdown_by_dimension(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    ids = await build_chain(client, auth_headers)
    await _seed(client, auth_headers, ids["placement_id"], 120)
    for dim in ("publisher", "site", "ad_unit", "placement", "format"):
        r = await client.get(f"/v1/admin/analytics/breakdown?dimension={dim}", headers=auth_headers)
        assert r.status_code == 200, dim
        rows = r.json()
        assert len(rows) >= 1
        assert {
            "key",
            "loads",
            "wins",
            "impressions",
            "fillRate",
            "avgCpmRaw",
            "avgCpmBiased",
        } <= set(rows[0].keys())
    bad = await client.get("/v1/admin/analytics/breakdown?dimension=nope", headers=auth_headers)
    assert bad.status_code == 422


async def test_analytics_requires_auth(client: AsyncClient) -> None:
    r = await client.get("/v1/admin/analytics/summary")
    assert r.status_code in (401, 403)
