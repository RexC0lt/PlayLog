"""Async SQLAlchemy engine/session setup and the FastAPI `get_db` dependency."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy import DateTime, event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    """Declarative base for all models."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Stores datetimes as naive UTC in SQLite, always returns timezone-aware UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: ANN001
        if value is None:
            return None
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):  # noqa: ANN001
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


def make_engine(settings) -> AsyncEngine:  # noqa: ANN001
    engine = create_async_engine(settings.database_url, echo=False, future=True)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):  # noqa: ANN001
        # WAL lets readers proceed while a writer commits; busy_timeout makes
        # concurrent writers wait instead of failing with "database is locked".
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=60000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


# Columns added after the initial release; applied to pre-existing databases.
GAMES_COLUMN_MIGRATIONS = (
    ("icon_filename", "VARCHAR(200)"),
    ("logo_filename", "VARCHAR(200)"),
    ("hero_filename", "VARCHAR(200)"),
)


def _migrate_sync(conn) -> None:  # noqa: ANN001
    from sqlalchemy import text

    cols = {row[1] for row in conn.execute(text("PRAGMA table_info(games)"))}
    for col, ddl in GAMES_COLUMN_MIGRATIONS:
        if col not in cols:
            conn.execute(text(f"ALTER TABLE games ADD COLUMN {col} {ddl}"))


async def migrate(engine: AsyncEngine) -> None:
    """Add any missing columns to existing tables (SQLite has no ALTER COLUMN)."""
    async with engine.begin() as conn:
        await conn.run_sync(_migrate_sync)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_db(request: Request):
    """FastAPI dependency yielding an AsyncSession bound to the app's session factory."""
    async with request.app.state.session_factory() as session:
        yield session
