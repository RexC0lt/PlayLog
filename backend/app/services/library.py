"""Library query helpers shared by routers: filtering + aggregate stats."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Game, Ownership, PlaySession, Storefront
from ..schemas import GameOut, OwnershipOut, csv_to_list, list_to_csv  # noqa: F401  (re-export helpers)


async def load_games(
    db: AsyncSession,
    search: str | None = None,
    storefront: str | None = None,
    status: str | None = None,
    tag: str | None = None,
) -> list[Game]:
    stmt = select(Game)
    if search:
        stmt = stmt.where(Game.title.ilike(f"%{search}%"))
    if status:
        stmt = stmt.where(Game.status == status)
    if tag:
        stmt = stmt.where(Game.tags.ilike(f"%{tag}%"))
    if storefront:
        stmt = (
            stmt.join(Ownership, Ownership.game_id == Game.id)
            .join(Storefront, Storefront.id == Ownership.storefront_id)
            .where(Storefront.name == storefront)
        )
    stmt = stmt.order_by(Game.title.asc()).distinct()
    result = await db.execute(stmt)
    return list(result.scalars().all())


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
                icon_filename=game.icon_filename,
                logo_filename=game.logo_filename,
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
