"""Injectable factories so tests can override Steam/IGDB with fakes."""

from __future__ import annotations

from fastapi import Request


def get_steam_adapter(request: Request):
    return request.app.state.steam_adapter_factory()


def get_igdb_client(request: Request):
    return request.app.state.igdb_client_factory()
