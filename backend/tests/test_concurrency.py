"""Concurrency regression tests: SQLite 'database is locked' under parallel access.

The scheduler job and a manual POST /api/sync/steam (or an assets refresh /
game PATCH) can run at the same time. Syncs are serialized with an asyncio
lock; the engine enables WAL + busy_timeout so short concurrent writes wait
instead of failing.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.config import Settings
from app.database import Base, make_engine, make_session_factory
from app.models import Game, seed_storefronts
from app.services.storefront_base import StorefrontAdapter, StoreGame
from app.services.sync_service import sync_storefront


class FakeAdapter(StorefrontAdapter):
    name = "steam"
    igdb_external_category = 1

    def __init__(self, n: int):
        self.n = n

    async def fetch_library(self):
        return [
            StoreGame(
                product_id=str(i),
                title=f"Game {i}",
                playtime_minutes=i,
                last_played_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
            for i in range(self.n)
        ]

    async def fetch_recently_played(self):
        return []


@pytest.fixture
async def file_engine(tmp_path):
    settings = Settings(APP_PASSWORD="x", DATA_DIR=str(tmp_path))
    engine = make_engine(settings)  # applies WAL + busy_timeout pragmas
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = make_session_factory(engine)
    async with factory() as db:
        await seed_storefronts(db)
        await db.commit()
    yield engine, factory, tmp_path / "covers"
    await engine.dispose()


async def test_concurrent_syncs_are_serialized(file_engine):
    """Scheduler job + manual trigger at the same time must not corrupt or crash."""
    _engine, factory, covers = file_engine
    async with factory() as s1, factory() as s2:
        r1, r2 = await asyncio.gather(
            sync_storefront(s1, FakeAdapter(30), None, covers),
            sync_storefront(s2, FakeAdapter(30), None, covers),
        )
    assert r1.success and r2.success
    assert r1.items_synced == 30 and r2.items_synced == 30
    async with factory() as db:
        games = (await db.execute(select(Game))).scalars().all()
    assert len(games) == 30  # no duplicates from the two overlapping syncs


async def test_short_write_waits_for_long_writer(file_engine):
    """A second session's commit must wait (busy_timeout) instead of 'database is locked'."""
    _engine, factory, _covers = file_engine
    async with factory() as a, factory() as b:
        a.add(Game(title="A"))
        await a.flush()  # session A now holds the SQLite write lock, uncommitted

        async def write_b():
            b.add(Game(title="B"))
            await b.commit()  # would raise OperationalError: database is locked without busy_timeout

        task = asyncio.create_task(write_b())
        await asyncio.sleep(0.2)
        await a.commit()
        await asyncio.wait_for(task, timeout=10)

    async with factory() as db:
        titles = {g.title for g in (await db.execute(select(Game))).scalars().all()}
    assert {"A", "B"} <= titles
