"""Soft delete (with cascade guard + restore) and the admin change-history log."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from tests.helpers import build_chain

pytestmark = pytest.mark.asyncio


async def _audit(client: AsyncClient, headers: dict[str, str], **params: str) -> list[dict]:
    resp = await client.get("/v1/admin/audit-log", headers=headers, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- soft delete ----------------------------------------------------------


async def test_delete_placement_is_soft_and_hides_from_list_and_config(
    client: AsyncClient, auth_headers: dict[str, str]
):
    ids = await build_chain(client, auth_headers)
    plc_id, au_id = ids["placement_id"], ids["ad_unit_id"]

    # config serves before delete
    assert (await client.get(f"/v1/config/{plc_id}")).status_code == 200

    resp = await client.delete(f"/v1/admin/placements/{plc_id}", headers=auth_headers)
    assert resp.status_code == 204

    # gone from the list, 404 on fetch, and no longer served
    listed = (
        await client.get(f"/v1/admin/ad-units/{au_id}/placements", headers=auth_headers)
    ).json()
    assert plc_id not in [p["id"] for p in listed]
    assert (
        await client.get(f"/v1/admin/placements/{plc_id}", headers=auth_headers)
    ).status_code == 404
    assert (await client.get(f"/v1/config/{plc_id}")).status_code == 404


async def test_delete_publisher_requires_cascade_flag(
    client: AsyncClient, auth_headers: dict[str, str]
):
    ids = await build_chain(client, auth_headers)
    pub_id, plc_id = ids["publisher_id"], ids["placement_id"]

    # refused while it still has live children
    resp = await client.delete(f"/v1/admin/publishers/{pub_id}", headers=auth_headers)
    assert resp.status_code == 409
    assert "cascade" in resp.json()["detail"]

    # with the flag the whole subtree goes down
    resp = await client.delete(
        f"/v1/admin/publishers/{pub_id}", headers=auth_headers, params={"cascade": "true"}
    )
    assert resp.status_code == 204

    assert pub_id not in [
        p["id"] for p in (await client.get("/v1/admin/publishers", headers=auth_headers)).json()
    ]
    assert (await client.get(f"/v1/config/{plc_id}")).status_code == 404


async def test_restore_publisher_brings_it_back(client: AsyncClient, auth_headers: dict[str, str]):
    ids = await build_chain(client, auth_headers)
    pub_id = ids["publisher_id"]

    await client.delete(
        f"/v1/admin/publishers/{pub_id}", headers=auth_headers, params={"cascade": "true"}
    )
    resp = await client.post(f"/v1/admin/publishers/{pub_id}/restore", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["deleted_at"] is None
    assert pub_id in [
        p["id"] for p in (await client.get("/v1/admin/publishers", headers=auth_headers)).json()
    ]


# --- demand partner delete ------------------------------------------------


async def test_delete_demand_partner_blocked_while_in_use(
    client: AsyncClient, auth_headers: dict[str, str]
):
    await build_chain(client, auth_headers)  # enables limelightDigital for a publisher
    partners = (await client.get("/v1/admin/demand-partners", headers=auth_headers)).json()
    in_use = next(p for p in partners if p["code"] == "limelightDigital")

    resp = await client.delete(f"/v1/admin/demand-partners/{in_use['id']}", headers=auth_headers)
    assert resp.status_code == 409


async def test_delete_unused_demand_partner_succeeds(
    client: AsyncClient, auth_headers: dict[str, str]
):
    created = (
        await client.post(
            "/v1/admin/demand-partners",
            headers=auth_headers,
            json={"code": "tempSsp", "label": "Temp", "adapter_module": "tempBidAdapter"},
        )
    ).json()
    resp = await client.delete(f"/v1/admin/demand-partners/{created['id']}", headers=auth_headers)
    assert resp.status_code == 204


# --- history log ----------------------------------------------------------


async def test_audit_records_create_update_delete_restore(
    client: AsyncClient, auth_headers: dict[str, str]
):
    ids = await build_chain(client, auth_headers)
    pub_id = ids["publisher_id"]

    # create was logged
    rows = await _audit(client, auth_headers, entity_id=pub_id)
    assert any(r["action"] == "create" for r in rows)

    # update
    await client.patch(
        f"/v1/admin/publishers/{pub_id}", headers=auth_headers, json={"name": "Renamed"}
    )
    rows = await _audit(client, auth_headers, entity_id=pub_id, action="update")
    assert rows and "name" in rows[0]["changed_fields"]
    assert rows[0]["before"]["name"] == "Acme Media"
    assert rows[0]["after"]["name"] == "Renamed"

    # soft delete is logged as a delete (not a generic update), and carries the
    # human label captured at write time (readable even though the row is now gone)
    await client.delete(
        f"/v1/admin/publishers/{pub_id}", headers=auth_headers, params={"cascade": "true"}
    )
    dels = await _audit(client, auth_headers, entity_id=pub_id, action="delete")
    assert dels and dels[0]["entity_label"] == "Renamed"

    # restore
    await client.post(f"/v1/admin/publishers/{pub_id}/restore", headers=auth_headers)
    assert await _audit(client, auth_headers, entity_id=pub_id, action="restore")


async def test_audit_captures_actor_and_device_signals(
    client: AsyncClient, auth_headers: dict[str, str]
):
    ids = await build_chain(client, auth_headers)
    rows = await _audit(client, auth_headers, entity_id=ids["publisher_id"], action="create")
    row = rows[0]
    assert row["actor"] == "admin"
    assert row["entity_label"] == "Acme Media"  # name, not just the opaque id
    assert row["method"] == "POST"
    assert row["path"] == "/v1/admin/publishers"
    assert row["user_agent"]  # httpx sends a default UA
    assert row["request_id"]


async def test_cascade_delete_logs_every_child(client: AsyncClient, auth_headers: dict[str, str]):
    ids = await build_chain(client, auth_headers)
    await client.delete(
        f"/v1/admin/publishers/{ids['publisher_id']}",
        headers=auth_headers,
        params={"cascade": "true"},
    )
    # one delete entry each for publisher, site, ad_unit, placement
    for key, entity in [
        ("publisher_id", "publisher"),
        ("site_id", "site"),
        ("ad_unit_id", "ad_unit"),
        ("placement_id", "placement"),
    ]:
        rows = await _audit(client, auth_headers, entity_id=ids[key], action="delete")
        assert rows and rows[0]["entity_type"] == entity

    # the whole cascade shares one request_id
    dels = await _audit(client, auth_headers, action="delete")
    req_ids = {r["request_id"] for r in dels if r["entity_id"] in ids.values()}
    assert len(req_ids) == 1


async def test_reading_audit_log_does_not_audit_itself(
    client: AsyncClient, auth_headers: dict[str, str]
):
    await build_chain(client, auth_headers)
    before = len(await _audit(client, auth_headers))
    await _audit(client, auth_headers)  # a read
    after = len(await _audit(client, auth_headers))
    assert before == after
    assert not await _audit(client, auth_headers, entity_type="audit_log")
