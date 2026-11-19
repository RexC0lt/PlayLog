"""SteamGridDB API v2 client — optional source for cover art (grids), icons and logos.

Requires STEAMGRIDDB_API_KEY (Bearer token from
https://www.steamgriddb.com/profile/preferences/api). All methods raise
SteamGridDbError on failure; callers treat SteamGridDB as best-effort.
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://www.steamgriddb.com/api/v2"


class SteamGridDbError(Exception):
    pass


def _ext_from(mime: str | None, url: str | None) -> str:
    """Derive a file extension from an asset's mime type or URL."""
    if mime:
        sub = mime.split("/")[-1]
        if sub == "jpeg":
            return ".jpg"
        if sub == "svg+xml":
            return ".svg"
        if sub in ("x-icon", "vnd.microsoft.icon"):
            return ".ico"
        if sub and sub.isalnum():
            return f".{sub}"
    if url:
        suffix = Path(url.split("?")[0]).suffix
        if suffix:
            return suffix.lower()
    return ".png"


def _unwrap(payload: dict, what: str) -> list[dict]:
    if not payload.get("success"):
        raise SteamGridDbError(f"{what}: {payload.get('errors') or payload}")
    data = payload.get("data")
    return data if isinstance(data, list) else []


class SteamGridDbClient:
    def __init__(self, api_key: str, client: httpx.AsyncClient | None = None):
        self.api_key = api_key
        self._client = client  # injectable for tests (httpx.MockTransport)

    async def _get(self, path: str, params: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if self._client is not None:
            resp = await self._client.get(path, params=params, headers=headers)
        else:
            async with httpx.AsyncClient(base_url=API_BASE, timeout=30.0) as client:
                resp = await client.get(path, params=params, headers=headers)
        if resp.status_code != 200:
            raise SteamGridDbError(f"SteamGridDB HTTP {resp.status_code} for {path}: {resp.text[:200]}")
        return resp.json()

    async def find_game_by_steam_appid(self, appid: str) -> dict | None:
        """Map a Steam appid to a SteamGridDB game. Returns None when not found."""
        try:
            payload = await self._get(f"/game/steam/{quote(str(appid))}")
        except SteamGridDbError:
            return None
        data = payload.get("data")
        return data if isinstance(data, dict) else None

    async def search_games(self, term: str, limit: int = 10) -> list[dict]:
        payload = await self._get(f"/search/autocomplete/{quote(term)}")
        return _unwrap(payload, "search")[:limit]

    async def get_grids(self, game_id: int) -> list[dict]:
        payload = await self._get(
            f"/grids/game/{game_id}",
            params={
                "dimensions": "600x900,342x482,512x512,460x215",
                "mimes": "image/png,image/jpeg,image/webp",
                "types": "static,animated",
                "nsfw": "false",
                "humor": "false",
                "epilepsy": "false",
            },
        )
        return _unwrap(payload, "grids")

    async def get_icons(self, game_id: int) -> list[dict]:
        # NOTE: the icons endpoint only accepts image/png and
        # image/vnd.microsoft.icon as mimes — image/webp AND image/x-icon are
        # rejected with HTTP 400 "Invalid mime type" (verified against several
        # working open-source clients).
        payload = await self._get(
            f"/icons/game/{game_id}",
            params={"mimes": "image/png,image/vnd.microsoft.icon", "types": "static"},
        )
        return _unwrap(payload, "icons")

    async def get_logos(self, game_id: int) -> list[dict]:
        # NOTE: the logos endpoint only accepts image/png and image/webp
        # (svg is rejected with HTTP 400).
        payload = await self._get(
            f"/logos/game/{game_id}",
            params={"mimes": "image/png,image/webp", "types": "static,animated"},
        )
        return _unwrap(payload, "logos")

    async def download(self, url: str, dest_dir: Path, name_hint: str, mime: str | None = None) -> str:
        """Download an asset once into dest_dir (CDN link, no auth needed)."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{name_hint}{_ext_from(mime, url)}"
        path = dest_dir / filename
        if not path.exists():
            if self._client is not None:
                resp = await self._client.get(url)
            else:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.get(url)
            if resp.status_code != 200:
                raise SteamGridDbError(f"asset download failed: HTTP {resp.status_code} for {url}")
            path.write_bytes(resp.content)
        return filename
