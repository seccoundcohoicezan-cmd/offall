import uuid
from datetime import timedelta

from fastapi import APIRouter, Request, Response
from sqlalchemy import func, select, update

from app.core import ratelimit
from app.core.deps import ACCESS_COOKIE, DB, REFRESH_COOKIE, AppSettings, CurrentUser, client_ip
from app.core.errors import ApiError
from app.core.security import TokenError, create_token, decode_token, hash_password, verify_password
from app.db.base import as_utc, utcnow
from app.models import RefreshToken, User
from app.schemas import Credentials, RefreshIn, TokenOut, UserOut
from app.services import app_settings

router = APIRouter(prefix="/auth", tags=["auth"])


async def _issue(db: DB, settings: AppSettings, user: User, response: Response) -> TokenOut:
    access, _, _ = create_token(
        settings.jwt_secret, str(user.id), "access", timedelta(minutes=settings.access_token_minutes)
    )
    refresh, jti, expires = create_token(
        settings.jwt_secret, str(user.id), "refresh", timedelta(days=settings.refresh_token_days)
    )
    db.add(RefreshToken(jti=jti, user_id=user.id, expires_at=expires))
    await db.commit()
    common = {"httponly": True, "secure": settings.cookie_secure, "samesite": "lax"}
    response.set_cookie(
        ACCESS_COOKIE,
        access,
        max_age=settings.access_token_minutes * 60,
        path="/",
        **common,  # type: ignore[arg-type]
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh,
        max_age=settings.refresh_token_days * 86400,
        path="/api/v1/auth",
        **common,  # type: ignore[arg-type]
    )
    return TokenOut(access_token=access, refresh_token=refresh)


@router.post("/register", response_model=TokenOut, status_code=201)
async def register(
    body: Credentials, request: Request, response: Response, db: DB, settings: AppSettings
) -> TokenOut:
    if not (await app_settings.get_all(db, settings))["registration_open"]:
        raise ApiError(403, "registration_closed", "Pendaftaran ditutup. Minta akun ke admin.")
    await ratelimit.hit(
        request.app.state.redis, f"register:{client_ip(request)}", settings.login_rate_limit_per_minute
    )
    email = body.email.lower()
    if await db.scalar(select(User.id).where(User.email == email)):
        raise ApiError(409, "email_taken", "Email sudah terdaftar.")
    first_user = not await db.scalar(select(func.count()).select_from(User))
    user = User(
        email=email, password_hash=hash_password(body.password), role="admin" if first_user else "user"
    )
    db.add(user)
    await db.flush()
    return await _issue(db, settings, user, response)


@router.post("/login", response_model=TokenOut)
async def login(
    body: Credentials, request: Request, response: Response, db: DB, settings: AppSettings
) -> TokenOut:
    await ratelimit.hit(
        request.app.state.redis, f"login:{client_ip(request)}", settings.login_rate_limit_per_minute
    )
    user = await db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not verify_password(user.password_hash, body.password):
        raise ApiError(401, "invalid_credentials", "Email atau password salah.")
    if not user.is_active:
        raise ApiError(403, "account_disabled", "Akun dinonaktifkan oleh admin.")
    user.last_login_at = utcnow()
    return await _issue(db, settings, user, response)


@router.post("/refresh", response_model=TokenOut)
async def refresh(
    request: Request, response: Response, db: DB, settings: AppSettings, body: RefreshIn | None = None
) -> TokenOut:
    token = (body.refresh_token if body else None) or request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise ApiError(401, "unauthorized", "Refresh token tidak ada.")
    try:
        payload = decode_token(settings.jwt_secret, token, "refresh")
    except TokenError as exc:
        raise ApiError(401, "unauthorized", "Refresh token tidak valid.") from exc
    # Rotate: the old refresh token is revoked atomically, so it can be used once only.
    result = await db.execute(
        update(RefreshToken)
        .where(RefreshToken.jti == payload["jti"], RefreshToken.revoked.is_(False))
        .values(revoked=True)
    )
    if not getattr(result, "rowcount", 0):
        raise ApiError(401, "unauthorized", "Refresh token sudah dicabut.")
    stored = await db.get(RefreshToken, payload["jti"])
    if stored is None or (as_utc(stored.expires_at) or utcnow()) < utcnow():
        raise ApiError(401, "unauthorized", "Refresh token kedaluwarsa.")
    user = await db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise ApiError(401, "unauthorized", "Akun tidak aktif.")
    return await _issue(db, settings, user, response)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: DB, settings: AppSettings) -> None:
    token = request.cookies.get(REFRESH_COOKIE)
    if token:
        try:
            payload = decode_token(settings.jwt_secret, token, "refresh")
            await db.execute(
                update(RefreshToken).where(RefreshToken.jti == payload["jti"]).values(revoked=True)
            )
            await db.commit()
        except TokenError:
            pass
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")


@router.get("/config")
async def auth_config(db: DB, settings: AppSettings) -> dict[str, bool]:
    """Public: lets the login/register pages know whether self sign-up is open."""
    return {"registration_open": bool((await app_settings.get_all(db, settings))["registration_open"])}


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    return user
