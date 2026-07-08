from __future__ import annotations

from httpx import AsyncClient
from tests.helpers import build_chain


async def test_full_chain_crud(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    ids = await build_chain(client, auth_headers)
    # each resource is retrievable
    for path in (
        f"/v1/admin/publishers/{ids['publisher_id']}",
        f"/v1/admin/sites/{ids['site_id']}",
        f"/v1/admin/ad-units/{ids['ad_unit_id']}",
        f"/v1/admin/placements/{ids['placement_id']}",
    ):
        r = await client.get(path, headers=auth_headers)
        assert r.status_code == 200, path


async def test_patch_publisher(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    ids = await build_chain(client, auth_headers)
    r = await client.patch(
        f"/v1/admin/publishers/{ids['publisher_id']}",
        headers=auth_headers,
        json={"status": "paused"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "paused"


async def test_delete_cascades(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    ids = await build_chain(client, auth_headers)
    # a parent with live children requires the explicit cascade flag
    blocked = await client.delete(
        f"/v1/admin/publishers/{ids['publisher_id']}", headers=auth_headers
    )
    assert blocked.status_code == 409
    r = await client.delete(
        f"/v1/admin/publishers/{ids['publisher_id']}",
        headers=auth_headers,
        params={"cascade": "true"},
    )
    assert r.status_code == 204
    # child placement is gone (soft-deleted)
    r2 = await client.get(f"/v1/admin/placements/{ids['placement_id']}", headers=auth_headers)
    assert r2.status_code == 404


async def test_get_missing_returns_404(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    r = await client.get("/v1/admin/publishers/pub_missing", headers=auth_headers)
    assert r.status_code == 404


async def test_demand_catalog_seeded(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    r = await client.get("/v1/admin/demand-partners", headers=auth_headers)
    assert r.status_code == 200
    codes = {p["code"] for p in r.json()}
    assert {"limelightDigital", "appnexus", "rubicon", "pubmatic", "openx", "incrementx"} <= codes


async def test_enable_demand_missing_params_rejected(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    ids = await build_chain(client, auth_headers)
    r = await client.put(
        f"/v1/admin/publishers/{ids['publisher_id']}/demand/rubicon",
        headers=auth_headers,
        json={"params": {"accountId": "123"}, "enabled": True},  # missing siteId, zoneId
    )
    assert r.status_code == 422
