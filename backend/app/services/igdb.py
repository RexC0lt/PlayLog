"""IGDB API client (OAuth client-credentials flow) + cover downloads.

Used for metadata (description, genres, release year) and cover art. Covers are
downloaded once into the local covers directory; the app never proxies remote
images per request afterwards.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
API_BASE = "https://api.igdb.com/v4"
IMAGE_BASE = "https://images.igdb.com/igdb/image/upload"

GAME_FIELDS = (
    "fields name, summary, storyline, first_release_date, rating, cover.image_id, "
    "genres.name, external_games;"
)


class IgdbError(Exception):
    """Raised on any IGDB failure; callers must treat IGDB as best-effort."""


def release_year_from(first_release_date: int | None) -> int | None:
    if not first_release_date:
        return None
    import datetime as _dt

    return _dt.datetime.fromtimestamp(first_release_date, tz=_dt.timezone.utc).year


def game_fields(detail: dict) -> dict:
    """Normalize an IGDB game object into plain fields for our Game model."""
    cover = detail.get("cover") or {}
    genres = [g.get("name") for g in (detail.get("genres") or []) if g.get("name")]
    return {
        "title": detail.get("name"),
        "description": detail.get("summary") or detail.get("storyline"),
        "genres": genres,
        "release_year": release_year_from(detail.get("first_release_date")),
        "image_id": cover.get("image_id"),
    }


def cover_url(image_id: str, size: str = "t_cover_big") -> str:
    return f"{IMAGE_BASE}/{size}/{image_id}.jpg"


class IgdbClient:
    def __init__(self, client_id: str, client_secret: str, client: httpx.AsyncClient | None = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self._client = client  # injectable for tests
        self._token: str | None = None
        self._token_exp: float = 0.0

    async def _http(self) -> httpx.AsyncClient:
        return self._client if self._client is not None else httpx.AsyncClient(timeout=30.0)

    async def _ensure_token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        client = await self._http()
        resp = await client.post(
            TOKEN_URL,
            params={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            },
        )
        if resp.status_code != 200:
            raise IgdbError(f"IGDB token request failed: HTTP {resp.status_code}")
        data = resp.json()
        self._token = data["access_token"]
        self._token_exp = time.time() + int(data.get("expires_in", 3600))
        return self._token

    async def _api(self, endpoint: str, query: str) -> list[dict]:
        token = await self._ensure_token()
        client = await self._http()
        resp = await client.post(
            f"{API_BASE}/{endpoint}",
            headers={
                "Client-ID": self.client_id,
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            content=query.encode("utf-8"),
        )
        if resp.status_code != 200:
            raise IgdbError(f"IGDB {endpoint} failed: HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    @staticmethod
    def _escape(text: str) -> str:
        return text.replace("\\", " ").replace('"', " ").strip()

    async def search_games(self, query: str, limit: int = 10) -> list[dict]:
        q = (
            f'search "{self._escape(query)}"; '
            f"{GAME_FIELDS} limit {limit};"
        )
        return await self._api("games", q)

    async def get_game(self, igdb_id: int) -> dict | None:
        q = f"{GAME_FIELDS} where id = {int(igdb_id)}; limit 1;"
        results = await self._api("games", q)
        return results[0] if results else None

    async def find_by_external(self, category: int, uid: str) -> int | None:
        """Map a storefront product id to an IGDB game id via the external_games endpoint."""
        q = (
            f'fields game, uid, external_game_category; '
            f'where external_game_category = {int(category)} & uid = "{self._escape(uid)}"; '
            f"limit 1;"
        )
        results = await self._api("external_games", q)
        if results:
            return int(results[0]["game"])
        return None

    async def download_cover(self, image_id: str, dest_dir: Path, size: str = "t_cover_big") -> str:
        """Download a cover image once into dest_dir; returns the local filename."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{image_id}.jpg"
        path = dest_dir / filename
        if path.exists():
            return filename
        client = await self._http()
        resp = await client.get(cover_url(image_id, size))
        if resp.status_code != 200:
            raise IgdbError(f"Cover download failed for {image_id}: HTTP {resp.status_code}")
        path.write_bytes(resp.content)
        return filename
