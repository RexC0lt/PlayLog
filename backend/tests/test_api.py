"""API integration tests: auth, manual games, mocked Steam sync, mocked IGDB.

Steam/IGDB are mocked at two levels:
- HTTP level with httpx.MockTransport for the adapter parsing (test_steam_adapter_http),
- dependency level with fake adapters for the API endpoints.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.config import Settings
from app.database import Base
from app.deps import get_igdb_client, get_steam_adapter
from app.main import create_app
from app.models import Game
from app.services.steam import SteamAdapter
from app.services.storefront_base import RecentPlay, StorefrontAdapter, StoreGame
from tests.conftest import TEST_PASSWORD


# ---------------------------------------------------------------- auth


async def test_api_requires_auth(client):
    assert (await client.get("/api/games")).status_code == 401
    assert (await client.get("/api/sync/status")).status_code == 401
    assert (await client.get("/api/recently-played")).status_code == 401
    assert (await client.post("/api/sync/steam")).status_code == 401


async def test_login_wrong_password(client):
    resp = await client.post("/api/auth/login", json={"password": "nope"})
    assert resp.status_code == 401


async def test_login_ok_and_me(auth_client):
    resp = await auth_client.get("/api/auth/me")
    assert resp.status_code == 200 and resp.json()["authenticated"] is True
    # cookie was set
    assert "playlog_session" in auth_client.cookies


async def test_bearer_token_works(client):
    resp = await client.post("/api/auth/login", json={"password": TEST_PASSWORD})
    token = resp.json()["access_token"]
    resp = await client.get("/api/games", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


# ------------------------------------------------------- manual games


async def test_manual_game_crud(auth_client):
    resp = await auth_client.post(
        "/api/games",
        json={"title": "Chrono Trigger", "status": "in_progress", "rating": 9, "tags": ["jrpg", "retro"]},
    )
    assert resp.status_code == 201, resp.text
    game = resp.json()
    assert game["title"] == "Chrono Trigger"
    assert game["status"] == "in_progress"
    assert game["rating"] == 9
    assert sorted(game["tags"]) == ["jrpg", "retro"]
    assert game["ownerships"][0]["storefront"] == "manual"
    assert game["cover_url"] is None

    resp = await auth_client.patch(
        f"/api/games/{game['id']}", json={"status": "completed", "notes": "best ending"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"
    assert resp.json()["notes"] == "best ending"
    assert resp.json()["rating"] == 9  # untouched fields preserved

    resp = await auth_client.get("/api/games", params={"search": "chrono"})
    assert [g["title"] for g in resp.json()] == ["Chrono Trigger"]
    resp = await auth_client.get("/api/games", params={"status": "completed"})
    assert len(resp.json()) == 1
    resp = await auth_client.get("/api/games", params={"status": "unplayed"})
    assert resp.json() == []
    resp = await auth_client.get("/api/games", params={"tag": "jrpg"})
    assert len(resp.json()) == 1
    resp = await auth_client.get("/api/games", params={"storefront": "manual"})
    assert len(resp.json()) == 1

    resp = await auth_client.get(f"/api/games/{game['id']}")
    assert resp.status_code == 200 and resp.json()["id"] == game["id"]
    assert (await auth_client.get(f"/api/games/{game['id']}/cover")).status_code == 404


async def test_manual_session(auth_client):
    game = (await auth_client.post("/api/games", json={"title": "Retro Gem"})).json()
    started = datetime(2024, 5, 1, 20, 0, tzinfo=timezone.utc)
    ended = datetime(2024, 5, 1, 21, 30, tzinfo=timezone.utc)
    resp = await auth_client.post(
        f"/api/games/{game['id']}/sessions",
        json={"started_at": started.isoformat(), "ended_at": ended.isoformat()},
    )
    assert resp.status_code == 201 and resp.json()["source"] == "manual"
    game = (await auth_client.get(f"/api/games/{game['id']}")).json()
    assert game["total_playtime_minutes"] == 90
    sessions = (await auth_client.get(f"/api/games/{game['id']}/sessions")).json()
    assert len(sessions) == 1

    bad = await auth_client.post(
        f"/api/games/{game['id']}/sessions",
        json={"started_at": ended.isoformat(), "ended_at": started.isoformat()},
    )
    assert bad.status_code == 400


# ------------------------------------------- mocked Steam/IGDB sync


class FakeSteamAdapter(StorefrontAdapter):
    name = "steam"
    igdb_external_category = 1

    async def fetch_library(self):
        return [
            StoreGame(
                product_id="620",
                title="Portal 2",
                playtime_minutes=754,
                last_played_at=datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc),
            )
        ]

    async def fetch_recently_played(self):
        return [
            RecentPlay(
                product_id="620",
                playtime_recent_minutes=120,
                last_played_at=datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc),
            )
        ]


class FakeIgdb:
    async def find_by_external(self, category, uid):
        return 1942 if uid == "620" else None

    async def search_games(self, query, limit=10):
        return []

    async def get_game(self, igdb_id):
        return {
            "id": 1942,
            "name": "Portal 2",
            "summary": "The sequel to the puzzle classic.",
            "first_release_date": 1_334_764_800,
            "genres": [{"name": "Puzzle"}, {"name": "Shooter"}],
            "cover": {"image_id": "co1r7f"},
        }

    async def download_cover(self, image_id, dest_dir, size="t_cover_big"):
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / f"{image_id}.jpg").write_bytes(b"\xff\xd8\xff\xe0jpeg-bytes")
        return f"{image_id}.jpg"


@pytest.fixture
async def synced_app(app):
    app.dependency_overrides[get_steam_adapter] = lambda: FakeSteamAdapter()
    app.dependency_overrides[get_igdb_client] = lambda: FakeIgdb()
    return app


async def test_steam_sync_via_api(synced_app, tmp_path):
    transport = httpx.ASGITransport(app=synced_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post("/api/auth/login", json={"password": TEST_PASSWORD})

        resp = await client.post("/api/sync/steam")
        assert resp.status_code == 200, resp.text
        status = resp.json()
        assert status["storefront"] == "steam" and status["success"] is True
        assert status["items_synced"] == 1

        statuses = (await client.get("/api/sync/status")).json()
        steam = next(s for s in statuses if s["storefront"] == "steam")
        assert steam["success"] is True and steam["last_run_at"] is not None
        # all seeded storefronts are listed, even ones never synced
        assert {s["storefront"] for s in statuses} == {"steam", "epic", "gog", "manual"}

        games = (await client.get("/api/games", params={"storefront": "steam"})).json()
        assert len(games) == 1
        game = games[0]
        assert game["title"] == "Portal 2"
        assert game["igdb_id"] == 1942
        assert game["description"] == "The sequel to the puzzle classic."
        assert game["release_year"] == 2012
        assert sorted(game["genres"]) == ["Puzzle", "Shooter"]
        assert game["total_playtime_minutes"] == 754
        assert game["ownerships"][0]["storefront"] == "steam"
        assert game["ownerships"][0]["recent_playtime_minutes"] == 120

        # cover is served from the local cache
        cover = await client.get(f"/api/games/{game['id']}/cover")
        assert cover.status_code == 200 and cover.content == b"\xff\xd8\xff\xe0jpeg-bytes"

        recent = (await client.get("/api/recently-played")).json()
        assert len(recent) == 1 and recent[0]["title"] == "Portal 2"
        assert recent[0]["recent_playtime_minutes"] == 120


async def test_steam_sync_not_configured(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post("/api/auth/login", json={"password": TEST_PASSWORD})
        resp = await client.post("/api/sync/steam")
        assert resp.status_code == 400
        assert "STEAM_API_KEY" in resp.json()["detail"]


async def test_failed_steam_sync_reported_not_crashing(synced_app):
    class BrokenAdapter(FakeSteamAdapter):
        async def fetch_library(self):
            raise RuntimeError("connection reset")

    synced_app.dependency_overrides[get_steam_adapter] = lambda: BrokenAdapter()
    transport = httpx.ASGITransport(app=synced_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post("/api/auth/login", json={"password": TEST_PASSWORD})
        resp = await client.post("/api/sync/steam")
        assert resp.status_code == 200  # API still answers
        assert resp.json()["success"] is False
        assert "connection reset" in resp.json()["error"]
        # status endpoint reflects the failure
        statuses = (await client.get("/api/sync/status")).json()
        steam = next(s for s in statuses if s["storefront"] == "steam")
        assert steam["success"] is False and "connection reset" in steam["error"]


async def test_igdb_search_and_manual_add_with_igdb(synced_app):
    transport = httpx.ASGITransport(app=synced_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post("/api/auth/login", json={"password": TEST_PASSWORD})

        class SearchIgdb(FakeIgdb):
            async def search_games(self, query, limit=10):
                return [
                    {
                        "id": 1942,
                        "name": "Portal 2",
                        "summary": "The sequel.",
                        "first_release_date": 1_334_764_800,
                        "genres": [{"name": "Puzzle"}],
                        "cover": {"image_id": "co1r7f"},
                    }
                ]

        synced_app.dependency_overrides[get_igdb_client] = lambda: SearchIgdb()
        results = (await client.get("/api/igdb/search", params={"q": "portal"})).json()
        assert results[0]["igdb_id"] == 1942
        assert results[0]["title"] == "Portal 2"
        assert results[0]["release_year"] == 2012
        assert results[0]["cover_url"].endswith("co1r7f.jpg")

        game = (
            await client.post("/api/games", json={"title": "Portal 2", "igdb_id": 1942})
        ).json()
        assert game["igdb_id"] == 1942
        assert game["description"] == "The sequel to the puzzle classic."
        assert game["cover_url"] == f"/api/games/{game['id']}/cover"
        cover = await client.get(f"/api/games/{game['id']}/cover")
        assert cover.status_code == 200


async def test_steam_adapter_http_parsing():
    """SteamAdapter against a mocked HTTP transport (canned Steam JSON)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "GetOwnedGames" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "response": {
                        "game_count": 1,
                        "games": [
                            {
                                "appid": 620,
                                "name": "Portal 2",
                                "playtime_forever": 754,
                                "rtime_last_played": 1_700_000_000,
                            }
                        ],
                    }
                },
            )
        return httpx.Response(200, json={"response": {"games": []}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.steampowered.com")
    adapter = SteamAdapter("KEY", "7656119", client=client)
    games = await adapter.fetch_library()
    assert games[0].product_id == "620" and games[0].playtime_minutes == 754


async def test_data_persists_across_restarts(tmp_path):
    """A second app instance on the same DATA_DIR sees the first instance's data."""
    data_dir = tmp_path / "data"

    settings1 = Settings(APP_PASSWORD=TEST_PASSWORD, DATA_DIR=str(data_dir))
    app1 = create_app(settings1, enable_scheduler=False)
    async with app1.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with app1.state.session_factory() as db:
        from app.models import seed_storefronts
        from app.auth.password import ensure_password_hash

        await seed_storefronts(db)
        await ensure_password_hash(db, TEST_PASSWORD)
        db.add(Game(title="Persisted Game"))
        await db.commit()
    await app1.state.engine.dispose()

    settings2 = Settings(APP_PASSWORD=TEST_PASSWORD, DATA_DIR=str(data_dir))
    app2 = create_app(settings2, enable_scheduler=False)
    async with app2.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with app2.state.session_factory() as db:
        rows = (await db.execute(select(Game))).scalars().all()
        assert [g.title for g in rows] == ["Persisted Game"]
    await app2.state.engine.dispose()
