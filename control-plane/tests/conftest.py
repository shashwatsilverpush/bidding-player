"""Test fixtures.

Schema is bootstrapped here via ``Base.metadata.create_all`` for isolation and
speed. Migrations remain the canonical schema source — CI additionally runs
``alembic upgrade head`` against a fresh DB to validate them (see .github/workflows).
"""

from __future__ import annotations

import os
import re

# NullPool so each test's fresh event loop gets its own connections (see app/db.py).
os.environ.setdefault("DB_NULLPOOL", "1")

# The suite DROPS all tables on teardown, so it must NEVER run against a dev/prod
# database. Resolution order:
#   1. TEST_DATABASE_URL (explicit) — used verbatim.
#   2. else derive a "<db>_test" database from DATABASE_URL (so a stray `pytest`
#      against your dev DATABASE_URL still hits <db>_test, not the real one).
#   3. else the local default, "_test"-suffixed.
_DEFAULT = "postgresql+asyncpg://bp:bp@localhost:55432/control_plane_test"
_test_url = os.environ.get("TEST_DATABASE_URL")
if not _test_url:
    _base = os.environ.get("DATABASE_URL")
    _test_url = re.sub(r"/([^/?]+)(\?|$)", r"/\1_test\2", _base, count=1) if _base else _DEFAULT
# Point the app (settings are cached at import) at the resolved TEST database.
os.environ["DATABASE_URL"] = _test_url
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "admin")
os.environ.setdefault("PUBLIC_BASE_URL", "http://testserver")
os.environ.setdefault("CONSENT_MODE", "anonymize")
# Force jsDelivr tag output in tests regardless of a local .env ENGINE_BASE_URL
# (pydantic-settings reads .env; os.environ takes precedence).
os.environ["ENGINE_BASE_URL"] = ""

from collections.abc import AsyncGenerator  # noqa: E402

import pytest_asyncio  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Account, DemandPartner  # noqa: E402
from app.services.seed import (  # noqa: E402
    BOOTSTRAP_ACCOUNT_ID,
    BOOTSTRAP_ACCOUNT_NAME,
    DEMAND_PARTNERS,
)
from httpx import ASGITransport, AsyncClient  # noqa: E402


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[None, None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as session:
        session.add(Account(id=BOOTSTRAP_ACCOUNT_ID, name=BOOTSTRAP_ACCOUNT_NAME))
        for dp in DEMAND_PARTNERS:
            session.add(DemandPartner(**dp))
        await session.commit()
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client(db: None) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest_asyncio.fixture
async def token(client: AsyncClient) -> str:
    resp = await client.post("/auth/login", json={"username": "admin", "password": "admin"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest_asyncio.fixture
def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
