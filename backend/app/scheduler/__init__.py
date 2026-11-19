"""In-process APScheduler setup."""

from .jobs import build_scheduler

__all__ = ["build_scheduler"]
