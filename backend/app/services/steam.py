"""Steam Web API adapter (IPlayerService).

Requires STEAM_API_KEY and STEAM_ID64. The Steam profile's "Game Details" privacy
setting must be Public, otherwise GetOwnedGames returns an empty response.
See README.md.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from .storefront_base import RecentPlay, StorefrontAdapter, StorefrontError, StoreGame

STEAM_API_BASE = "https://api.steampowered.com"
#: IGDB external_game_category id for Steam appids
STEAM_IGDB_CATEGORY = 1


def _ts(unix_seconds: int | None) -> datetime | None:
    if not unix_seconds:
        return None
    return datetime.fromtimestamp(int(unix_seconds), tz=timezone.utc)


def parse_owned_games(response: dict) -> list[StoreGame]:
    """Parse the `response` object of IPlayerService/GetOwnedGames."""
    games = response.get("games")
    if games is None:
        raise StorefrontError(
            "Steam returned no game list. Make sure the profile and its 'Game Details' "
            "are set to Public (see README)."
        )
    out: list[StoreGame] = []
    for g in games:
        out.append(
            StoreGame(
                product_id=str(g.get("appid", "")),
                title=str(g.get("name", "")).strip(),
                playtime_minutes=int(g.get("playtime_forever", 0) or 0),
                last_played_at=_ts(g.get("rtime_last_played")),
            )
        )
    return [g for g in out if g.product_id and g.title]


def parse_recently_played(response: dict) -> list[RecentPlay]:
    """Parse the `response` object of IPlayerService/GetRecentlyPlayedGames."""
    games = response.get("games")
    if games is None:
        raise StorefrontError("Steam returned no recently-played list (profile may be private).")
    out: list[RecentPlay] = []
    for g in games:
        out.append(
            RecentPlay(
                product_id=str(g.get("appid", "")),
                playtime_recent_minutes=int(g.get("playtime_2weeks", 0) or 0),
                last_played_at=_ts(g.get("rtime_last_played")),
            )
        )
    return [r for r in out if r.product_id]


class SteamAdapter(StorefrontAdapter):
    """Fetches the owned-games and recently-played lists from the Steam Web API."""

    name = "steam"
    igdb_external_category = STEAM_IGDB_CATEGORY

    def __init__(self, api_key: str, steam_id64: str, client: httpx.AsyncClient | None = None):
        self.api_key = api_key
        self.steam_id64 = steam_id64
        self._client = client  # injectable for tests (e.g. httpx.MockTransport)

    async def _request(self, path: str, params: dict) -> dict:
        if self._client is not None:
            response = await self._client.get(path, params=params)
        else:
            async with httpx.AsyncClient(base_url=STEAM_API_BASE, timeout=30.0) as client:
                response = await client.get(path, params=params)
        if response.status_code != 200:
            raise StorefrontError(f"Steam API returned HTTP {response.status_code} for {path}")
        try:
            data = response.json()
        except ValueError as exc:
            raise StorefrontError(f"Steam API returned invalid JSON for {path}") from exc
        return data.get("response") or {}

    async def fetch_library(self) -> list[StoreGame]:
        response = await self._request(
            "/IPlayerService/GetOwnedGames/v1/",
            {
                "key": self.api_key,
                "steamid": self.steam_id64,
                "include_appinfo": "1",
                "include_played_free_games": "1",
                "format": "json",
            },
        )
        return parse_owned_games(response)

    async def fetch_recently_played(self) -> list[RecentPlay]:
        response = await self._request(
            "/IPlayerService/GetRecentlyPlayedGames/v1/",
            {"key": self.api_key, "steamid": self.steam_id64, "format": "json"},
        )
        return parse_recently_played(response)
