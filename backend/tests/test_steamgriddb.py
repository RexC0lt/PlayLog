"""Unit tests for the SteamGridDB client (mocked HTTP, no network)."""

from __future__ import annotations

import httpx
import pytest

from app.services.steamgriddb import SteamGridDbClient, SteamGridDbError, _ext_from

API = "https://www.steamgriddb.com/api/v2"


def make_client(handler) -> SteamGridDbClient:
    return SteamGridDbClient(
        "TEST-KEY",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=API),
    )


def rich_handler(request: httpx.Request) -> httpx.Response:
    host, path = request.url.host, request.url.path
    if host == "cdn2.steamgriddb.com":  # CDN downloads carry no auth header
        assert "Authorization" not in request.headers
        return httpx.Response(200, content=b"img-bytes")
    assert request.headers["Authorization"] == "Bearer TEST-KEY"
    mimes = request.url.params.get("mimes", "")
    if "/icons/" in path:
        # regression guard: icons reject image/webp and image/x-icon with
        # HTTP 400 "Invalid mime type"; only png + vnd.microsoft.icon are valid
        assert set(mimes.split(",")) == {"image/png", "image/vnd.microsoft.icon"}, mimes
    if "/logos/" in path:
        # regression guard: logos reject image/svg+xml with HTTP 400
        assert "svg" not in mimes and set(mimes.split(",")) <= {"image/png", "image/webp"}, mimes
    if path.endswith("/search/autocomplete/portal"):
        return httpx.Response(200, json={"success": True, "data": [{"id": 123, "name": "Portal 2"}]})
    if path.endswith("/game/steam/620"):
        return httpx.Response(200, json={"success": True, "data": {"id": 123, "name": "Portal 2"}})
    if "/grids/game/123" in path:
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": [
                    {"id": 1, "score": 5, "width": 342, "height": 482, "mime": "image/jpeg", "url": "https://cdn2.steamgriddb.com/grid/a.jpg"},
                    {"id": 2, "score": 9, "width": 600, "height": 900, "mime": "image/png", "url": "https://cdn2.steamgriddb.com/grid/b.png"},
                ],
            },
        )
    if "/icons/game/123" in path:
        return httpx.Response(
            200,
            json={"success": True, "data": [{"id": 7, "score": 3, "mime": "image/png", "url": "https://cdn2.steamgriddb.com/icon/c.png"}]},
        )
    if "/logos/game/123" in path:
        return httpx.Response(
            200,
            json={"success": True, "data": [{"id": 8, "score": 2, "mime": "image/svg+xml", "url": "https://cdn2.steamgriddb.com/logo/d.svg"}]},
        )
    return httpx.Response(404, json={"success": False, "errors": ["not found"]})


async def test_search_lookup_assets_and_download(tmp_path):
    client = make_client(rich_handler)

    matches = await client.search_games("portal")
    assert matches[0]["id"] == 123

    game = await client.find_game_by_steam_appid("620")
    assert game["id"] == 123

    grids = await client.get_grids(123)
    assert len(grids) == 2
    icons = await client.get_icons(123)
    assert icons[0]["id"] == 7
    logos = await client.get_logos(123)
    assert logos[0]["mime"] == "image/svg+xml"

    fn = await client.download(grids[1]["url"], tmp_path, "sgdb_grid_2", grids[1]["mime"])
    assert fn == "sgdb_grid_2.png"
    assert (tmp_path / fn).read_bytes() == b"img-bytes"
    # second call uses the cache, no HTTP
    assert await client.download(grids[1]["url"], tmp_path, "sgdb_grid_2", grids[1]["mime"]) == fn


async def test_unknown_steam_appid_returns_none():
    client = make_client(rich_handler)  # everything 404s except known paths
    assert await client.find_game_by_steam_appid("999999") is None


async def test_http_error_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"success": False, "errors": ["boom"]})

    client = make_client(handler)
    with pytest.raises(SteamGridDbError):
        await client.get_grids(1)


def test_ext_from():
    assert _ext_from("image/jpeg", None) == ".jpg"
    assert _ext_from("image/svg+xml", None) == ".svg"
    assert _ext_from("image/x-icon", None) == ".ico"
    assert _ext_from("image/vnd.microsoft.icon", None) == ".ico"
    assert _ext_from(None, "https://cdn/x/y.webp?dl=1") == ".webp"
    assert _ext_from(None, None) == ".png"
