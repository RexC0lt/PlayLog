"""Pydantic schemas for API input/output."""

from .auth import LoginRequest, TokenResponse
from .game import (
    GameCreate,
    GameOut,
    GamePatch,
    OwnershipOut,
    SessionCreate,
    SessionOut,
    csv_to_list,
    list_to_csv,
)
from .igdb import IgdbSearchResult
from .sync import RecentlyPlayedItem, SyncStatusOut

__all__ = [
    "GameCreate",
    "GameOut",
    "GamePatch",
    "IgdbSearchResult",
    "LoginRequest",
    "OwnershipOut",
    "RecentlyPlayedItem",
    "SessionCreate",
    "SessionOut",
    "SyncStatusOut",
    "TokenResponse",
    "csv_to_list",
    "list_to_csv",
]
