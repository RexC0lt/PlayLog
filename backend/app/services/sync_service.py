"""Storefront sync orchestration.

Generic over any `StorefrontAdapter`: fetch the library, resolve each title to a
Game (by store product id -> IGDB external id -> IGDB title search -> normalized
title match against existing games), upsert ownerships with authoritative
playtime, derive play sessions from observed playtime deltas, and record a
per-storefront sync status. A failing sync never raises — it is recorded and
reported through the API/UI.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import utcnow
from ..models import Game, Ownership, PlaySession, Storefront, SyncStatus, get_or_create_storefront
from .assets import fetch_game_assets
from .covers import cache_cover
from .igdb import game_fields
from .matching import normalize_title, pick_best_igdb_match
from .storefront_base import RecentPlay, StorefrontAdapter, StoreGame

logger = logging.getLogger(__name__)


@dataclass
class SyncOutcome:
    storefront: str
    success: bool
    items_synced: int = 0
    error: str | None = None


async def _record_status(
    db: AsyncSession, storefront: str, success: bool, items_synced: int, error: str | None
) -> None:
    """Persist the sync outcome. Never raises — a failed status write must not 500 the API."""
    try:
        row = await db.scalar(select(SyncStatus).where(SyncStatus.storefront == storefront))
        if row is None:
            row = SyncStatus(storefront=storefront)
            db.add(row)
        row.last_run_at = utcnow()
        row.success = success
        row.error = error
        row.items_synced = items_synced
        await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("Failed to record sync status for %s", storefront)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass


async def _apply_igdb_detail(db: AsyncSession, game: Game, igdb, covers_dir: Path, overwrite: bool) -> None:
    """Fill missing IGDB metadata fields (and cover) on a game. Best-effort."""
    if igdb is None or not game.igdb_id:
        return
    try:
        detail = await igdb.get_game(game.igdb_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("IGDB get_game(%s) failed: %s", game.igdb_id, exc)
        return
    if not detail:
        return
    fields = game_fields(detail)

    def _set(attr: str, value) -> None:
        if value is None:
            return
        if overwrite or getattr(game, attr) in (None, "", []):
            setattr(game, attr, value)

    _set("description", fields["description"])
    _set("release_year", fields["release_year"])
    if fields["genres"]:
        _set("genres", ", ".join(fields["genres"]))
    if fields["image_id"] and not game.cover_filename:
        filename = await cache_cover(igdb, fields["image_id"], covers_dir)
        if filename:
            game.cover_filename = filename


async def _resolve_game(
    db: AsyncSession,
    item: StoreGame,
    storefront: Storefront,
    adapter: StorefrontAdapter,
    igdb,
    covers_dir: Path,
) -> Game:
    """Find or create the Game row for one storefront library entry."""
    # 1. already linked via ownership on this storefront?
    ownership = await db.scalar(
        select(Ownership).where(
            Ownership.storefront_id == storefront.id,
            Ownership.store_product_id == item.product_id,
        )
    )
    if ownership is not None:
        game = await db.scalar(select(Game).where(Game.id == ownership.game_id))
        assert game is not None
        return game

    igdb_id: int | None = None
    # 2. match by storefront product id through IGDB external_games
    if igdb is not None and adapter.igdb_external_category is not None:
        try:
            igdb_id = await igdb.find_by_external(adapter.igdb_external_category, item.product_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("IGDB external lookup for %s failed: %s", item.product_id, exc)

    game: Game | None = None
    if igdb_id is not None:
        game = await db.scalar(select(Game).where(Game.igdb_id == igdb_id))
        if game is None:
            game = Game(title=item.title, igdb_id=igdb_id)
            db.add(game)

    # 3. fall back to IGDB title search
    if game is None and igdb is not None:
        try:
            candidates = await igdb.search_games(item.title, limit=10)
            match = pick_best_igdb_match(item.title, candidates)
            if match is not None:
                game = await db.scalar(select(Game).where(Game.igdb_id == int(match["id"])))
                if game is None:
                    fields = game_fields(match)
                    game = Game(
                        title=fields["title"] or item.title,
                        igdb_id=int(match["id"]),
                        description=fields["description"],
                        release_year=fields["release_year"],
                        genres=", ".join(fields["genres"]) if fields["genres"] else None,
                    )
                    db.add(game)
                    if fields["image_id"]:
                        filename = await cache_cover(igdb, fields["image_id"], covers_dir)
                        if filename:
                            game.cover_filename = filename
        except Exception as exc:  # noqa: BLE001
            logger.warning("IGDB title search for %r failed: %s", item.title, exc)
            game = None

    # 4. match an existing (e.g. manual) game by normalized title
    if game is None:
        result = await db.execute(select(Game))
        for existing in result.scalars().all():
            if normalize_title(existing.title) == normalize_title(item.title):
                game = existing
                break

    # 5. create a bare game
    if game is None:
        game = Game(title=item.title)
        db.add(game)
        await db.flush()

    # enrich missing metadata from IGDB (never overwrites existing data)
    await _apply_igdb_detail(db, game, igdb, covers_dir, overwrite=False)
    return game


async def _upsert_ownership(
    db: AsyncSession,
    game: Game,
    storefront: Storefront,
    item: StoreGame,
    recent: RecentPlay | None,
) -> Ownership:
    ownership = await db.scalar(
        select(Ownership).where(
            Ownership.game_id == game.id,
            Ownership.storefront_id == storefront.id,
        )
    )
    prev_playtime = ownership.playtime_minutes if ownership else 0
    prev_last_played = ownership.last_played_at if ownership else None
    now = utcnow()

    if ownership is None:
        ownership = Ownership(
            game_id=game.id,
            storefront_id=storefront.id,
            store_product_id=item.product_id,
            acquired_at=now,
        )
        db.add(ownership)
    else:
        ownership.store_product_id = item.product_id
    ownership.last_synced_at = now
    ownership.playtime_minutes = item.playtime_minutes  # storefront playtime is authoritative
    if item.last_played_at is not None:
        ownership.last_played_at = item.last_played_at
    if recent is not None:
        ownership.recent_playtime_minutes = recent.playtime_recent_minutes

    # Derive a play session from the playtime delta observed between two syncs.
    if (
        item.playtime_minutes > prev_playtime
        and item.last_played_at is not None
        and prev_last_played is not None
        and item.last_played_at > prev_last_played
    ):
        delta_minutes = item.playtime_minutes - prev_playtime
        db.add(
            PlaySession(
                game_id=game.id,
                started_at=prev_last_played,
                ended_at=item.last_played_at,
                source="steam",
            )
        )
        _ = delta_minutes  # duration is implied by started/ended; kept for clarity
    return ownership


# Serializes syncs within this process so the scheduler job and a manual
# POST /api/sync/steam never write to SQLite concurrently.
_SYNC_LOCK = asyncio.Lock()


async def sync_storefront(
    db: AsyncSession,
    adapter: StorefrontAdapter,
    igdb,
    covers_dir: Path,
    sgdb=None,
) -> SyncOutcome:
    """Sync one storefront. Never raises: failures are recorded in sync_status."""
    async with _SYNC_LOCK:
        return await _sync_storefront_locked(db, adapter, igdb, covers_dir, sgdb)


async def _sync_storefront_locked(
    db: AsyncSession,
    adapter: StorefrontAdapter,
    igdb,
    covers_dir: Path,
    sgdb=None,
) -> SyncOutcome:
    name = adapter.name
    try:
        library = await adapter.fetch_library()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Sync of %s failed", name)
        await _record_status(db, name, False, 0, f"{type(exc).__name__}: {exc}")
        return SyncOutcome(name, False, 0, str(exc))

    recent_by_product: dict[str, RecentPlay] = {}
    try:
        for entry in await adapter.fetch_recently_played():
            recent_by_product[entry.product_id] = entry
    except Exception as exc:  # noqa: BLE001 - recently-played is best-effort
        logger.warning("Recently-played fetch for %s failed: %s", name, exc)

    storefront = await get_or_create_storefront(db, name)
    count = 0
    try:
        for item in library:
            game = await _resolve_game(db, item, storefront, adapter, igdb, covers_dir)
            await _upsert_ownership(db, game, storefront, item, recent_by_product.get(item.product_id))
            if sgdb is not None and (
                not game.cover_filename or not game.icon_filename or not game.logo_filename
            ):
                # best-effort SteamGridDB art (fills only what is missing); steam product id = appid
                steam_appid = item.product_id if adapter.name == "steam" else None
                await fetch_game_assets(game, sgdb, covers_dir, steam_appid=steam_appid, overwrite=False)
            count += 1
            if count % 20 == 0:
                # commit in chunks so the SQLite write lock is not held for the
                # whole sync (lets concurrent short writes, e.g. PATCH, through)
                await db.commit()
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.exception("Sync of %s failed mid-apply", name)
        await _record_status(db, name, False, 0, f"{type(exc).__name__}: {exc}")
        return SyncOutcome(name, False, 0, str(exc))

    await _record_status(db, name, True, count, None)
    return SyncOutcome(name, True, count, None)
