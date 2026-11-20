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
from app.database import Base, migrate
from app.deps import get_igdb_client, get_sgdb_client, get_steam_adapter
from app.main import create_app
from app.models import Game, Ownership, get_or_create_storefront
from app.services.steam import SteamAdapter
from app.services.storefront_base import RecentPlay, StorefrontAdapter, StoreGame
from tests.conftest import TEST_PASSWORD


# ---------------------------------------------------------------- auth


async def test_health_endpoint_is_public(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200 and resp.json() == {"status": "ok"}


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


async def test_meta_endpoint_reports_configured_integrations(auth_client):
    meta = (await auth_client.get("/api/meta")).json()
    assert meta == {
        "steam_configured": False,
        "igdb_configured": False,
        "steamgriddb_configured": False,
    }


class FakeSgdb:
    """Duck-typed SteamGridDB client for the assets-refresh test."""

    async def find_game_by_steam_appid(self, appid):
        return {"id": 55, "name": "Portal 2"} if appid == "620" else None

    async def search_games(self, term, limit=5):
        return [{"id": 55, "name": "Portal 2"}]

    async def get_grids(self, gid):
        return [{"id": 1, "score": 9, "width": 600, "height": 900, "mime": "image/png", "url": "https://cdn/x.png"}]

    async def get_icons(self, gid):
        return [{"id": 2, "score": 5, "mime": "image/png", "url": "https://cdn/i.png"}]

    async def get_logos(self, gid):
        return [{"id": 3, "score": 5, "mime": "image/png", "url": "https://cdn/l.png"}]

    async def download(self, url, dest_dir, hint, mime=None):
        Path(dest_dir).mkdir(parents=True, exist_ok=True)
        fn = f"{hint}.png"
        (Path(dest_dir) / fn).write_bytes(b"asset-bytes")
        return fn


async def test_assets_refresh_requires_sgdb(auth_client):
    game = (await auth_client.post("/api/games", json={"title": "Portal 2"})).json()
    resp = await auth_client.post(f"/api/games/{game['id']}/assets/refresh")
    assert resp.status_code == 400
    assert "STEAMGRIDDB_API_KEY" in resp.json()["detail"]


async def test_assets_refresh_fetches_and_serves(app, auth_client):
    # create a game and give it a steam ownership so refresh matches by appid
    game = (await auth_client.post("/api/games", json={"title": "Portal 2"})).json()
    gid = game["id"]
    async with app.state.session_factory() as db:
        sf = await get_or_create_storefront(db, "steam")
        db.add(Ownership(game_id=gid, storefront_id=sf.id, store_product_id="620"))
        await db.commit()

    app.dependency_overrides[get_sgdb_client] = lambda: FakeSgdb()
    try:
        resp = await auth_client.post(f"/api/games/{gid}/assets/refresh")
        assert resp.status_code == 200, resp.text
        g = resp.json()
        assert g["cover_url"] == f"/api/games/{gid}/cover"
        assert g["icon_url"] == f"/api/games/{gid}/icon"
        assert g["logo_url"] == f"/api/games/{gid}/logo"
        assert (await auth_client.get(f"/api/games/{gid}/cover")).content == b"asset-bytes"
        assert (await auth_client.get(f"/api/games/{gid}/icon")).status_code == 200
        assert (await auth_client.get(f"/api/games/{gid}/logo")).status_code == 200
    finally:
        app.dependency_overrides.clear()


async def test_icon_logo_404_without_assets(auth_client):
    game = (await auth_client.post("/api/games", json={"title": "Bare Game"})).json()
    assert (await auth_client.get(f"/api/games/{game['id']}/icon")).status_code == 404
    assert (await auth_client.get(f"/api/games/{game['id']}/logo")).status_code == 404


async def test_migrate_adds_asset_columns_to_existing_db():
    """Simulate a DB created before icon_filename/logo_filename existed."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE games (id INTEGER PRIMARY KEY, title VARCHAR(300), igdb_id INTEGER, "
                "description TEXT, cover_filename VARCHAR(200), release_year INTEGER, genres VARCHAR(500), "
                "status VARCHAR(20), notes TEXT, rating INTEGER, tags VARCHAR(500), created_at DATETIME)"
            )
        )
    await migrate(engine)
    async with engine.connect() as conn:
        cols = {r[1] for r in (await conn.execute(text("PRAGMA table_info(games)"))).all()}
    assert {"icon_filename", "logo_filename"} <= cols
    await engine.dispose()


async def test_manual_title_edit(auth_client):
    game = (await auth_client.post("/api/games", json={"title": "Old Name"})).json()
    resp = await auth_client.patch(f"/api/games/{game['id']}", json={"title": "New Name"})
    assert resp.status_code == 200 and resp.json()["title"] == "New Name"
    listing = await auth_client.get("/api/games", params={"search": "new name"})
    assert [g["title"] for g in listing.json()] == ["New Name"]


async def test_manual_asset_upload_and_delete(auth_client):
    game = (await auth_client.post("/api/games", json={"title": "Art Game"})).json()
    gid = game["id"]

    # upload a custom cover (raw body, image content-type)
    png = b"\x89PNG\r\n\x1a\n" + b"fake-png"
    resp = await auth_client.put(
        f"/api/games/{gid}/assets/cover", content=png, headers={"Content-Type": "image/png"}
    )
    assert resp.status_code == 200, resp.text
    g = resp.json()
    assert g["cover_filename"].startswith(f"manual_cover_{gid}")
    assert g["cover_url"] == f"/api/games/{gid}/cover"
    served = await auth_client.get(f"/api/games/{gid}/cover")
    assert served.status_code == 200 and served.content == png

    # upload icon + logo too
    for kind, ctype in (("icon", "image/x-icon"), ("logo", "image/svg+xml")):
        r = await auth_client.put(f"/api/games/{gid}/assets/{kind}", content=b"x", headers={"Content-Type": ctype})
        assert r.status_code == 200 and r.json()[f"{kind}_url"] == f"/api/games/{gid}/{kind}"

    # bad content type -> 415; bad kind -> 400
    assert (await auth_client.put(f"/api/games/{gid}/assets/cover", content=b"x", headers={"Content-Type": "text/plain"})).status_code == 415
    assert (await auth_client.put(f"/api/games/{gid}/assets/banner", content=b"x", headers={"Content-Type": "image/png"})).status_code == 400

    # delete clears the field and the file; cover then 404s
    r = await auth_client.delete(f"/api/games/{gid}/assets/cover")
    assert r.status_code == 200 and r.json()["cover_url"] is None
    assert (await auth_client.get(f"/api/games/{gid}/cover")).status_code == 404


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
