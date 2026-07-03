from __future__ import annotations

from httpx import AsyncClient
from tests.helpers import build_chain


async def test_embed_tag_generation(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    ids = await build_chain(client, auth_headers)
    # give the placement a GAM tag
    await client.patch(
        f"/v1/admin/placements/{ids['placement_id']}",
        headers=auth_headers,
        json={"config": {"placement": "instream", "adTag": "https://gam.example/vast?iu=/x"}},
    )
    r = await client.get(f"/v1/admin/placements/{ids['placement_id']}/embed", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    tag = body["tag"]
    assert 'id="adtech-player-core"' in tag
    assert "data-bidders=" in tag
    assert "limelightDigital" in tag  # enabled in build_chain
    assert 'data-tag="https://gam.example/vast?iu=/x"' in tag


async def test_embed_channel_override(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    ids = await build_chain(client, auth_headers)
    auto = (
        await client.get(
            f"/v1/admin/placements/{ids['placement_id']}/embed?channel=auto", headers=auth_headers
        )
    ).json()
    pinned = (
        await client.get(
            f"/v1/admin/placements/{ids['placement_id']}/embed?channel=pinned",
            headers=auth_headers,
        )
    ).json()
    assert "engine/loader.js" in auto["tag"]  # auto emits the loader
    assert "__VER__" in auto["tag"]  # prebid url tokenized for the loader
    assert "engine/player.js" in pinned["tag"]  # pinned emits the engine directly


async def test_embed_requires_auth(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    ids = await build_chain(client, auth_headers)
    r = await client.get(f"/v1/admin/placements/{ids['placement_id']}/embed")
    assert r.status_code in (401, 403)
