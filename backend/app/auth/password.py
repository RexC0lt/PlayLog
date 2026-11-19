"""Password hashing and JWT session tokens.

Only the salted bcrypt hash of APP_PASSWORD is persisted (in the auth_config table).
The JWT signing key is derived at runtime from APP_PASSWORD, so no extra secret
needs to be stored anywhere.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.auth import AuthConfig

JWT_ALGORITHM = "HS256"


def _prehash(password: str) -> bytes:
    # bcrypt is limited to 72 bytes; pre-hashing with SHA-256 lets any password length work.
    return hashlib.sha256(password.encode("utf-8")).digest()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(password), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def session_secret(app_password: str) -> bytes:
    """Derive the JWT signing key from APP_PASSWORD (never stored anywhere)."""
    return hashlib.sha256(("playlog/session/v1:" + app_password).encode("utf-8")).digest()


def create_token(app_password: str, ttl_hours: int) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=ttl_hours)
    payload = {"sub": "owner", "iat": now, "exp": expires_at}
    token = jwt.encode(payload, session_secret(app_password), algorithm=JWT_ALGORITHM)
    return token, expires_at


def decode_token(app_password: str, token: str) -> dict | None:
    try:
        return jwt.decode(token, session_secret(app_password), algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None


async def ensure_password_hash(db: AsyncSession, app_password: str) -> None:
    """Create the password hash on first start; re-hash if APP_PASSWORD was rotated."""
    row = (await db.execute(select(AuthConfig).order_by(AuthConfig.id))).scalars().first()
    if row is None:
        db.add(AuthConfig(password_hash=hash_password(app_password)))
    elif not verify_password(app_password, row.password_hash):
        row.password_hash = hash_password(app_password)
        from ..database import utcnow

        row.updated_at = utcnow()


async def verify_app_password(db: AsyncSession, app_password: str) -> bool:
    row = (await db.execute(select(AuthConfig).order_by(AuthConfig.id))).scalars().first()
    if row is None:
        return False
    return verify_password(app_password, row.password_hash)
