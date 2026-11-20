"""Common interface every storefront integration implements.

Epic Games Store and GOG adapters are intentionally not implemented yet; when they
are, they only need to subclass `StorefrontAdapter` and the existing sync pipeline
(`services.sync_service.sync_storefront`) works unchanged.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


class StorefrontError(Exception):
    """Raised when a storefront API call fails; sync records it and never crashes."""


@dataclass
class StoreGame:
    """One owned title as reported by a storefront."""

    product_id: str
    title: str
    playtime_minutes: int = 0
    last_played_at: datetime | None = None


@dataclass
class RecentPlay:
    """Recently-played information for one title (best-effort, optional)."""

    product_id: str
    playtime_recent_minutes: int = 0
    last_played_at: datetime | None = None


class StorefrontAdapter(ABC):
    """Interface for a storefront integration (steam, epic, gog, ...).

    Subclasses set the class attributes below; plain ABC (not a dataclass) so
    class-level defaults are not shadowed by a generated __init__.
    """

    #: storefront key stored in the storefronts table (steam | epic | gog | ...)
    name: str
    #: IGDB `external_game_category` value used to match store product ids
    #: (1 = steam). None means "no IGDB external-id matching for this store".
    igdb_external_category: int | None = None

    @abstractmethod
    async def fetch_library(self) -> list[StoreGame]:
        """Return every owned game with total playtime. Raise StorefrontError on failure."""

    @abstractmethod
    async def fetch_recently_played(self) -> list[RecentPlay]:
        """Return recently played games. May raise StorefrontError; callers treat it as optional."""

    async def fetch_store_genres(self, product_id: str) -> list[str]:
        """Store-reported genres for a product, if the storefront exposes them.

        Default: none. The sync uses this to fill game.genres when IGDB had none.
        Implementations must be best-effort (return [] on any failure).
        """
        return []
