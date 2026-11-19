"""Game CRUD, cover serving and manual play sessions. All routes require auth."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select

from ..database import get_db, utcnow
from ..deps import get_igdb_client
from ..models import Game, Ownership, PlaySession, get_or_create_storefront
from ..schemas import (
    GameCreate,
    GameOut,
    GamePatch,
    SessionCreate,
    SessionOut,
    list_to_csv,
)
from ..services.covers import cache_cover, cover_file
from ..services.igdb import game_fields
from ..services.library import build_game_outs, load_games

router = APIRouter(prefix="/api/games", tags=["games"])


@router.get("", response_model=list[GameOut])
async def list_games(
    search: str | None = None,
    storefront: str | None = None,
    status: str | None = None,
    tag: str | None = None,
    db=Depends(get_db),
):
    games = await load_games(db, search=search, storefront=storefront, status=status, tag=tag)
    return await build_game_outs(db, games)


@router.post("", response_model=GameOut, status_code=201)
async def create_game(
    payload: GameCreate,
    request: Request,
    db=Depends(get_db),
    igdb=Depends(get_igdb_client),
):
    """Manual entry. When igdb_id is given, enrich metadata + cover from IGDB."""
    settings = request.app.state.settings
    game = Game(
        title=payload.title.strip(),
        status=payload.status,
        notes=payload.notes,
        rating=payload.rating,
        tags=list_to_csv(payload.tags),
    )
    if payload.igdb_id is not None:
        game.igdb_id = payload.igdb_id
        if igdb is not None:
            try:
                detail = await igdb.get_game(payload.igdb_id)
                if detail:
                    fields = game_fields(detail)
                    game.title = fields["title"] or game.title
                    game.description = fields["description"]
                    game.release_year = fields["release_year"]
                    game.genres = ", ".join(fields["genres"]) if fields["genres"] else None
                    if fields["image_id"]:
                        filename = await cache_cover(igdb, fields["image_id"], settings.covers_dir)
                        if filename:
                            game.cover_filename = filename
            except Exception:
                pass  # IGDB enrichment is best-effort; the manual entry still works
    db.add(game)
    await db.flush()
    manual = await get_or_create_storefront(db, "manual")
    db.add(
        Ownership(
            game_id=game.id,
            storefront_id=manual.id,
            store_product_id=None,
            acquired_at=utcnow(),
            last_synced_at=utcnow(),
        )
    )
    await db.commit()
    return (await build_game_outs(db, [game]))[0]


@router.get("/{game_id}", response_model=GameOut)
async def get_game(game_id: int, db=Depends(get_db)):
    game = await db.get(Game, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    return (await build_game_outs(db, [game]))[0]


@router.patch("/{game_id}", response_model=GameOut)
async def patch_game(game_id: int, payload: GamePatch, db=Depends(get_db)):
    game = await db.get(Game, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    data = payload.model_dump(exclude_unset=True)
    if "tags" in data:
        data["tags"] = list_to_csv(data["tags"])
    for key, value in data.items():
        setattr(game, key, value)
    await db.commit()
    return (await build_game_outs(db, [game]))[0]


@router.get("/{game_id}/cover")
async def get_cover(game_id: int, request: Request, db=Depends(get_db)):
    """Serve the locally cached cover image (downloaded once at sync/add time)."""
    game = await db.get(Game, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    path = cover_file(request.app.state.settings.covers_dir, game.cover_filename)
    if path is None:
        raise HTTPException(status_code=404, detail="No cached cover for this game")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/{game_id}/sessions", response_model=list[SessionOut])
async def list_sessions(game_id: int, db=Depends(get_db)):
    game = await db.get(Game, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    result = await db.execute(
        select(PlaySession).where(PlaySession.game_id == game_id).order_by(PlaySession.started_at.desc())
    )
    return [
        SessionOut(
            id=s.id, game_id=s.game_id, started_at=s.started_at, ended_at=s.ended_at, source=s.source
        )
        for s in result.scalars().all()
    ]


@router.post("/{game_id}/sessions", response_model=SessionOut, status_code=201)
async def add_session(game_id: int, payload: SessionCreate, db=Depends(get_db)):
    """Manually log a play session (for DRM-free/retro titles without a storefront)."""
    game = await db.get(Game, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    if payload.ended_at < payload.started_at:
        raise HTTPException(status_code=400, detail="ended_at must be after started_at")
    session = PlaySession(
        game_id=game_id,
        started_at=payload.started_at,
        ended_at=payload.ended_at,
        source="manual",
    )
    db.add(session)
    await db.commit()
    return SessionOut(
        id=session.id,
        game_id=session.game_id,
        started_at=session.started_at,
        ended_at=session.ended_at,
        source=session.source,
    )
