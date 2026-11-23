"""Game CRUD, cover serving and manual play sessions. All routes require auth."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select  # noqa: F401  (used in refresh_assets)

from ..database import get_db, utcnow
from ..deps import get_igdb_client, get_sgdb_client
from ..models import Game, Ownership, PlaySession, Storefront, get_or_create_storefront
from ..schemas import (
    GameCreate,
    GameOut,
    GamePatch,
    SessionCreate,
    SessionOut,
    list_to_csv,
)
from ..services.assets import fetch_game_assets
from ..services.covers import cache_cover, cover_file
from ..services.igdb import game_fields
from ..services.library import SORT_KEYS, build_game_outs, load_games, sort_game_outs

router = APIRouter(prefix="/api/games", tags=["games"])


@router.get("", response_model=list[GameOut])
async def list_games(
    search: str | None = None,
    storefront: str | None = None,
    status: str | None = None,
    tag: str | None = None,
    genre: str | None = None,
    sort: str | None = None,
    db=Depends(get_db),
):
    if sort is not None and sort not in SORT_KEYS:
        raise HTTPException(status_code=400, detail=f"sort must be one of {sorted(SORT_KEYS)}")
    games = await load_games(db, search=search, storefront=storefront, status=status, tag=tag, genre=genre)
    outs = await build_game_outs(db, games)
    return sort_game_outs(outs, sort or "title")


@router.post("", response_model=GameOut, status_code=201)
async def create_game(
    payload: GameCreate,
    request: Request,
    db=Depends(get_db),
    igdb=Depends(get_igdb_client),
    sgdb=Depends(get_sgdb_client),
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
    if sgdb is not None and (not game.cover_filename or not game.icon_filename or not game.logo_filename):
        # best-effort SteamGridDB art (fills only what is missing)
        await fetch_game_assets(game, sgdb, settings.covers_dir, steam_appid=None, overwrite=False)
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


def _media_type(path) -> str:  # noqa: ANN001
    return {
        ".png": "image/png",
        ".svg": "image/svg+xml",
        ".ico": "image/x-icon",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(path.suffix.lower(), "image/jpeg")


#: asset kinds that can be uploaded/replaced manually
ASSET_KINDS = {"cover": "cover_filename", "icon": "icon_filename", "logo": "logo_filename"}

#: content-type -> file extension for manual uploads
UPLOAD_EXTS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
    "image/x-icon": ".ico",
    "image/vnd.microsoft.icon": ".ico",
}

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


@router.put("/{game_id}/assets/{kind}", response_model=GameOut)
async def upload_asset(game_id: int, kind: str, request: Request, db=Depends(get_db)):
    """Replace one artwork asset (cover/icon/logo) with a manually uploaded image.

    Raw request body = image bytes; Content-Type must be an image/* type.
    """
    attr = ASSET_KINDS.get(kind)
    if attr is None:
        raise HTTPException(status_code=400, detail=f"kind must be one of {sorted(ASSET_KINDS)}")
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    ext = UPLOAD_EXTS.get(content_type)
    if ext is None:
        raise HTTPException(status_code=415, detail=f"Unsupported content type {content_type!r}; upload an image (png/jpeg/webp/gif/svg/ico).")
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty body")
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 10 MB)")
    game = await db.get(Game, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    settings = request.app.state.settings
    settings.covers_dir.mkdir(parents=True, exist_ok=True)
    filename = f"manual_{kind}_{game_id}{ext}"
    (settings.covers_dir / filename).write_bytes(body)
    setattr(game, attr, filename)
    await db.commit()
    return (await build_game_outs(db, [game]))[0]


@router.delete("/{game_id}/assets/{kind}", response_model=GameOut)
async def delete_asset(game_id: int, kind: str, request: Request, db=Depends(get_db)):
    """Clear a cached artwork asset (cover/icon/logo)."""
    attr = ASSET_KINDS.get(kind)
    if attr is None:
        raise HTTPException(status_code=400, detail=f"kind must be one of {sorted(ASSET_KINDS)}")
    game = await db.get(Game, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    old = getattr(game, attr)
    setattr(game, attr, None)
    if old and old.startswith("manual_"):  # only delete files we created via upload
        path = cover_file(request.app.state.settings.covers_dir, old)
        if path is not None:
            path.unlink(missing_ok=True)
    await db.commit()
    return (await build_game_outs(db, [game]))[0]


async def _serve_asset(game_id: int, attr: str, request: Request, db) -> FileResponse:
    game = await db.get(Game, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    path = cover_file(request.app.state.settings.covers_dir, getattr(game, attr))
    if path is None:
        raise HTTPException(status_code=404, detail=f"No cached {attr} for this game")
    return FileResponse(path, media_type=_media_type(path))


@router.get("/{game_id}/cover")
async def get_cover(game_id: int, request: Request, db=Depends(get_db)):
    """Serve the locally cached cover image (downloaded once at sync/add time)."""
    return await _serve_asset(game_id, "cover_filename", request, db)


@router.get("/{game_id}/icon")
async def get_icon(game_id: int, request: Request, db=Depends(get_db)):
    """Serve the locally cached SteamGridDB icon, if any."""
    return await _serve_asset(game_id, "icon_filename", request, db)


@router.get("/{game_id}/logo")
async def get_logo(game_id: int, request: Request, db=Depends(get_db)):
    """Serve the locally cached SteamGridDB logo, if any."""
    return await _serve_asset(game_id, "logo_filename", request, db)


@router.post("/{game_id}/assets/refresh", response_model=GameOut)
async def refresh_assets(
    game_id: int,
    request: Request,
    db=Depends(get_db),
    sgdb=Depends(get_sgdb_client),
):
    """(Re)fetch cover/icon/logo from SteamGridDB for one game.

    Matches by Steam appid when the game has a Steam ownership, else by title.
    """
    if sgdb is None:
        raise HTTPException(
            status_code=400,
            detail="SteamGridDB is not configured: set STEAMGRIDDB_API_KEY (see README).",
        )
    game = await db.get(Game, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    row = await db.execute(
        select(Ownership.store_product_id)
        .join(Storefront, Storefront.id == Ownership.storefront_id)
        .where(Ownership.game_id == game_id, Storefront.name == "steam")
    )
    steam_appid = row.scalar_one_or_none()
    await fetch_game_assets(
        game, sgdb, request.app.state.settings.covers_dir, steam_appid=steam_appid, overwrite=True
    )
    await db.commit()
    return (await build_game_outs(db, [game]))[0]


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
