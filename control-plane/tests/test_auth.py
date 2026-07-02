from __future__ import annotations

from httpx import AsyncClient


async def test_login_success(client: AsyncClient) -> None:
    resp = await client.post("/auth/login", json={"username": "admin", "password": "admin"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["expires_in"] > 0


async def test_login_bad_password(client: AsyncClient) -> None:
    resp = await client.post("/auth/login", json={"username": "admin", "password": "nope"})
    assert resp.status_code == 401


async def test_admin_route_requires_token(client: AsyncClient) -> None:
    resp = await client.get("/v1/admin/publishers")
    assert resp.status_code in (401, 403)


async def test_admin_route_rejects_bad_token(client: AsyncClient) -> None:
    resp = await client.get("/v1/admin/publishers", headers={"Authorization": "Bearer garbage"})
    assert resp.status_code == 401
