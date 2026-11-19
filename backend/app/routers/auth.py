"""Authentication routes. Only these are reachable without a session."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from ..auth.dependencies import SESSION_COOKIE, require_auth
from ..auth.password import create_token, ensure_password_hash, verify_app_password
from ..database import get_db
from ..schemas import LoginRequest, TokenResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, request: Request, response: Response, db=Depends(get_db)):
    settings = request.app.state.settings
    if not await verify_app_password(db, payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")
    token, expires_at = create_token(settings.APP_PASSWORD, settings.SESSION_TTL_HOURS)
    from ..database import utcnow

    max_age = max(0, int((expires_at - utcnow()).total_seconds()))
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=False,  # served over the private tailnet, plain HTTP
        path="/",
    )
    return TokenResponse(access_token=token, token_type="bearer", expires_at=expires_at)


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
async def me(_payload: dict = Depends(require_auth)):
    return {"authenticated": True}


# Re-exported for tests / startup wiring.
__all__ = ["router", "ensure_password_hash"]
