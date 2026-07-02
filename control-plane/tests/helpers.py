"""Shared test helpers: build a full publisher chain via the admin API."""

from __future__ import annotations

from httpx import AsyncClient


async def build_chain(client: AsyncClient, headers: dict[str, str]) -> dict[str, str]:
    """Create publisher -> site -> ad_unit -> placement and enable a bidder.
    Returns the created ids."""
    pub = (
        await client.post(
            "/v1/admin/publishers",
            headers=headers,
            json={"name": "Acme Media", "gam_network_code": "21775744923"},
        )
    ).json()
    site = (
        await client.post(
            f"/v1/admin/publishers/{pub['id']}/sites",
            headers=headers,
            json={"domain": "acme.example"},
        )
    ).json()
    au = (
        await client.post(
            f"/v1/admin/sites/{site['id']}/ad-units",
            headers=headers,
            json={"gam_ad_unit_path": "/21775744923/acme/video", "format": "video"},
        )
    ).json()
    plc = (
        await client.post(
            f"/v1/admin/ad-units/{au['id']}/placements",
            headers=headers,
            json={
                "name": "Homepage instream",
                "engine_channel": "auto",
                "config": {
                    "placement": "instream",
                    "timeout": 1200,
                    "bias": "0.00",
                    "video": "https://vjs.zencdn.net/v/oceans.mp4",
                },
            },
        )
    ).json()
    # enable a demand partner for the publisher
    await client.put(
        f"/v1/admin/publishers/{pub['id']}/demand/limelightDigital",
        headers=headers,
        json={
            "params": {
                "host": "ads-jbi003.rtba.bidsxchange.com",
                "publisherId": "649658371",
                "adUnitId": 972556929,
                "adUnitType": "video",
            },
            "enabled": True,
        },
    )
    return {
        "publisher_id": pub["id"],
        "site_id": site["id"],
        "ad_unit_id": au["id"],
        "placement_id": plc["id"],
    }
