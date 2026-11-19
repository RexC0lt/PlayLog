"""Sync status + manual sync trigger. All routes require auth."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from ..database import get_db
from ..deps import get_igdb_client, get_steam_adapter
from ..models import Storefront, SyncStatus
from ..schemas import SyncStatusOut
from ..services.sync_service import sync_storefront

router = APIRouter(prefix="/api/sync", tags=["sync"])


async def _status_rows(db) -> list[SyncStatusOut]:
    storefronts = (await db.execute(select(Storefront).order_by(Storefront.name))).scalars().all()
    statuses = {
        s.storefront: s for s in (await db.execute(select(SyncStatus))).scalars().all()
    }
    out: list[SyncStatusOut] = []
    for sf in storefronts:
        st = statuses.get(sf.name)
        out.append(
            SyncStatusOut(
                storefront=sf.name,
                last_run_at=st.last_run_at if st else None,
                success=st.success if st else None,
                error=st.error if st else None,
                items_synced=st.items_synced if st else None,
            )
        )
    return out


@router.get("/status", response_model=list[SyncStatusOut])
async def sync_status(db=Depends(get_db)):
    return await _status_rows(db)


@router.post("/steam", response_model=SyncStatusOut)
async def trigger_steam_sync(
    request: Request,
    db=Depends(get_db),
    adapter=Depends(get_steam_adapter),
    igdb=Depends(get_igdb_client),
):
    if adapter is None:
        raise HTTPException(
            status_code=400,
            detail="Steam is not configured: set STEAM_API_KEY and STEAM_ID64.",
        )
    settings = request.app.state.settings
    outcome = await sync_storefront(db, adapter, igdb, settings.covers_dir)
    rows = await _status_rows(db)
    for row in rows:
        if row.storefront == outcome.storefront:
            return row
    return SyncStatusOut(
        storefront=outcome.storefront,
        last_run_at=None,
        success=outcome.success,
        error=outcome.error,
        items_synced=outcome.items_synced,
    )
