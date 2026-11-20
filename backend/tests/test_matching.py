"""Unit tests for the pure matching/parsing logic."""

from __future__ import annotations

import httpx

from app.services.matching import normalize_title, pick_best_igdb_match, title_similarity
from app.services.steam import (
    SteamAdapter,
    parse_owned_games,
    parse_recently_played,
    parse_store_appdetails,
)
from app.services.storefront_base import StorefrontError


class TestNormalizeTitle:
    def test_lowercase_and_punctuation(self):
        assert normalize_title("Hades II™") == "hades ii"
        assert normalize_title("  Hollow  Knight: Silksong! ") == "hollow knight silksong"

    def test_accents_removed(self):
        assert normalize_title("Pokémon Legends: Z-A") == "pokemon legends z a"

    def test_empty(self):
        assert normalize_title("") == ""
        assert normalize_title(None) == ""


class TestSimilarity:
    def test_identical(self):
        assert title_similarity("Portal 2", "portal 2") == 1.0

    def test_different(self):
        assert title_similarity("Portal 2", "Doom Eternal") < 0.5


class TestPickBestIgdbMatch:
    CANDIDATES = [
        {"id": 1, "name": "Hades"},
        {"id": 2, "name": "Hades II"},
        {"id": 3, "name": "Something Unrelated"},
    ]

    def test_exact_match_wins(self):
        assert pick_best_igdb_match("Hades", self.CANDIDATES)["id"] == 1

    def test_fuzzy_match(self):
        match = pick_best_igdb_match("Hadez II", self.CANDIDATES)  # typo'd query
        assert match is not None and match["id"] == 2

    def test_no_match_below_threshold(self):
        assert pick_best_igdb_match("Completely Different Game", self.CANDIDATES) is None

    def test_empty_candidates(self):
        assert pick_best_igdb_match("Hades", []) is None


class TestSteamParsing:
    def test_parse_owned_games(self):
        payload = {
            "game_count": 2,
            "games": [
                {"appid": 620, "name": "Portal 2", "playtime_forever": 754, "rtime_last_played": 1_700_000_000},
                {"appid": 400, "name": "Portal", "playtime_forever": 0, "rtime_last_played": 0},
            ],
        }
        games = parse_owned_games(payload)
        assert len(games) == 2
        assert games[0].product_id == "620"
        assert games[0].title == "Portal 2"
        assert games[0].playtime_minutes == 754
        assert games[0].last_played_at is not None
        assert games[1].last_played_at is None

    def test_parse_owned_games_private_profile(self):
        # Steam returns {"response": {}} (no "games" key) for private profiles
        try:
            parse_owned_games({})
        except StorefrontError as exc:
            assert "Public" in str(exc)
        else:
            raise AssertionError("expected StorefrontError")

    def test_parse_recently_played(self):
        payload = {
            "total_count": 1,
            "games": [
                {"appid": 620, "name": "Portal 2", "playtime_2weeks": 120, "rtime_last_played": 1_700_000_000}
            ],
        }
        recent = parse_recently_played(payload)
        assert recent[0].product_id == "620"
        assert recent[0].playtime_recent_minutes == 120


class TestSteamStoreGenres:
    def test_parse_store_appdetails(self):
        payload = {
            "620": {
                "success": True,
                "data": {"genres": [{"id": "3", "description": "Puzzle"}, {"id": "2", "description": "Shooter"}]},
            }
        }
        assert parse_store_appdetails(payload, "620") == ["Puzzle", "Shooter"]
        # unsuccessful / missing entries yield no genres
        assert parse_store_appdetails({"620": {"success": False}}, "620") == []
        assert parse_store_appdetails({}, "620") == []

    async def test_fetch_store_genres_http(self):
        def handler(request: httpx.Request) -> httpx.Response:
            # store API is keyless — no Authorization header
            assert "Authorization" not in request.headers
            assert request.url.host == "store.steampowered.com"
            assert request.url.params["appids"] == "620"
            return httpx.Response(
                200,
                json={
                    "620": {
                        "success": True,
                        "data": {"genres": [{"id": "3", "description": "Puzzle"}]},
                    }
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        adapter = SteamAdapter("KEY", "7656119", client=client)
        assert await adapter.fetch_store_genres("620") == ["Puzzle"]

    async def test_fetch_store_genres_failure_returns_empty(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text="rate limited")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        adapter = SteamAdapter("KEY", "7656119", client=client)
        assert await adapter.fetch_store_genres("620") == []
