"""Async SQLAlchemy engine, session factory, and FastAPI dependency."""

from __future__ import annotations

import os
import secrets
import ssl
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import DateTime, String, func
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import NullPool

from app.settings import get_settings

_settings = get_settings()


def async_engine_args(url: str) -> tuple[str, dict[str, Any]]:
    """Make a managed-Postgres URL usable by asyncpg.

    Managed DBs (Shipyard/RDS/Neon) hand out libpq-style URLs with
    ``?sslmode=require`` (and sometimes ``channel_binding``). asyncpg's
    ``connect()`` rejects those kwargs ("unexpected keyword argument 'sslmode'"),
    so strip them from the URL and translate an SSL requirement into an asyncpg
    ``ssl`` context via connect_args. `require`-style = encrypt without cert
    verification (managed hosts often present certs that won't verify by hostname).
    """
    parts = urlsplit(url)
    q = dict(parse_qsl(parts.query))
    sslmode = q.pop("sslmode", None)
    q.pop("channel_binding", None)
    clean = urlunsplit(parts._replace(query=urlencode(q)))
    connect_args: dict[str, Any] = {}
    if sslmode and sslmode.lower() != "disable":
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        connect_args["ssl"] = ctx
    return clean, connect_args


# Tests run each case on a fresh event loop; a pooled asyncpg connection bound to
# one loop can't be reused on another ("attached to a different loop"). NullPool
# opens a connection per operation on the current loop, sidestepping that. Enabled
# via DB_NULLPOOL=1 (set by the test harness); prod keeps normal pooling.
_engine_kwargs: dict = {"future": True}
if os.environ.get("DB_NULLPOOL") == "1":
    _engine_kwargs["poolclass"] = NullPool
else:
    _engine_kwargs["pool_pre_ping"] = True

_db_url, _connect_args = async_engine_args(_settings.database_url)
engine = create_async_engine(_db_url, connect_args=_connect_args, **_engine_kwargs)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


# Base32-ish alphabet without ambiguous chars, matching the engine's opaque-id style.
_ID_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz"


def gen_id(prefix: str, length: int = 10) -> str:
    """Opaque, URL-safe id: ``<prefix>_<random>`` e.g. ``plc_5A3bK9xQ2m``."""
    body = "".join(secrets.choice(_ID_ALPHABET) for _ in range(length))
    return f"{prefix}_{body}"


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base with created_at / updated_at on every table."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class IdMixin:
    """Opaque string primary key. Subclasses set ``_id_prefix``."""

    _id_prefix: str = "id"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
