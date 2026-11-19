"""Library-wide endpoints (recently played). Requires auth."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..database import get_db
from ..schemas import RecentlyPlayedItem
from ..services.library import build_game_outs, load_games

router = APIRouter(prefix="/api", tags=["library"])


@router.get("/meta")
async def meta(request: Request):
    """Which optional integrations are configured (drives UI affordances)."""
    s = request.app.state.settings
    return {
        "steam_configured": s.steam_configured,
        "igdb_configured": s.igdb_configured,
        "steamgriddb_configured": s.steamgriddb_configured,
    }


@router.get("/recently-played", response_model=list[RecentlyPlayedItem])
async def recently_played(limit: int = 10, db=Depends(get_db)):
    games = await load_games(db)
    outs = await build_game_outs(db, games)
    items: list[RecentlyPlayedItem] = []
    for g in outs:
        if g.last_played_at is None:
            continue
        recent_own = [o for o in g.ownerships if o.last_played_at == g.last_played_at]
        storefront = recent_own[0].storefront if recent_own else (g.ownerships[0].storefront if g.ownerships else None)
        recent_minutes = max(
            (o.recent_playtime_minutes for o in g.ownerships if o.recent_playtime_minutes is not None),
            default=None,
        )
        items.append(
            RecentlyPlayedItem(
                game_id=g.id,
                title=g.title,
                cover_url=g.cover_url,
                storefront=storefront,
                last_played_at=g.last_played_at,
                recent_playtime_minutes=recent_minutes,
                total_playtime_minutes=g.total_playtime_minutes,
            )
        )
    items.sort(key=lambda i: i.last_played_at, reverse=True)
    return items[: max(1, min(limit, 50))]
