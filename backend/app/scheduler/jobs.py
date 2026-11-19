"""APScheduler jobs running inside the FastAPI process."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from ..services.sync_service import sync_storefront

logger = logging.getLogger(__name__)


def build_scheduler(settings, session_factory, steam_adapter_factory, igdb_client_factory) -> AsyncIOScheduler:
    """Build the scheduler. Steam syncs every SYNC_INTERVAL_HOURS (and once at startup)."""
    scheduler = AsyncIOScheduler()
    if settings.steam_configured:

        async def steam_sync_job() -> None:
            try:
                async with session_factory() as db:
                    outcome = await sync_storefront(
                        db, steam_adapter_factory(), igdb_client_factory(), settings.covers_dir
                    )
                logger.info(
                    "Steam sync finished: success=%s items=%s error=%s",
                    outcome.success, outcome.items_synced, outcome.error,
                )
            except Exception:  # noqa: BLE001 - a job must never kill the scheduler
                logger.exception("Steam sync job crashed")

        scheduler.add_job(
            steam_sync_job,
            trigger=IntervalTrigger(hours=settings.SYNC_INTERVAL_HOURS),
            id="steam_sync",
            name="Steam library sync",
            next_run_time=datetime.now(timezone.utc),  # also run once at startup
            misfire_grace_time=600,
            coalesce=True,
            max_instances=1,
            replace_existing=True,
        )
    else:
        logger.info("Steam credentials not configured; automatic sync disabled.")
    return scheduler
