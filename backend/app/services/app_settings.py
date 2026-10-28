"""Instance settings stored in the DB so the admin can change them without a redeploy."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import AppSetting


def defaults(cfg: Settings) -> dict[str, Any]:
    return {"registration_open": cfg.registration_open}


async def get_all(db: AsyncSession, cfg: Settings) -> dict[str, Any]:
    values = defaults(cfg)
    for key in values:
        row = await db.get(AppSetting, key)
        if row is not None:
            values[key] = row.value
    return values


async def set_values(db: AsyncSession, cfg: Settings, changes: dict[str, Any]) -> dict[str, Any]:
    for key, value in changes.items():
        if key not in defaults(cfg):
            continue
        row = await db.get(AppSetting, key)
        if row is None:
            db.add(AppSetting(key=key, value=value))
        else:
            row.value = value
    await db.commit()
    return await get_all(db, cfg)
