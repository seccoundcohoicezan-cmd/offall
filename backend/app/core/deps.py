import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.config import Settings, get_settings
from app.core.encryption import KeyCipher
from app.core.errors import ApiError
from app.core.security import TokenError, decode_token
from app.db.session import get_session_factory
from app.models import User

ACCESS_COOKIE = "offall_access"
REFRESH_COOKIE = "offall_refresh"


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session


def get_redis(request: Request) -> Any:
    return request.app.state.redis


def get_queue(request: Request) -> Any:
    return request.app.state.queue


def get_cipher(settings: Annotated[Settings, Depends(get_settings)]) -> KeyCipher:
    return KeyCipher(settings.master_encryption_key)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _token_from(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.cookies.get(ACCESS_COOKIE)


async def current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    token = _token_from(request)
    if not token:
        raise ApiError(401, "unauthorized", "Login diperlukan.")
    try:
        payload = decode_token(settings.jwt_secret, token, "access")
    except TokenError as exc:
        raise ApiError(401, "unauthorized", "Sesi kedaluwarsa, silakan login lagi.") from exc
    user = await db.get(User, uuid.UUID(payload["sub"]))
    if user is None:
        raise ApiError(401, "unauthorized", "User tidak ditemukan.")
    if not user.is_active:
        raise ApiError(403, "account_disabled", "Akun dinonaktifkan oleh admin.")
    await ratelimit.hit(get_redis(request), f"user:{user.id}", settings.rate_limit_per_minute)
    await ratelimit.hit(get_redis(request), f"ip:{client_ip(request)}", settings.rate_limit_per_minute * 2)
    return user


DB = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(current_user)]
AppSettings = Annotated[Settings, Depends(get_settings)]
Redis = Annotated[Any, Depends(get_redis)]
Queue = Annotated[Any, Depends(get_queue)]
Cipher = Annotated[KeyCipher, Depends(get_cipher)]


async def admin_user(user: CurrentUser) -> User:
    if user.role != "admin":
        raise ApiError(403, "forbidden", "Hanya admin yang boleh mengakses ini.")
    return user


AdminUser = Annotated[User, Depends(admin_user)]
