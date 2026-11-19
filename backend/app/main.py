"""FastAPI application factory + module-level `app` for uvicorn.

Run locally:  uvicorn app.main:app --port 8787   (from backend/, with env vars set)
In Docker:    the image sets FRONTEND_DIST=/app/static and DATA_DIR=/data.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from .auth.dependencies import require_auth
from .auth.password import ensure_password_hash
from .config import Settings, get_settings
from .database import Base, get_db, make_engine, make_session_factory
from .models import seed_storefronts
from .routers import auth as auth_router
from .routers import games as games_router
from .routers import igdb as igdb_router
from .routers import library as library_router
from .routers import sync as sync_router
from .scheduler.jobs import build_scheduler
from .services.igdb import IgdbClient
from .services.steam import SteamAdapter

logger = logging.getLogger(__name__)


def _frontend_dist(settings: Settings) -> Path:
    candidates = []
    if settings.FRONTEND_DIST:
        candidates.append(Path(settings.FRONTEND_DIST))
    here = Path(__file__).resolve()
    candidates.append(here.parent.parent / "static")  # Docker image layout: /app/static
    candidates.append(here.parent.parent.parent / "frontend" / "dist")  # local dev build
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


def create_app(settings: Settings | None = None, *, enable_scheduler: bool = True) -> FastAPI:
    settings = settings or get_settings()
    if not settings.APP_PASSWORD:
        raise RuntimeError(
            "APP_PASSWORD is not set. Provide it via the environment or a .env file "
            "(see .env.example). The app refuses to start without it."
        )

    data_dir = Path(settings.DATA_DIR)
    data_dir.mkdir(parents=True, exist_ok=True)
    settings.covers_dir.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with app.state.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with app.state.session_factory() as db:
            await seed_storefronts(db)
            await ensure_password_hash(db, settings.APP_PASSWORD)
            await db.commit()
        if enable_scheduler:
            app.state.scheduler = build_scheduler(
                settings,
                app.state.session_factory,
                app.state.steam_adapter_factory,
                app.state.igdb_client_factory,
            )
            app.state.scheduler.start()
            logger.info("Scheduler started (steam sync every %sh)", settings.SYNC_INTERVAL_HOURS)
        yield
        if app.state.scheduler is not None:
            app.state.scheduler.shutdown(wait=False)
        await app.state.engine.dispose()

    app = FastAPI(title="PlayLog — Game Library Server", version="1.0.0", lifespan=lifespan)

    app.state.settings = settings
    app.state.engine = make_engine(settings)
    app.state.session_factory = make_session_factory(app.state.engine)
    app.state.steam_adapter_factory = (
        lambda: SteamAdapter(settings.STEAM_API_KEY, settings.STEAM_ID64) if settings.steam_configured else None
    )
    app.state.igdb_client_factory = (
        lambda: IgdbClient(settings.IGDB_CLIENT_ID, settings.IGDB_CLIENT_SECRET)
        if settings.igdb_configured
        else None
    )
    app.state.scheduler = None

    # auth router is public; everything else requires a session
    app.include_router(auth_router.router)
    for router in (games_router.router, sync_router.router, igdb_router.router, library_router.router):
        app.include_router(router, dependencies=[Depends(require_auth)])

    dist = _frontend_dist(settings)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        """Serve built SPA assets; fall back to index.html for client-side routes."""
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        if dist.is_dir():
            candidate = (dist / full_path).resolve()
            try:
                candidate.relative_to(dist.resolve())
            except ValueError:
                candidate = dist / "index.html"
            if candidate.is_file():
                return FileResponse(candidate)
            index = dist / "index.html"
            if index.is_file():
                return FileResponse(index)
        return JSONResponse({"detail": "Frontend not built yet"}, status_code=404)

    return app


app = create_app()
