"""FastAPI dependency guarding all API routes except login."""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from .password import decode_token

SESSION_COOKIE = "playlog_session"


def extract_token(request: Request) -> str | None:
    header = request.headers.get("Authorization")
    if header and header.startswith("Bearer "):
        return header[len("Bearer "):]
    return request.cookies.get(SESSION_COOKIE)


async def require_auth(request: Request) -> dict:
    token = extract_token(request)
    payload = decode_token(request.app.state.settings.APP_PASSWORD, token) if token else None
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return payload
