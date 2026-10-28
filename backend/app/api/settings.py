from fastapi import APIRouter
from sqlalchemy import select

from app.core.deps import DB, AppSettings, CurrentUser
from app.models import PushSubscription, User, default_settings
from app.schemas import PushSubIn, SettingsIn, SettingsOut

router = APIRouter(tags=["settings"])


def _out(user: User, settings: AppSettings) -> SettingsOut:
    merged = {**default_settings(), **(user.settings or {})}
    return SettingsOut(
        **merged,
        vapid_public_key=settings.vapid_public_key,
        telegram_enabled=bool(settings.telegram_bot_token),
    )


@router.get("/settings", response_model=SettingsOut)
async def get_user_settings(user: CurrentUser, settings: AppSettings) -> SettingsOut:
    return _out(user, settings)


@router.patch("/settings", response_model=SettingsOut)
async def patch_user_settings(
    body: SettingsIn, db: DB, user: CurrentUser, settings: AppSettings
) -> SettingsOut:
    # Reassign (not mutate) so SQLAlchemy notices the JSON change.
    user.settings = {**default_settings(), **(user.settings or {}), **body.model_dump(exclude_none=True)}
    await db.commit()
    return _out(user, settings)


@router.post("/push/subscribe", status_code=204)
async def push_subscribe(body: PushSubIn, db: DB, user: CurrentUser) -> None:
    existing = await db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
    if existing is None:
        db.add(PushSubscription(user_id=user.id, endpoint=body.endpoint, keys=body.keys))
    else:
        existing.user_id, existing.keys = user.id, body.keys
    await db.commit()
