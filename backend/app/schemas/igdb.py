"""IGDB search result schema."""

from __future__ import annotations

from pydantic import BaseModel


class IgdbSearchResult(BaseModel):
    igdb_id: int
    title: str
    release_year: int | None = None
    summary: str | None = None
    cover_url: str | None = None  # remote IGDB thumbnail, used only in the add-game picker
