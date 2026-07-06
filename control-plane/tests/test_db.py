from __future__ import annotations

from app.db import async_engine_args


def test_sslmode_stripped_and_ssl_context_added() -> None:
    url, ca = async_engine_args("postgresql+asyncpg://u:p@h:5432/db?sslmode=require")
    assert "sslmode" not in url
    assert url == "postgresql+asyncpg://u:p@h:5432/db"
    assert "ssl" in ca  # SSL context supplied to asyncpg


def test_channel_binding_stripped() -> None:
    url, _ = async_engine_args(
        "postgresql+asyncpg://u:p@h/db?sslmode=require&channel_binding=require"
    )
    assert "channel_binding" not in url and "sslmode" not in url


def test_plain_url_no_connect_args() -> None:
    url, ca = async_engine_args("postgresql+asyncpg://u:p@h/db")
    assert ca == {}
    assert url == "postgresql+asyncpg://u:p@h/db"


def test_sslmode_disable_no_ssl() -> None:
    _, ca = async_engine_args("postgresql+asyncpg://u:p@h/db?sslmode=disable")
    assert ca == {}
