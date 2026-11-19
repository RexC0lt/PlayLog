"""Game model plus user-managed metadata fields."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base, UTCDateTime, utcnow


class BacklogStatus(str, enum.Enum):
    UNPLAYED = "unplayed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300), index=True)
    igdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_filename: Mapped[str | None] = mapped_column(String(200), nullable=True)
    release_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    genres: Mapped[str | None] = mapped_column(String(500), nullable=True)  # comma-separated

    # user-managed metadata
    status: Mapped[str] = mapped_column(String(20), default=BacklogStatus.UNPLAYED.value)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-10
    tags: Mapped[str | None] = mapped_column(String(500), nullable=True)  # comma-separated

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    ownerships: Mapped[list["Ownership"]] = relationship(
        back_populates="game", cascade="all, delete-orphan", lazy="selectin"
    )
    sessions: Mapped[list["PlaySession"]] = relationship(
        back_populates="game", cascade="all, delete-orphan", lazy="selectin"
    )
