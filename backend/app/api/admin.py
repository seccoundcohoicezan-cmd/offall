"""User management for the instance owner (role=admin)."""

import uuid
from datetime import timedelta

from fastapi import APIRouter, Query
from sqlalchemy import func, or_, select, update

from app.core.deps import DB, AdminUser, AppSettings
from app.core.errors import ApiError, not_found
from app.core.security import hash_password
from app.db.base import utcnow
from app.models import ACTIVE_JOB_STATUSES, Chat, Job, JobStatus, Provider, RefreshToken, UsageLog, User
from app.schemas import (
    AdminUserIn,
    AdminUserOut,
    AdminUserPatch,
    InstanceSettings,
    InstanceSettingsPatch,
    Page,
)
from app.services import app_settings

router = APIRouter(prefix="/admin", tags=["admin"])


async def _stats(db: DB, ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
    stats: dict[uuid.UUID, dict[str, int]] = {i: {"chats": 0, "tokens_30d": 0, "providers": 0} for i in ids}
    if not ids:
        return stats
    for uid, n in await db.execute(
        select(Chat.user_id, func.count()).where(Chat.user_id.in_(ids)).group_by(Chat.user_id)
    ):
        stats[uid]["chats"] = int(n)
    for uid, n in await db.execute(
        select(Provider.user_id, func.count()).where(Provider.user_id.in_(ids)).group_by(Provider.user_id)
    ):
        stats[uid]["providers"] = int(n)
    since = utcnow() - timedelta(days=30)
    for uid, n in await db.execute(
        select(UsageLog.user_id, func.sum(UsageLog.tokens_in + UsageLog.tokens_out))
        .where(UsageLog.user_id.in_(ids), UsageLog.created_at >= since)
        .group_by(UsageLog.user_id)
    ):
        stats[uid]["tokens_30d"] = int(n or 0)
    return stats


def _out(user: User, stats: dict[str, int]) -> AdminUserOut:
    return AdminUserOut(
        id=user.id,
        email=user.email,
        role=user.role,
        display_name=user.display_name,
        is_active=user.is_active,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        **stats,
    )


@router.get("/users", response_model=Page[AdminUserOut])
async def list_users(
    db: DB,
    _: AdminUser,
    q: str = "",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[AdminUserOut]:
    base = select(User)
    if q.strip():
        like = f"%{q.strip().lower()}%"
        base = base.where(or_(func.lower(User.email).like(like), func.lower(User.display_name).like(like)))
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    users = (await db.scalars(base.order_by(User.created_at).limit(limit).offset(offset))).all()
    stats = await _stats(db, [u.id for u in users])
    return Page(items=[_out(u, stats[u.id]) for u in users], total=total, limit=limit, offset=offset)


@router.post("/users", response_model=AdminUserOut, status_code=201)
async def create_user(body: AdminUserIn, db: DB, _: AdminUser) -> AdminUserOut:
    email = body.email.lower()
    if await db.scalar(select(User.id).where(User.email == email)):
        raise ApiError(409, "email_taken", "Email sudah terdaftar.")
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        role=body.role,
        display_name=body.display_name,
    )
    db.add(user)
    await db.commit()
    return _out(user, {"chats": 0, "tokens_30d": 0, "providers": 0})


async def _admin_count(db: DB) -> int:
    return int(
        await db.scalar(
            select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True))
        )
        or 0
    )


async def _revoke_sessions(db: DB, user_id: uuid.UUID) -> None:
    await db.execute(update(RefreshToken).where(RefreshToken.user_id == user_id).values(revoked=True))


@router.patch("/users/{user_id}", response_model=AdminUserOut)
async def patch_user(user_id: uuid.UUID, body: AdminUserPatch, db: DB, admin: AdminUser) -> AdminUserOut:
    user = await db.get(User, user_id)
    if user is None:
        raise not_found("user")
    losing_admin = (
        user.role == "admin" and user.is_active and (body.role == "user" or body.is_active is False)
    )
    if losing_admin and await _admin_count(db) <= 1:
        raise ApiError(400, "last_admin", "Minimal harus ada satu admin aktif.")
    if user.id == admin.id and body.is_active is False:
        raise ApiError(400, "self_disable", "Tidak bisa menonaktifkan akun sendiri.")
    if body.role is not None:
        user.role = body.role
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.password:
        user.password_hash = hash_password(body.password)
        await _revoke_sessions(db, user.id)
    if body.is_active is not None:
        user.is_active = body.is_active
        if not body.is_active:
            await _revoke_sessions(db, user.id)
            # Stop the user's queued work too; it would run on their keys after the ban.
            await db.execute(
                update(Job)
                .where(Job.user_id == user.id, Job.status.in_(ACTIVE_JOB_STATUSES))
                .values(status=JobStatus.cancelled, finished_at=utcnow(), error="akun dinonaktifkan")
            )
    await db.commit()
    stats = await _stats(db, [user.id])
    return _out(user, stats[user.id])


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: uuid.UUID, db: DB, admin: AdminUser) -> None:
    user = await db.get(User, user_id)
    if user is None:
        raise not_found("user")
    if user.id == admin.id:
        raise ApiError(400, "self_delete", "Tidak bisa menghapus akun sendiri.")
    if user.role == "admin" and await _admin_count(db) <= 1:
        raise ApiError(400, "last_admin", "Minimal harus ada satu admin aktif.")
    await db.delete(user)
    await db.commit()


@router.get("/settings", response_model=InstanceSettings)
async def get_instance_settings(db: DB, _: AdminUser, settings: AppSettings) -> InstanceSettings:
    return InstanceSettings(**await app_settings.get_all(db, settings))


@router.patch("/settings", response_model=InstanceSettings)
async def patch_instance_settings(
    body: InstanceSettingsPatch, db: DB, _: AdminUser, settings: AppSettings
) -> InstanceSettings:
    values = await app_settings.set_values(db, settings, body.model_dump(exclude_none=True))
    return InstanceSettings(**values)
