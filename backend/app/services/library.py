"""Library query helpers shared by routers: filtering + aggregate stats."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Game, Ownership, PlaySession, Storefront
from ..schemas import GameOut, OwnershipOut, csv_to_list, list_to_csv  # noqa: F401  (re-export helpers)


def _like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _genre_clause(genre: str):  # noqa: ANN001
    """Exact membership match on the comma-separated genres string (no substring false positives)."""
    from sqlalchemy import or_

    g = _like_escape(genre.strip())
    return or_(
        Game.genres.ilike(g, escape="\\"),
        Game.genres.ilike(f"{g}, %", escape="\\"),
        Game.genres.ilike(f"%, {g}, %", escape="\\"),
        Game.genres.ilike(f"%, {g}", escape="\\"),
    )


async def load_games(
    db: AsyncSession,
    search: str | None = None,
    storefront: str | None = None,
    status: str | None = None,
    tag: str | None = None,
    genre: str | None = None,
) -> list[Game]:
    stmt = select(Game)
    if search:
        stmt = stmt.where(Game.title.ilike(f"%{search}%"))
    if status:
        stmt = stmt.where(Game.status == status)
    if tag:
        stmt = stmt.where(Game.tags.ilike(f"%{_like_escape(tag)}%", escape="\\"))
    if genre:
        stmt = stmt.where(_genre_clause(genre))
    if storefront:
        stmt = (
            stmt.join(Ownership, Ownership.game_id == Game.id)
            .join(Storefront, Storefront.id == Ownership.storefront_id)
            .where(Storefront.name == storefront)
        )
    stmt = stmt.order_by(Game.title.asc()).distinct()
    result = await db.execute(stmt)
    return list(result.scalars().all())


SORT_KEYS = {
    "title",
    "title_desc",
    "playtime",  # most played first
    "playtime_asc",
    "recent",  # last played, most recent first
    "year",  # newest first
    "year_asc",
    "genre",
    "genre_desc",
}


def sort_game_outs(outs: list[GameOut], sort: str = "title") -> list[GameOut]:
    """Sort game list output; games without a value go last (except where noted)."""
    if sort == "title":
        return sorted(outs, key=lambda g: g.title.lower())
    if sort == "title_desc":
        return sorted(outs, key=lambda g: g.title.lower(), reverse=True)
    if sort == "playtime":
        return sorted(outs, key=lambda g: g.total_playtime_minutes, reverse=True)
    if sort == "playtime_asc":
        return sorted(outs, key=lambda g: g.total_playtime_minutes)
    if sort == "recent":
        epoch = datetime.min.replace(tzinfo=timezone.utc)
        return sorted(outs, key=lambda g: g.last_played_at or epoch, reverse=True)
    if sort == "year":
        return sorted(outs, key=lambda g: (g.release_year is None, -(g.release_year or 0)))
    if sort == "year_asc":
        return sorted(outs, key=lambda g: (g.release_year is None, g.release_year or 0))
    if sort == "genre":
        return sorted(outs, key=lambda g: (not g.genres, g.genres[0].lower() if g.genres else "", g.title.lower()))
    if sort == "genre_desc":
        with_genre = [g for g in outs if g.genres]
        without = [g for g in outs if not g.genres]
        return (
            sorted(with_genre, key=lambda g: g.genres[0].lower(), reverse=True)
            + sorted(without, key=lambda g: g.title.lower())
        )
    return outs


async def build_game_outs(db: AsyncSession, games: list[Game]) -> list[GameOut]:
    """Attach ownerships, total playtime and last-played to each game."""
    if not games:
        return []
    ids = [g.id for g in games]

    ownerships = (
        await db.execute(
            select(Ownership, Storefront.name)
            .join(Storefront, Storefront.id == Ownership.storefront_id)
            .where(Ownership.game_id.in_(ids))
        )
    ).all()
    sessions = (
        await db.execute(select(PlaySession).where(PlaySession.game_id.in_(ids)))
    ).scalars().all()

    own_by_game: dict[int, list[tuple[Ownership, str]]] = {}
    for own, sf_name in ownerships:
        own_by_game.setdefault(own.game_id, []).append((own, sf_name))
    sessions_by_game: dict[int, list[PlaySession]] = {}
    for s in sessions:
        sessions_by_game.setdefault(s.game_id, []).append(s)

    outs: list[GameOut] = []
    for game in games:
        owns = own_by_game.get(game.id, [])
        sess = sessions_by_game.get(game.id, [])
        manual_minutes = sum(
            int((s.ended_at - s.started_at).total_seconds() // 60)
            for s in sess
            if s.source == "manual" and s.ended_at >= s.started_at
        )
        total_minutes = sum(o.playtime_minutes for o, _ in owns) + manual_minutes
        last_candidates: list[datetime] = [o.last_played_at for o, _ in owns if o.last_played_at]
        last_candidates += [s.ended_at for s in sess if s.ended_at]
        last_played = max(last_candidates) if last_candidates else None
        outs.append(
            GameOut(
                id=game.id,
                title=game.title,
                igdb_id=game.igdb_id,
                description=game.description,
                cover_url=f"/api/games/{game.id}/cover" if game.cover_filename else None,
                cover_filename=game.cover_filename,
                icon_url=f"/api/games/{game.id}/icon" if game.icon_filename else None,
                logo_url=f"/api/games/{game.id}/logo" if game.logo_filename else None,
                hero_url=f"/api/games/{game.id}/hero" if game.hero_filename else None,
                icon_filename=game.icon_filename,
                logo_filename=game.logo_filename,
                hero_filename=game.hero_filename,
                release_year=game.release_year,
                genres=csv_to_list(game.genres),
                status=game.status,  # type: ignore[arg-type]
                notes=game.notes,
                rating=game.rating,
                tags=csv_to_list(game.tags),
                created_at=game.created_at,
                total_playtime_minutes=total_minutes,
                last_played_at=last_played,
                ownerships=[
                    OwnershipOut(
                        storefront=sf_name,
                        store_product_id=o.store_product_id,
                        playtime_minutes=o.playtime_minutes,
                        recent_playtime_minutes=o.recent_playtime_minutes,
                        last_played_at=o.last_played_at,
                        acquired_at=o.acquired_at,
                        last_synced_at=o.last_synced_at,
                    )
                    for o, sf_name in owns
                ],
            )
        )
    return outs
