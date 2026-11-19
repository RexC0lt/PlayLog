"""Application configuration, sourced entirely from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Every value comes from the environment (or a .env file)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- auth ---
    APP_PASSWORD: str = ""  # required at startup; only its hash is stored in the DB
    SESSION_TTL_HOURS: int = 24

    # --- server ---
    PORT: int = 8787
    DATA_DIR: str = "./data"  # bind-mounted volume in Docker; holds SQLite file + covers/
    FRONTEND_DIST: str = ""  # built SPA assets; auto-detected when empty

    # --- scheduler ---
    SYNC_INTERVAL_HOURS: int = 12

    # --- external services (all optional except APP_PASSWORD) ---
    STEAM_API_KEY: str = ""
    STEAM_ID64: str = ""
    IGDB_CLIENT_ID: str = ""
    IGDB_CLIENT_SECRET: str = ""
    STEAMGRIDDB_API_KEY: str = ""

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{Path(self.DATA_DIR) / 'playlog.db'}"

    @property
    def covers_dir(self) -> Path:
        return Path(self.DATA_DIR) / "covers"

    @property
    def steam_configured(self) -> bool:
        return bool(self.STEAM_API_KEY and self.STEAM_ID64)

    @property
    def igdb_configured(self) -> bool:
        return bool(self.IGDB_CLIENT_ID and self.IGDB_CLIENT_SECRET)

    @property
    def steamgriddb_configured(self) -> bool:
        return bool(self.STEAMGRIDDB_API_KEY)


@lru_cache
def get_settings() -> Settings:
    return Settings()
