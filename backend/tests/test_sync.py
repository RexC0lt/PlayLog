"""Unit tests for the storefront sync pipeline with fake adapters (no network)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Game, Ownership, PlaySession, SyncStatus
from app.services.storefront_base import RecentPlay, StorefrontAdapter, StorefrontError, StoreGame
from app.services.sync_service import sync_storefront


class FakeSteamAdapter(StorefrontAdapter):
    name = "steam"
    igdb_external_category = 1

    def __init__(self, library: list[StoreGame], recent: list[RecentPlay] | None = None, fail: bool = False):
        self._library = library
        self._recent = recent or []
        self._fail = fail

    async def fetch_library(self) -> list[StoreGame]:
        if self._fail:
            raise StorefrontError("Steam API returned HTTP 403")
        return self._library

    async def fetch_recently_played(self) -> list[RecentPlay]:
        return self._recent


class FakeIgdb:
    """Duck-typed IGDB client: maps steam appids to IGDB ids, serves canned details."""

    def __init__(self, covers_dir: Path):
        self.covers_dir = covers_dir
        self.external_map = {"620": 1942, "400": 1905}
        self.details = {
            1942: {
                "id": 1942,
                "name": "Portal 2",
                "summary": "A puzzle game.",
                "first_release_date": 1_334_764_800,  # 2012-04-18
                "genres": [{"name": "Puzzle"}],
                "cover": {"image_id": "co1r7f"},
            },
            1905: {
                "id": 1905,
                "name": "Portal",
                "summary": "The original.",
                "first_release_date": 1_191_801_600,  # 2007-10-10
                "genres": [{"name": "Puzzle"}],
                "cover": {"image_id": "co1xyz"},
            },
        }

    async def find_by_external(self, category: int, uid: str):
        assert category == 1
        return self.external_map.get(uid)

    async def search_games(self, query: str, limit: int = 10):
        return [d for d in self.details.values() if query.lower() in d["name"].lower()]

    async def get_game(self, igdb_id: int):
        return self.details.get(igdb_id)

    async def download_cover(self, image_id: str, dest_dir: Path, size: str = "t_cover_big") -> str:
        dest_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{image_id}.jpg"
        (dest_dir / filename).write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
        return filename


def _game(appid_playtime: tuple[str, int], last_played_unix: int) -> StoreGame:
    return StoreGame(
        product_id=appid_playtime[0],
        title={"620": "Portal 2", "400": "Portal"}[appid_playtime[0]],
        playtime_minutes=appid_playtime[1],
        last_played_at=datetime.fromtimestamp(last_played_unix, tz=timezone.utc),
    )


async def test_sync_creates_games_ownerships_and_status(session, tmp_path):
    covers = tmp_path / "covers"
    adapter = FakeSteamAdapter(
        library=[
            _game(("620", 754), 1_700_000_000),
            _game(("400", 120), 1_690_000_000),
        ],
        recent=[RecentPlay(product_id="620", playtime_recent_minutes=60,
                           last_played_at=datetime.fromtimestamp(1_700_000_000, tz=timezone.utc))],
    )
    outcome = await sync_storefront(session, adapter, FakeIgdb(covers), covers)

    assert outcome.success and outcome.items_synced == 2 and outcome.error is None

    games = (await session.execute(select(Game).order_by(Game.title))).scalars().all()
    assert {g.title for g in games} == {"Portal", "Portal 2"}
    portal2 = next(g for g in games if g.title == "Portal 2")
    assert portal2.igdb_id == 1942
    assert portal2.description == "A puzzle game."
    assert portal2.release_year == 2012
    assert portal2.genres == "Puzzle"
    assert portal2.cover_filename == "co1r7f.jpg"
    assert (covers / "co1r7f.jpg").is_file()

    owns = (await session.execute(select(Ownership))).scalars().all()
    assert len(owns) == 2
    own620 = next(o for o in owns if o.store_product_id == "620")
    assert own620.playtime_minutes == 754
    assert own620.recent_playtime_minutes == 60
    assert own620.last_synced_at is not None

    status = await session.scalar(select(SyncStatus).where(SyncStatus.storefront == "steam"))
    assert status.success is True and status.items_synced == 2 and status.error is None


async def test_second_sync_updates_playtime_and_derives_session(session, tmp_path):
    covers = tmp_path / "covers"
    igdb = FakeIgdb(covers)
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    adapter = FakeSteamAdapter(library=[StoreGame(product_id="620", title="Portal 2", playtime_minutes=100, last_played_at=t0)])
    await sync_storefront(session, adapter, igdb, covers)

    # play 50 more minutes, last played at t1
    t1 = t0 + timedelta(days=2)
    adapter2 = FakeSteamAdapter(library=[StoreGame(product_id="620", title="Portal 2", playtime_minutes=150, last_played_at=t1)])
    outcome = await sync_storefront(session, adapter2, igdb, covers)
    assert outcome.success

    own = await session.scalar(select(Ownership).where(Ownership.store_product_id == "620"))
    assert own.playtime_minutes == 150
    assert own.last_played_at == t1

    sessions = (await session.execute(select(PlaySession))).scalars().all()
    assert len(sessions) == 1
    assert sessions[0].source == "steam"
    assert sessions[0].started_at == t0 and sessions[0].ended_at == t1


async def test_sync_failure_is_recorded_and_does_not_raise(session, tmp_path):
    adapter = FakeSteamAdapter(library=[], fail=True)
    outcome = await sync_storefront(session, adapter, None, tmp_path / "covers")
    assert outcome.success is False
    assert "403" in (outcome.error or "")

    status = await session.scalar(select(SyncStatus).where(SyncStatus.storefront == "steam"))
    assert status.success is False
    assert "403" in status.error
    # nothing else was written
    assert (await session.execute(select(Game))).scalars().all() == []


async def test_sync_works_without_igdb(session, tmp_path):
    adapter = FakeSteamAdapter(library=[StoreGame(product_id="99999", title="Some DRM-Free Game", playtime_minutes=30)])
    outcome = await sync_storefront(session, adapter, None, tmp_path / "covers")
    assert outcome.success and outcome.items_synced == 1
    game = await session.scalar(select(Game).where(Game.title == "Some DRM-Free Game"))
    assert game is not None and game.igdb_id is None and game.cover_filename is None


async def test_sync_links_storefront_game_to_existing_manual_game(session, tmp_path):
    """A manual entry whose title matches a synced title gets the ownership attached."""
    manual = Game(title="portal 2")  # normalized-equal to the steam title
    session.add(manual)
    await session.commit()

    adapter = FakeSteamAdapter(library=[StoreGame(product_id="77777", title="Portal 2", playtime_minutes=10)])
    # no IGDB available -> title match path
    outcome = await sync_storefront(session, adapter, None, tmp_path / "covers")
    assert outcome.success
    games = (await session.execute(select(Game))).scalars().all()
    assert len(games) == 1  # no duplicate
    owns = (await session.execute(select(Ownership))).scalars().all()
    assert len(owns) == 1 and owns[0].store_product_id == "77777"


async def test_recently_played_failure_is_tolerated(session, tmp_path):
    class NoRecentAdapter(FakeSteamAdapter):
        async def fetch_recently_played(self):
            raise StorefrontError("boom")

    adapter = NoRecentAdapter(library=[StoreGame(product_id="620", title="Portal 2", playtime_minutes=5)])
    outcome = await sync_storefront(session, adapter, FakeIgdb(tmp_path / "covers"), tmp_path / "covers")
    assert outcome.success and outcome.items_synced == 1
