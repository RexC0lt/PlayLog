"""Fetch cover/icon/logo assets for a game from SteamGridDB into the local cache.

Never raises — SteamGridDB is best-effort enrichment on top of IGDB metadata.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..models import Game
from .steamgriddb import SteamGridDbClient, SteamGridDbError

logger = logging.getLogger(__name__)


def _pick(assets: list[dict], prefer_dims: tuple[str, ...] = ()) -> dict | None:
    """Pick the best asset: preferred dimensions first, then highest score."""
    if not assets:
        return None

    def key(a: dict):
        dims = f"{a.get('width')}x{a.get('height')}"
        dim_rank = prefer_dims.index(dims) if dims in prefer_dims else len(prefer_dims)
        return (dim_rank, -(a.get("score") or 0))

    return sorted(assets, key=key)[0]


async def _fetch_one(
    game: Game,
    attr: str,
    fetch_assets,
    download,
    covers_dir: Path,
    kind: str,
    overwrite: bool,
    result: dict,
) -> None:
    try:
        assets = await fetch_assets()
        best = _pick(assets, prefer_dims=("600x900", "342x482") if kind == "grid" else ())
        if best is None:
            return
        if not overwrite and getattr(game, attr):
            return
        filename = await download(best["url"], covers_dir, f"sgdb_{kind}_{best['id']}", best.get("mime"))
        setattr(game, attr, filename)
        result[kind] = filename
    except SteamGridDbError as exc:
        logger.warning("SteamGridDB %s fetch failed for %r: %s", kind, game.title, exc)


async def fetch_game_assets(
    game: Game,
    sgdb: SteamGridDbClient,
    covers_dir: Path,
    steam_appid: str | None = None,
    overwrite: bool = False,
) -> dict:
    """Fill game.cover_filename / icon_filename / logo_filename from SteamGridDB.

    Matches by Steam appid when known, otherwise by title search. With
    overwrite=False only missing assets are filled (used during sync/add);
    overwrite=True replaces them (explicit user "refresh art" action).
    """
    result = {"grid": None, "icon": None, "logo": None}
    try:
        sgdb_game = None
        if steam_appid:
            sgdb_game = await sgdb.find_game_by_steam_appid(steam_appid)
        if sgdb_game is None and game.title:
            matches = await sgdb.search_games(game.title, limit=5)
            sgdb_game = matches[0] if matches else None
        if sgdb_game is None:
            logger.info("SteamGridDB: no game match for %r", game.title)
            return result
        gid = int(sgdb_game["id"])
        await _fetch_one(game, "cover_filename", lambda: sgdb.get_grids(gid), sgdb.download, covers_dir, "grid", overwrite, result)
        await _fetch_one(game, "icon_filename", lambda: sgdb.get_icons(gid), sgdb.download, covers_dir, "icon", overwrite, result)
        await _fetch_one(game, "logo_filename", lambda: sgdb.get_logos(gid), sgdb.download, covers_dir, "logo", overwrite, result)
    except Exception as exc:  # noqa: BLE001 - asset fetching must never break anything
        logger.warning("SteamGridDB asset fetch failed for %r: %s", game.title, exc)
    return result
