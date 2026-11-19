"""IGDB-assisted search for the add-game form. Requires auth."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import get_igdb_client
from ..schemas import IgdbSearchResult
from ..services.igdb import cover_url, game_fields

router = APIRouter(prefix="/api/igdb", tags=["igdb"])


@router.get("/search", response_model=list[IgdbSearchResult])
async def igdb_search(q: str = Query(min_length=1, max_length=200), igdb=Depends(get_igdb_client)):
    if igdb is None:
        raise HTTPException(status_code=400, detail="IGDB is not configured: set IGDB_CLIENT_ID and IGDB_CLIENT_SECRET.")
    try:
        results = await igdb.search_games(q, limit=10)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"IGDB search failed: {exc}") from exc
    out: list[IgdbSearchResult] = []
    for raw in results:
        fields = game_fields(raw)
        out.append(
            IgdbSearchResult(
                igdb_id=int(raw["id"]),
                title=fields["title"] or "",
                release_year=fields["release_year"],
                summary=fields["description"],
                cover_url=cover_url(fields["image_id"]) if fields["image_id"] else None,
            )
        )
    return out
