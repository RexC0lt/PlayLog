"""Storefront, ownership and per-storefront sync status models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base, UTCDateTime, utcnow

DEFAULT_STOREFRONTS = ("steam", "epic", "gog", "manual")


class Storefront(Base):
    __tablename__ = "storefronts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, index=True)  # steam | epic | gog | manual
    external_user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    ownerships: Mapped[list["Ownership"]] = relationship(back_populates="storefront")


class Ownership(Base):
    __tablename__ = "ownerships"
    __table_args__ = (UniqueConstraint("game_id", "storefront_id", name="uq_ownership_game_storefront"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"))
    storefront_id: Mapped[int] = mapped_column(ForeignKey("storefronts.id", ondelete="CASCADE"))
    store_product_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    acquired_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    # authoritative playtime reported by the storefront (minutes); 0 for manual entries
    playtime_minutes: Mapped[int] = mapped_column(Integer, default=0)
    # playtime in the last 2 weeks, when the storefront reports it
    recent_playtime_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_played_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    game: Mapped["Game"] = relationship(back_populates="ownerships")
    storefront: Mapped[Storefront] = relationship(back_populates="ownerships")


class SyncStatus(Base):
    """Last sync outcome per storefront; survives restarts so the UI can show it."""

    __tablename__ = "sync_status"

    id: Mapped[int] = mapped_column(primary_key=True)
    storefront: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    items_synced: Mapped[int | None] = mapped_column(Integer, nullable=True)


async def seed_storefronts(db: AsyncSession) -> None:
    """Ensure the well-known storefront rows exist (epic/gog are placeholders for now)."""
    result = await db.execute(select(Storefront))
    existing = {s.name for s in result.scalars().all()}
    for name in DEFAULT_STOREFRONTS:
        if name not in existing:
            db.add(Storefront(name=name))


async def get_or_create_storefront(db: AsyncSession, name: str) -> Storefront:
    storefront = await db.scalar(select(Storefront).where(Storefront.name == name))
    if storefront is None:
        storefront = Storefront(name=name)
        db.add(storefront)
        await db.flush()
    return storefront
