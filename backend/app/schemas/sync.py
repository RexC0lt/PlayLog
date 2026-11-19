"""Sync status and recently-played schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SyncStatusOut(BaseModel):
    storefront: str
    last_run_at: datetime | None = None
    success: bool | None = None
    error: str | None = None
    items_synced: int | None = None


class RecentlyPlayedItem(BaseModel):
    game_id: int
    title: str
    cover_url: str | None = None
    storefront: str | None = None
    last_played_at: datetime
    recent_playtime_minutes: int | None = None
    total_playtime_minutes: int = 0
