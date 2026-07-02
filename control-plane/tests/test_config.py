from __future__ import annotations

from httpx import AsyncClient
from tests.helpers import build_chain


async def test_config_assembly(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    ids = await build_chain(client, auth_headers)
    r = await client.get(f"/v1/config/{ids['placement_id']}")
    assert r.status_code == 200
    cfg = r.json()

    assert cfg["placement"] == "instream"
    assert cfg["timeout"] == 1200
    assert cfg["bias"] == "0.00"
    assert cfg["video"] == "https://vjs.zencdn.net/v/oceans.mp4"
    assert cfg["beaconUrl"].endswith("/e")
    assert cfg["adUnitPath"] == "/21775744923/acme/video"
    assert cfg["prebidUrl"]
    # the enabled bidder is assembled with its params
    assert len(cfg["bidders"]) == 1
    assert cfg["bidders"][0]["bidder"] == "limelightDigital"
    assert cfg["bidders"][0]["params"]["publisherId"] == "649658371"
    # cache header set
    assert "max-age=300" in r.headers.get("cache-control", "")


async def test_config_unknown_placement_404(client: AsyncClient) -> None:
    r = await client.get("/v1/config/plc_doesnotexist")
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "placement_not_found"


async def test_inactive_placement_404(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    ids = await build_chain(client, auth_headers)
    await client.patch(
        f"/v1/admin/placements/{ids['placement_id']}",
        headers=auth_headers,
        json={"active": False},
    )
    r = await client.get(f"/v1/config/{ids['placement_id']}")
    assert r.status_code == 404


async def test_disabled_bidder_excluded(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    ids = await build_chain(client, auth_headers)
    # disable the enabled partner
    await client.put(
        f"/v1/admin/publishers/{ids['publisher_id']}/demand/limelightDigital",
        headers=auth_headers,
        json={
            "params": {
                "host": "h",
                "publisherId": "p",
                "adUnitId": 1,
                "adUnitType": "video",
            },
            "enabled": False,
        },
    )
    r = await client.get(f"/v1/config/{ids['placement_id']}")
    assert r.json()["bidders"] == []
