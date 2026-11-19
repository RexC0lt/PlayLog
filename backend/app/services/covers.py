"""Cover caching: download once into data/covers, serve locally afterwards."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def cache_cover(igdb, image_id: str, covers_dir: Path) -> str | None:
    """Download a cover via the IGDB client. Never raises — returns None on failure."""
    if not image_id:
        return None
    try:
        return await igdb.download_cover(image_id, covers_dir)
    except Exception as exc:  # noqa: BLE001 - cover caching must never break a sync
        logger.warning("Failed to cache cover %s: %s", image_id, exc)
        return None


def cover_file(covers_dir: Path, filename: str | None) -> Path | None:
    """Resolve a stored cover filename safely (no path traversal)."""
    if not filename or Path(filename).name != filename:
        return None
    path = (covers_dir / filename).resolve()
    if path.parent != covers_dir.resolve():
        return None
    return path if path.is_file() else None
