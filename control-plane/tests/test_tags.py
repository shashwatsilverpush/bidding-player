from __future__ import annotations

from httpx import AsyncClient
from tests.helpers import build_chain


async def test_embed_tag_is_thin_and_dynamic(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    ids = await build_chain(client, auth_headers)
    await client.patch(
        f"/v1/admin/placements/{ids['placement_id']}",
        headers=auth_headers,
        json={"config": {"placement": "instream", "adTag": "https://gam.example/vast?iu=/x"}},
    )
    r = await client.get(f"/v1/admin/placements/{ids['placement_id']}/embed", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    tag = body["tag"]
    # thin, self-configuring tag
    assert 'id="adtech-player-core"' in tag
    assert "data-config-url=" in tag
    assert "/v1/config" in tag
    assert f'data-placement-id="{ids["placement_id"]}"' in tag
    # must NOT bake the snapshot / leak demand into the publisher's page
    assert "data-bidders=" not in tag
    assert "limelightDigital" not in tag
    assert "data-tag=" not in tag
    assert "data-bias=" not in tag
    # the assembled config is still returned for dashboard preview
    assert body["config"]["adTag"] == "https://gam.example/vast?iu=/x"


async def test_embed_channel_controls_src(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    ids = await build_chain(client, auth_headers)
    auto = (
        await client.get(
            f"/v1/admin/placements/{ids['placement_id']}/embed?channel=auto",
            headers=auth_headers,
        )
    ).json()
    pinned = (
        await client.get(
            f"/v1/admin/placements/{ids['placement_id']}/embed?channel=pinned",
            headers=auth_headers,
        )
    ).json()
    # channel still selects the engine delivery: loader (auto) vs pinned engine
    assert "engine/loader.js" in auto["tag"]
    assert "engine/player.js" in pinned["tag"]
    # thin tag carries no data-prebid-url, so no __VER__ token to substitute
    assert "__VER__" not in auto["tag"]
    assert "__VER__" not in pinned["tag"]


async def test_embed_requires_auth(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    ids = await build_chain(client, auth_headers)
    r = await client.get(f"/v1/admin/placements/{ids['placement_id']}/embed")
    assert r.status_code in (401, 403)
