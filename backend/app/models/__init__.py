"""Database models. Importing this package registers every table on Base.metadata."""

from .auth import AuthConfig
from .game import BacklogStatus, Game
from .session import PlaySession
from .storefront import Ownership, Storefront, SyncStatus, get_or_create_storefront, seed_storefronts

__all__ = [
    "AuthConfig",
    "BacklogStatus",
    "Game",
    "Ownership",
    "PlaySession",
    "Storefront",
    "SyncStatus",
    "get_or_create_storefront",
    "seed_storefronts",
]
