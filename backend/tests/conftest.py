"""Shared fixtures: in-memory DB session, app instance and HTTP client.

Environment variables are set BEFORE importing the app package so that the
module-level `app = create_app()` in app.main picks up test settings.
"""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault("APP_PASSWORD", "test-password-123")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="playlog-conftest-"))

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.auth.password import ensure_password_hash
from app.config import Settings
from app.database import Base
from app.main import create_app
from app.models import seed_storefronts

TEST_PASSWORD = "test-password-123"


@pytest.fixture
async def session():
    """A standalone async session on a fresh in-memory SQLite DB."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        await seed_storefronts(db)
        await ensure_password_hash(db, TEST_PASSWORD)
        await db.commit()
        yield db
    await engine.dispose()


@pytest.fixture
async def app(tmp_path):
    settings = Settings(
        APP_PASSWORD=TEST_PASSWORD,
        DATA_DIR=str(tmp_path / "data"),
        SESSION_TTL_HOURS=1,
        SYNC_INTERVAL_HOURS=12,
    )
    application = create_app(settings, enable_scheduler=False)
    # httpx's ASGITransport does not run lifespan events, so initialise the DB manually
    async with application.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with application.state.session_factory() as db:
        await seed_storefronts(db)
        await ensure_password_hash(db, TEST_PASSWORD)
        await db.commit()
    yield application
    await application.state.engine.dispose()


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture
async def auth_client(client):
    resp = await client.post("/api/auth/login", json={"password": TEST_PASSWORD})
    assert resp.status_code == 200, resp.text
    return client
