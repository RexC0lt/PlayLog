"""Game-related request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

BacklogStatusLiteral = Literal["unplayed", "in_progress", "completed", "abandoned"]


def csv_to_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def list_to_csv(value: list[str] | None) -> str | None:
    if value is None:
        return None
    cleaned = [v.strip() for v in value if v and v.strip()]
    return ",".join(cleaned) if cleaned else None


class OwnershipOut(BaseModel):
    storefront: str
    store_product_id: str | None = None
    playtime_minutes: int = 0
    recent_playtime_minutes: int | None = None
    last_played_at: datetime | None = None
    acquired_at: datetime | None = None
    last_synced_at: datetime | None = None


class GameOut(BaseModel):
    id: int
    title: str
    igdb_id: int | None = None
    description: str | None = None
    cover_url: str | None = None  # local cached cover endpoint
    cover_filename: str | None = None
    icon_url: str | None = None  # local cached SteamGridDB icon
    logo_url: str | None = None  # local cached SteamGridDB logo
    icon_filename: str | None = None
    logo_filename: str | None = None
    release_year: int | None = None
    genres: list[str] = []
    status: BacklogStatusLiteral
    notes: str | None = None
    rating: int | None = None
    tags: list[str] = []
    created_at: datetime
    total_playtime_minutes: int = 0
    last_played_at: datetime | None = None
    ownerships: list[OwnershipOut] = []


class GameCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    igdb_id: int | None = None  # when set, the server enriches from IGDB
    status: BacklogStatusLiteral = "unplayed"
    notes: str | None = None
    rating: int | None = Field(default=None, ge=0, le=10)
    tags: list[str] = Field(default_factory=list)


class GamePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    status: BacklogStatusLiteral | None = None
    notes: str | None = None
    rating: int | None = Field(default=None, ge=0, le=10)
    tags: list[str] | None = None


class SessionCreate(BaseModel):
    started_at: datetime
    ended_at: datetime


class SessionOut(BaseModel):
    id: int
    game_id: int
    started_at: datetime
    ended_at: datetime
    source: str
