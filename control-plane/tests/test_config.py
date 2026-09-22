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


async def test_lazy_and_refresh_defaults(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """Lazy is on out of the box; refresh is opt-in only."""
    ids = await build_chain(client, auth_headers)
    cfg = (await client.get(f"/v1/config/{ids['placement_id']}")).json()
    assert cfg["lazy"] is True
    assert cfg["refresh"] is False
    assert cfg["refreshInterval"] == 30
    assert cfg["refreshMax"] == 10


async def test_ad_controls_default_on_and_can_be_turned_off(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Ad-time play/pause + mute is on unless a placement opts out.

    IMA supplies no such controls and its ad layer covers the content player's
    control bar for the length of the break, so a placement that inherits the
    default must still ship controls.
    """
    ids = await build_chain(client, auth_headers)
    plc = ids["placement_id"]
    assert (await client.get(f"/v1/config/{plc}")).json()["adControls"] is True

    r = await client.patch(
        f"/v1/admin/placements/{plc}",
        headers=auth_headers,
        json={"config": {"adControls": False}},
    )
    assert r.status_code == 200
    assert (await client.get(f"/v1/config/{plc}")).json()["adControls"] is False


async def test_refresh_interval_floor_is_enforced(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """A sub-30s refresh interval is rejected at the API, not silently accepted.
    (The engine also floors it at 30s, so neither layer can burn inventory.)"""
    ids = await build_chain(client, auth_headers)
    plc = ids["placement_id"]

    bad = await client.patch(
        f"/v1/admin/placements/{plc}",
        headers=auth_headers,
        json={"config": {"refresh": True, "refreshInterval": 5}},
    )
    assert bad.status_code == 422

    ok = await client.patch(
        f"/v1/admin/placements/{plc}",
        headers=auth_headers,
        json={"config": {"refresh": True, "refreshInterval": 45, "refreshMax": 3}},
    )
    assert ok.status_code == 200, ok.text
    cfg = (await client.get(f"/v1/config/{plc}")).json()
    assert cfg["refresh"] is True
    assert cfg["refreshInterval"] == 45
    assert cfg["refreshMax"] == 3


async def test_legacy_ad_tag_is_promoted_to_a_one_entry_waterfall(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Placements written before the waterfall existed must still serve a chain,
    so the engine never has to special-case 'no adTags'."""
    ids = await build_chain(client, auth_headers)
    plc = ids["placement_id"]

    # A placement with no tag at all has an empty chain — nothing to promote.
    assert (await client.get(f"/v1/config/{plc}")).json()["adTags"] == []

    # Simulate a pre-waterfall placement: only the singular `adTag` is stored.
    r = await client.patch(
        f"/v1/admin/placements/{plc}",
        headers=auth_headers,
        json={"config": {"adTag": "https://legacy.example/gampad/ads?output=vast"}},
    )
    assert r.status_code == 200, r.text

    cfg = (await client.get(f"/v1/config/{plc}")).json()
    assert len(cfg["adTags"]) == 1
    assert (
        cfg["adTags"][0]["url"] == cfg["adTag"] == "https://legacy.example/gampad/ads?output=vast"
    )
    assert cfg["adTags"][0]["timeoutMs"] == 3000


async def test_waterfall_mirrors_first_entry_into_ad_tag(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """`adTag` must track waterfall entry #1 — a pinned pre-2.7.0 engine reads
    only `data-tag`, so a drifting mirror would serve the wrong primary tag."""
    ids = await build_chain(client, auth_headers)
    plc = ids["placement_id"]
    r = await client.patch(
        f"/v1/admin/placements/{plc}",
        headers=auth_headers,
        json={
            "config": {
                "adTags": [
                    {"url": "https://a.example/vast?x=1", "label": "Primary"},
                    {"url": "https://b.example/vast", "label": "Backfill", "timeoutMs": 1500},
                    {"url": "https://c.example/house", "label": "House"},
                ]
            }
        },
    )
    assert r.status_code == 200, r.text

    cfg = (await client.get(f"/v1/config/{plc}")).json()
    assert [t["label"] for t in cfg["adTags"]] == ["Primary", "Backfill", "House"]
    assert cfg["adTags"][1]["timeoutMs"] == 1500
    assert cfg["adTag"] == "https://a.example/vast?x=1"

    # Reordering must move the mirror with it.
    r2 = await client.patch(
        f"/v1/admin/placements/{plc}",
        headers=auth_headers,
        json={
            "config": {
                "adTags": [
                    {"url": "https://c.example/house", "label": "House"},
                    {"url": "https://a.example/vast?x=1", "label": "Primary"},
                ]
            }
        },
    )
    assert r2.status_code == 200
    cfg2 = (await client.get(f"/v1/config/{plc}")).json()
    assert cfg2["adTag"] == "https://c.example/house"


async def test_waterfall_rejects_non_http_tag(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    ids = await build_chain(client, auth_headers)
    r = await client.patch(
        f"/v1/admin/placements/{ids['placement_id']}",
        headers=auth_headers,
        json={"config": {"adTags": [{"url": "javascript:alert(1)"}]}},
    )
    assert r.status_code == 422


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
